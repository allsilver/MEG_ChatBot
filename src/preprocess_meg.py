import os
import win32com.client as win32
import pandas as pd
import re
import time
import shutil
from datetime import datetime

# Windows 경로 최대 길이 제한 (win32com 안정성 기준)
MAX_CSV_PATH_LENGTH = 218

# --- [전처리 함수들] ---

def clean_title_logic(text):
    """
    Title 컬럼 전용 정제 함수
    예: "02-Tail cap 이탈방지" -> "Tail cap 이탈방지"
    """
    if pd.isna(text):
        return ""

    text = str(text).strip()

    # 1. 맨 앞의 숫자 인덱스 및 기호 제거
    text = re.sub(r'^[0-9\s.\-_]+', '', text)

    # 2. 괄호 제거 및 특수기호(_, -)를 공백으로 치환
    text = text.replace('(', ' ').replace(')', ' ').replace('_', ' ').replace('-', ' ')

    # 3. 연속된 공백을 하나로 합치고 앞뒤 공백 제거
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def save_error_log(error_folder, step_name, failed_files):
    """실패 파일 목록을 error 폴더에 로그로 저장"""
    if not failed_files:
        return
    os.makedirs(error_folder, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_log_path = os.path.join(error_folder, f"error_log_{step_name}_{timestamp}.txt")
    with open(error_log_path, 'w', encoding='utf-8') as f:
        f.write(f"[{step_name}] 에러 발생 파일 목록 - {timestamp}\n")
        f.write("=" * 50 + "\n")
        f.write("\n".join(failed_files))
    print(f"에러 로그 저장: {error_log_path}")


def run_2nd_preprocessing(data_root, input_file_name):
    """
    1차 저장된 semi 파일을 불러와 Title을 정제하고 final 결과물로 저장
    - 입력 컬럼: No, Title, Item, Guide, Reason
    - 출력 컬럼: Title(정제됨), Item, Guide, Reason  (No 컬럼 제외)
    """
    input_path   = os.path.join(data_root, 'result', input_file_name)
    output_path  = os.path.join(data_root, 'result', 'preprocessed_data_final.xlsx')
    error_folder = os.path.join(data_root, 'error')

    if not os.path.exists(input_path):
        print(f"원본 파일을 찾을 수 없습니다: {input_path}")
        return

    df = pd.read_excel(input_path, engine='openpyxl')
    print(f"\n2차 전처리를 위해 데이터를 로드했습니다. (총 {len(df)}행)")

    if 'Title' not in df.columns:
        print("'Title' 컬럼이 엑셀에 존재하지 않습니다.")
        save_error_log(error_folder, "2nd_preprocess", ["'Title' 컬럼 없음"])
        return

    # Title 정제
    df['Title'] = df['Title'].apply(clean_title_logic)
    print("Title 컬럼 정제가 완료되었습니다.")

    try:
        # final에는 No 컬럼 제외하고 저장
        df[["Title", "Item", "Guide", "Reason"]].to_excel(output_path, index=False, engine='openpyxl')
        print(f"최종 전처리 완료. 저장 위치: {output_path}")
    except Exception as e:
        print(f"파일 저장 중 오류 발생: {e}")
        save_error_log(error_folder, "2nd_preprocess", [f"저장 실패: {e}"])


# --- [메인 로직] ---

def convert_all_excel_to_csv(data_root):
    raw_data_folder   = os.path.join(data_root, 'raw_data')
    csv_output_folder = os.path.join(data_root, 'converted_csv')
    error_folder      = os.path.join(data_root, 'error')

    os.makedirs(csv_output_folder, exist_ok=True)
    os.makedirs(error_folder, exist_ok=True)

    # Excel 애플리케이션 초기화 (최대 3회 재시도)
    excel = None
    for attempt in range(1, 4):
        try:
            excel = win32.gencache.EnsureDispatch('Excel.Application')
            excel.Visible = False
            excel.DisplayAlerts = False
            break
        except Exception as e:
            print(f"Excel 초기화 시도 {attempt}/3 실패: {e}")
            if attempt == 3:
                raise Exception(f"Excel 초기화 최종 실패: {e}")
            time.sleep(2)

    # raw_data 하위 폴더 포함 모든 xlsx 파일 수집
    all_excel_files = []
    for root, dirs, files in os.walk(raw_data_folder):
        for file in files:
            if file.endswith('.xlsx') and not file.startswith('~$'):
                all_excel_files.append(os.path.join(root, file))

    print(f"총 {len(all_excel_files)}개의 엑셀 파일을 발견했습니다.")

    success_count = 0
    skip_count    = 0
    failed_files  = []

    for file_path in all_excel_files:
        file_name  = os.path.basename(file_path)
        clean_name = file_name.replace('[', '').replace(']', '')
        csv_name   = clean_name.replace('.xlsx', '.csv')
        csv_path   = os.path.normpath(os.path.join(csv_output_folder, csv_name))

        # Windows 경로 길이 제한 초과 시 스킵
        if len(csv_path) > MAX_CSV_PATH_LENGTH:
            print(f"경로 길이 초과로 스킵: {file_name}")
            skip_count += 1
            failed_files.append(f"[경로초과] {file_name}")
            continue

        # 이미 변환된 파일은 건너뜀
        if os.path.exists(csv_path):
            success_count += 1
            continue

        has_brackets = '[' in file_name or ']' in file_name
        file_opened  = False

        if has_brackets:
            # 괄호 있는 파일 → converted_csv에 괄호 제거한 이름으로 복사 후 처리
            copied_xlsx_path = os.path.normpath(os.path.join(csv_output_folder, clean_name))
            try:
                shutil.copy2(file_path, copied_xlsx_path)
                for _ in range(3):
                    try:
                        wb = excel.Workbooks.Open(copied_xlsx_path)
                        file_opened = True
                        break
                    except Exception:
                        time.sleep(1)
                if file_opened:
                    wb.SaveAs(csv_path, FileFormat=6)
                    wb.Close()
                    success_count += 1
                    print(f"변환 완료 (괄호 처리): {file_name}")
                else:
                    print(f"파일 열기 실패 (괄호 처리): {file_name}")
                    failed_files.append(f"[열기실패] {file_name}")
            except Exception as e:
                print(f"처리 중 오류 ({file_name}): {e}")
                failed_files.append(f"[오류] {file_name} - {e}")
            finally:
                # 복사해둔 xlsx 정리
                if os.path.exists(copied_xlsx_path):
                    os.remove(copied_xlsx_path)
        else:
            for _ in range(3):
                try:
                    wb = excel.Workbooks.Open(file_path)
                    file_opened = True
                    break
                except Exception:
                    time.sleep(1)
            if file_opened:
                try:
                    wb.SaveAs(csv_path, FileFormat=6)
                    wb.Close()
                    success_count += 1
                    print(f"변환 완료: {file_name}")
                except Exception as e:
                    print(f"CSV 저장 실패 ({file_name}): {e}")
                    failed_files.append(f"[저장실패] {file_name} - {e}")
            else:
                print(f"파일 열기 실패: {file_name}")
                failed_files.append(f"[열기실패] {file_name}")

    try:
        excel.Quit()
    except Exception:
        pass

    save_error_log(error_folder, "excel_to_csv", failed_files)
    print(f"\nExcel → CSV 변환 완료: 성공 {success_count}개 / 실패 {len(failed_files)}개 / 스킵 {skip_count}개")
    return csv_output_folder


def process_and_save_checklists(data_root, csv_folder):
    csv_files      = [f for f in os.listdir(csv_folder) if f.endswith('.csv')]
    error_folder   = os.path.join(data_root, 'error')
    all_extracted_data = []
    failed_files   = []

    for csv_file in csv_files:
        file_path = os.path.join(csv_folder, csv_file)
        try:
            df_raw = None
            try:
                df_raw = pd.read_csv(file_path, header=None, encoding='cp949')
            except UnicodeDecodeError:
                df_raw = pd.read_csv(file_path, header=None, encoding='utf-8-sig')

            if df_raw is None or df_raw.empty:
                continue

            # 헤더 행 탐색: NO, ITEM, GUIDE 컬럼이 모두 있는 행
            header_idx      = None
            no_col          = None
            item_start_col  = None
            guide_start_col = None
            guide_end_col   = None

            for i, row in df_raw.iterrows():
                row_vals = [str(v).strip().upper() for v in row.values]
                if 'NO' in row_vals and 'ITEM' in row_vals and 'GUIDE' in row_vals:
                    header_idx = i
                    for j, val in enumerate(row_vals):
                        if val == 'NO' and no_col is None:
                            no_col = j
                        if val == 'ITEM' and item_start_col is None:
                            item_start_col = j
                        if val == 'GUIDE' and guide_start_col is None:
                            guide_start_col = j
                        if guide_start_col is not None and 'FIGURE' in val:
                            guide_end_col = j
                            break
                    if guide_end_col is None:
                        guide_end_col = len(row_vals)
                    break

            if header_idx is None:
                print(f"헤더를 찾을 수 없어 스킵: {csv_file}")
                failed_files.append(f"[헤더없음] {csv_file}")
                continue

            # 헤더 이후 데이터 추출 및 인덱스 초기화
            df_data = df_raw.iloc[header_idx + 1:].reset_index(drop=True).copy()

            # ITEM 컬럼 범위, NO 컬럼 빈 셀 forward fill
            for col_idx in range(item_start_col, guide_start_col):
                df_data[col_idx] = df_data[col_idx].replace('', pd.NA).ffill()
            df_data[no_col] = df_data[no_col].replace('', pd.NA).ffill()

            for _, row in df_data.iterrows():
                no_val = str(row[no_col]).strip().upper()

                # NO 컬럼이 단일 알파벳(A~Z)인 행만 유효 데이터로 처리
                if not re.match(r'^[A-Z]$', no_val):
                    continue

                item_list = [
                    str(row[k]).strip()
                    for k in range(item_start_col, guide_start_col)
                    if str(row[k]).strip().lower() not in ('nan', '')
                ]
                full_item_text = ", ".join(item_list)

                guide_list = [
                    str(row[g]).strip()
                    for g in range(guide_start_col, guide_end_col)
                    if str(row[g]).strip().lower() not in ('nan', '')
                ]
                full_guide = ", ".join(guide_list)

                if full_guide:
                    all_extracted_data.append({
                        "No":     no_val,
                        "Title":  csv_file.replace('.csv', ''),
                        "Item":   full_item_text,
                        "Guide":  full_guide,
                        "Reason": ""
                    })

        except Exception as e:
            print(f"파일 처리 중 오류 ({csv_file}): {e}")
            failed_files.append(f"[오류] {csv_file} - {e}")
            continue

    save_error_log(error_folder, "extract_checklists", failed_files)

    semi_file_name = "preprocessed_data_semi.xlsx"
    if not all_extracted_data:
        print("추출된 데이터가 없습니다.")
        return None

    result_df     = pd.DataFrame(all_extracted_data)
    result_folder = os.path.join(data_root, 'result')
    os.makedirs(result_folder, exist_ok=True)

    output_path = os.path.join(result_folder, semi_file_name)
    # semi: No 컬럼 포함하여 저장
    result_df[["No", "Title", "Item", "Guide", "Reason"]].to_excel(output_path, index=False, engine='openpyxl')
    print(f"1차 중간 데이터 저장 완료: {output_path} (총 {len(result_df)}행)")
    return semi_file_name


if __name__ == "__main__":
    # 경로 구조:
    # MEG_ChatBot/
    # ├── data/
    # │   ├── raw_data/       ← 원본 Excel
    # │   ├── converted_csv/  ← CSV 변환 결과
    # │   ├── result/         ← 전처리 결과 xlsx
    # │   └── error/          ← 단계별 에러 로그
    # └── src/
    #     └── preprocess_meg.py  ← 현재 파일
    current_dir  = os.path.dirname(os.path.abspath(__file__))  # MEG_ChatBot/src/
    project_root = os.path.dirname(current_dir)                 # MEG_ChatBot/
    data_root    = os.path.join(project_root, 'data')           # MEG_ChatBot/data/

    print(f"프로젝트 루트: {project_root}")
    print(f"데이터 폴더:   {data_root}")

    # 1단계: Excel → CSV 변환
    target_csv_folder = convert_all_excel_to_csv(data_root)

    # 2단계: CSV 데이터 추출 및 1차 저장 (semi) — 컬럼: No, Title, Item, Guide, Reason
    semi_file = process_and_save_checklists(data_root, target_csv_folder)

    # 3단계: Title 정제 및 최종 저장 (final) — 컬럼: Title(정제됨), Item, Guide, Reason
    if semi_file:
        run_2nd_preprocessing(data_root, semi_file)
