import os
import win32com.client as win32
import pandas as pd
import re
import time
import shutil

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


def run_2nd_preprocessing(base_preprocess_folder, input_file_name):
    """
    1차 저장된 semi 파일을 불러와 Title을 정제하고 final 결과물로 저장
    """
    input_path = os.path.join(base_preprocess_folder, 'result', input_file_name)
    output_path = os.path.join(base_preprocess_folder, 'result', 'preprocessed_data_final.xlsx')

    if not os.path.exists(input_path):
        print(f"원본 파일을 찾을 수 없습니다: {input_path}")
        return

    # 1. 데이터 로드
    df = pd.read_excel(input_path, engine='openpyxl')
    print(f"\n2차 전처리를 위해 데이터를 로드했습니다. (총 {len(df)}행)")

    # 2. Title 컬럼 전처리 수행
    if 'Title' not in df.columns:
        print("'Title' 컬럼이 엑셀에 존재하지 않습니다.")
        return

    df['Title'] = df['Title'].apply(clean_title_logic)
    print("Title 컬럼 정제가 완료되었습니다.")

    # 3. 결과 저장
    try:
        df.to_excel(output_path, index=False, engine='openpyxl')
        print(f"최종 전처리가 완료되었습니다.")
        print(f"최종 결과물 저장 위치: {output_path}")
    except Exception as e:
        print(f"파일 저장 중 오류 발생: {e}")


# --- [메인 로직] ---

def convert_all_excel_to_csv(base_preprocess_folder):
    data_input_root = os.path.join(base_preprocess_folder, 'data')
    csv_output_folder = os.path.join(base_preprocess_folder, 'converted_csv')
    temp_error_folder = os.path.join(base_preprocess_folder, 'error')

    os.makedirs(csv_output_folder, exist_ok=True)
    os.makedirs(temp_error_folder, exist_ok=True)

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

    # 하위 폴더 포함 모든 xlsx 파일 수집
    all_excel_files = []
    for root, dirs, files in os.walk(data_input_root):
        for file in files:
            if file.endswith('.xlsx') and not file.startswith('~$'):
                all_excel_files.append(os.path.join(root, file))

    print(f"총 {len(all_excel_files)}개의 엑셀 파일을 발견했습니다.")

    success_count = 0
    skip_count = 0

    for file_path in all_excel_files:
        file_name = os.path.basename(file_path)
        csv_name = file_name.replace('[', '').replace(']', '').replace('.xlsx', '.csv')
        csv_path = os.path.normpath(os.path.join(csv_output_folder, csv_name))

        # Windows 경로 길이 제한 초과 시 스킵
        if len(csv_path) > MAX_CSV_PATH_LENGTH:
            print(f"경로 길이 초과로 스킵: {file_name}")
            skip_count += 1
            continue

        if os.path.exists(csv_path):
            success_count += 1
            continue

        has_brackets = '[' in file_name or ']' in file_name
        file_opened = False

        if has_brackets:
            # 파일명에 괄호가 있으면 임시 폴더에 복사 후 처리
            temp_file_name = file_name.replace('[', '').replace(']', '')
            temp_file_path = os.path.normpath(os.path.join(temp_error_folder, temp_file_name))
            try:
                shutil.copy2(file_path, temp_file_path)
                for _ in range(3):
                    try:
                        wb = excel.Workbooks.Open(temp_file_path)
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
            except Exception as e:
                print(f"처리 중 오류 ({file_name}): {e}")
            finally:
                if os.path.exists(temp_file_path):
                    os.remove(temp_file_path)
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
            else:
                print(f"파일 열기 실패: {file_name}")

    try:
        excel.Quit()
    except Exception:
        pass

    print(f"\nExcel → CSV 변환 완료: 성공 {success_count}개 / 스킵 {skip_count}개")
    return csv_output_folder


def process_and_save_checklists(base_preprocess_folder, csv_folder):
    csv_files = [f for f in os.listdir(csv_folder) if f.endswith('.csv')]
    all_extracted_data = []

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
            header_idx = None
            no_col = None
            item_start_col = None
            guide_start_col = None
            guide_end_col = None

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
                continue

            # 헤더 이후 데이터 추출 및 인덱스 초기화
            df_data = df_raw.iloc[header_idx + 1:].reset_index(drop=True).copy()

            # ITEM 컬럼 병합 범위, NO 컬럼 빈 셀 forward fill
            for col_idx in range(item_start_col, guide_start_col):
                df_data[col_idx] = df_data[col_idx].replace('', pd.NA).ffill()
            df_data[no_col] = df_data[no_col].replace('', pd.NA).ffill()

            for _, row in df_data.iterrows():
                no_val = str(row[no_col]).strip().upper()

                # NO 컬럼이 단일 알파벳(A~Z)인 행만 유효 데이터로 처리
                # NaN이나 기타 값은 스킵 (break 대신 continue로 중간 빈 행 허용)
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
                        "Title": csv_file.replace('.csv', ''),
                        "Item": full_item_text,
                        "Guide": full_guide,
                        "Reason": ""
                    })

        except Exception as e:
            print(f"파일 처리 중 오류 ({csv_file}): {e}")
            continue

    semi_file_name = "preprocessed_data_semi.xlsx"
    if not all_extracted_data:
        print("추출된 데이터가 없습니다.")
        return None

    result_df = pd.DataFrame(all_extracted_data)
    result_folder = os.path.join(base_preprocess_folder, 'result')
    os.makedirs(result_folder, exist_ok=True)

    output_path = os.path.join(result_folder, semi_file_name)
    result_df[["Title", "Item", "Guide", "Reason"]].to_excel(output_path, index=False, engine='openpyxl')
    print(f"1차 중간 데이터 저장 완료: {output_path} (총 {len(result_df)}행)")
    return semi_file_name


if __name__ == "__main__":
    # preprocess_meg.py 위치: src/preprocess_meg.py
    # preprocess 폴더 위치: src/preprocess/
    current_dir = os.path.dirname(os.path.abspath(__file__))
    preprocess_root = os.path.join(current_dir, 'preprocess')

    print(f"전처리 작업 폴더: {preprocess_root}")

    # 1단계: Excel → CSV 변환
    target_csv_folder = convert_all_excel_to_csv(preprocess_root)

    # 2단계: CSV 데이터 추출 및 1차 저장 (semi)
    semi_file = process_and_save_checklists(preprocess_root, target_csv_folder)

    # 3단계: Title 정제 및 최종 저장 (final)
    if semi_file:
        run_2nd_preprocessing(preprocess_root, semi_file)
