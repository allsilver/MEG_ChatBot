import os
import win32com.client as win32
import pandas as pd
import re
import time
import shutil
from datetime import datetime

MAX_CSV_PATH_LENGTH = 218


def clean_title_logic(text):
    if pd.isna(text):
        return ""
    text = str(text).strip()
    text = re.sub(r'^[0-9\s.\-_]+', '', text)

    PROTECT_KEYWORDS = ['2.5D', '3D', '2D']
    placeholders = {}
    for i, kw in enumerate(PROTECT_KEYWORDS):
        placeholder = f'__PROTECTED_{i}__'
        if kw in text:
            placeholders[placeholder] = kw
            text = text.replace(kw, placeholder)

    text = text.replace('(', ' ').replace(')', ' ').replace('_', ' ').replace('-', ' ')

    for placeholder, kw in placeholders.items():
        text = text.replace(placeholder, kw)

    text = re.sub(r'\s+', ' ', text).strip()
    return text


def save_error_log(error_folder, step_name, failed_files):
    if not failed_files:
        return
    os.makedirs(error_folder, exist_ok=True)
    timestamp    = datetime.now().strftime("%Y%m%d_%H%M%S")
    error_path   = os.path.join(error_folder, f"error_log_{step_name}_{timestamp}.txt")
    with open(error_path, 'w', encoding='utf-8') as f:
        f.write(f"[{step_name}] 에러 발생 파일 목록 - {timestamp}\n")
        f.write("=" * 50 + "\n")
        f.write("\n".join(failed_files))
    print(f"에러 로그 저장: {error_path}")


def run_2nd_preprocessing(domain_data_root, db_key, input_file_name):
    """
    1차 저장된 semi 파일을 불러와 Title을 정제하고 final 결과물로 저장.
    domain_data_root: data/<DOMAIN_KEY>/
    """
    result_folder = os.path.join(domain_data_root, 'result', db_key)
    input_path    = os.path.join(result_folder, input_file_name)
    output_path   = os.path.join(result_folder, 'preprocessed_data_final.xlsx')
    error_folder  = os.path.join(domain_data_root, 'error')

    if not os.path.exists(input_path):
        print(f"원본 파일을 찾을 수 없습니다: {input_path}")
        return

    df = pd.read_excel(input_path, engine='openpyxl')
    print(f"\n2차 전처리 데이터 로드 완료. (총 {len(df)}행)")

    if 'Title' not in df.columns:
        print("'Title' 컬럼이 존재하지 않습니다.")
        save_error_log(error_folder, "2nd_preprocess", ["'Title' 컬럼 없음"])
        return

    df['Title'] = df['Title'].apply(clean_title_logic)
    print("Title 컬럼 정제 완료.")

    try:
        df[["Title", "Item", "Guide", "Reason"]].to_excel(output_path, index=False, engine='openpyxl')
        print(f"최종 전처리 완료: {output_path}")
    except Exception as e:
        print(f"파일 저장 오류: {e}")
        save_error_log(error_folder, "2nd_preprocess", [f"저장 실패: {e}"])


def convert_all_excel_to_csv(domain_data_root, db_key):
    """
    domain_data_root/<raw_data>/<db_key>/ 의 Excel 파일을 CSV 로 변환.
    domain_data_root: data/<DOMAIN_KEY>/
    """
    raw_data_folder   = os.path.join(domain_data_root, 'raw_data', db_key)
    csv_output_folder = os.path.join(domain_data_root, 'converted_csv', db_key)
    error_folder      = os.path.join(domain_data_root, 'error')

    os.makedirs(csv_output_folder, exist_ok=True)
    os.makedirs(error_folder, exist_ok=True)

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

    all_excel_files = []
    EXCLUDE_KEYWORDS = ['OLD', 'old', '삭제']

    for root, dirs, files in os.walk(raw_data_folder):
        for file in files:
            if file.endswith('.xlsx') and not file.startswith('~$'):
                if any(keyword in file for keyword in EXCLUDE_KEYWORDS):
                    print(f"제외 (키워드 필터): {file}")
                    continue
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

        if len(csv_path) > MAX_CSV_PATH_LENGTH:
            print(f"경로 길이 초과로 스킵: {file_name}")
            skip_count += 1
            failed_files.append(f"[경로초과] {file_name}")
            continue

        if os.path.exists(csv_path):
            success_count += 1
            continue

        has_brackets = '[' in file_name or ']' in file_name
        file_opened  = False

        if has_brackets:
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
                    failed_files.append(f"[열기실패] {file_name}")
            except Exception as e:
                failed_files.append(f"[오류] {file_name} - {e}")
            finally:
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
                    failed_files.append(f"[저장실패] {file_name} - {e}")
            else:
                failed_files.append(f"[열기실패] {file_name}")

    try:
        excel.Quit()
    except Exception:
        pass

    save_error_log(error_folder, "excel_to_csv", failed_files)
    print(f"\nExcel → CSV 변환 완료: 성공 {success_count}개 / 실패 {len(failed_files)}개 / 스킵 {skip_count}개")
    return csv_output_folder


def process_and_save_checklists(domain_data_root, db_key, csv_folder):
    """
    CSV 에서 체크리스트 항목을 추출해 semi xlsx 로 저장.
    domain_data_root: data/<DOMAIN_KEY>/
    """
    csv_files          = [f for f in os.listdir(csv_folder) if f.endswith('.csv')]
    error_folder       = os.path.join(domain_data_root, 'error')
    all_extracted_data = []
    failed_files       = []

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
                        if val == 'NO'   and no_col          is None: no_col          = j
                        if val == 'ITEM' and item_start_col  is None: item_start_col  = j
                        if val == 'GUIDE'and guide_start_col is None: guide_start_col = j
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

            df_data = df_raw.iloc[header_idx + 1:].reset_index(drop=True).copy()

            for col_idx in range(item_start_col, guide_start_col):
                df_data[col_idx] = df_data[col_idx].replace('', pd.NA).ffill()
            df_data[no_col] = df_data[no_col].replace('', pd.NA).ffill()

            for _, row in df_data.iterrows():
                no_val = str(row[no_col]).strip().upper()
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
    result_folder = os.path.join(domain_data_root, 'result', db_key)
    os.makedirs(result_folder, exist_ok=True)

    output_path = os.path.join(result_folder, semi_file_name)
    result_df[["No", "Title", "Item", "Guide", "Reason"]].to_excel(output_path, index=False, engine='openpyxl')
    print(f"1차 중간 데이터 저장 완료: {output_path} (총 {len(result_df)}행)")
    return semi_file_name
