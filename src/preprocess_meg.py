import os
import win32com.client as win32
import pandas as pd
import re
import time
import shutil

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
    df = pd.read_excel(input_path)
    print(f"\n2차 전처리를 위해 데이터를 로드했습니다. (총 {len(df)}행)")

    # 2. Title 컬럼 전처리 수행
    if 'Title' in df.columns:
        df['Title'] = df['Title'].apply(clean_title_logic)
        print("Title 컬럼 정제가 완료되었습니다.")
    else:
        print("'Title' 컬럼이 엑셀에 존재하지 않습니다.")
        return

    # 3. 결과 저장
    try:
        df.to_excel(output_path, index=False)
        print(f"최종 전처리가 완료되었습니다.")
        print(f"최종 결과물 저장 위치: {output_path}")
    except Exception as e:
        print(f"파일 저장 중 오류 발생: {e}")

# --- [메인 로직] ---
def convert_all_excel_to_csv(base_preprocess_folder):
    data_input_root = os.path.join(base_preprocess_folder, 'data')
    csv_output_folder = os.path.join(base_preprocess_folder, 'converted_csv')
    temp_error_folder = os.path.join(base_preprocess_folder, 'error')

    if not os.path.exists(csv_output_folder): os.makedirs(csv_output_folder)
    if not os.path.exists(temp_error_folder): os.makedirs(temp_error_folder)

    excel = None
    retry_count = 0
    max_retries = 3

    while retry_count < max_retries:
        try:
            excel = win32.gencache.EnsureDispatch('Excel.Application')
            excel.Visible = False
            excel.DisplayAlerts = False
            break
        except Exception as e:
            retry_count += 1
            if retry_count >= max_retries: raise Exception(f"Excel 초기화 실패: {e}")
            time.sleep(2)

    all_excel_files = []
    for root, dirs, files in os.walk(data_input_root):
        for file in files:
            if file.endswith('.xlsx') and not file.startswith('~$'):
                all_excel_files.append(os.path.join(root, file))

    print(f"총 {len(all_excel_files)}개의 엑셀 파일을 발견했습니다.")

    success_count = 0
    for file_path in all_excel_files:
        file_name = os.path.basename(file_path)
        csv_name = file_name.replace('[', '').replace(']', '').replace('.xlsx', '.csv')
        csv_path = os.path.normpath(os.path.join(csv_output_folder, csv_name))

        if len(csv_path) > 218: continue
        if os.path.exists(csv_path):
            success_count += 1
            continue

        has_brackets = '[' in file_name or ']' in file_name
        wb = None
        file_opened = False

        if has_brackets:
            temp_file_name = file_name.replace('[', '').replace(']', '')
            temp_file_path = os.path.normpath(os.path.join(temp_error_folder, temp_file_name))
            try:
                shutil.copy2(file_path, temp_file_path)
                for attempt in range(3):
                    try:
                        wb = excel.Workbooks.Open(temp_file_path)
                        file_opened = True
                        break
                    except: time.sleep(1)
                if file_opened:
                    wb.SaveAs(csv_path, FileFormat=6)
                    wb.Close()
                    success_count += 1
                os.remove(temp_file_path)
            except: pass
        else:
            for attempt in range(3):
                try:
                    wb = excel.Workbooks.Open(file_path)
                    file_opened = True
                    break
                except: time.sleep(1)
            if file_opened:
                try:
                    wb.SaveAs(csv_path, FileFormat=6)
                    wb.Close()
                    success_count += 1
                except: pass

    try: excel.Quit()
    except: pass
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
            except:
                df_raw = pd.read_csv(file_path, header=None, encoding='utf-8-sig')

            if df_raw is None or df_raw.empty: continue

            header_idx, no_col = None, None
            item_start_col, guide_start_col, guide_end_col = None, None, None

            for i, row in df_raw.iterrows():
                row_vals = [str(v).strip().upper() for v in row.values]
                if 'NO' in row_vals and 'ITEM' in row_vals and 'GUIDE' in row_vals:
                    header_idx = i
                    for j, val in enumerate(row_vals):
                        if 'NO' == val: no_col = j
                        if 'ITEM' == val and item_start_col is None: item_start_col = j
                        if 'GUIDE' == val and guide_start_col is None: guide_start_col = j
                        if guide_start_col is not None and 'FIGURE' in val:
                            guide_end_col = j
                            break
                    if guide_end_col is None: guide_end_col = len(row_vals)
                    break
            
            if header_idx is None: continue

            df_data = df_raw.iloc[header_idx + 1:].copy()
            for col_idx in range(item_start_col, guide_start_col):
                df_data[col_idx] = df_data[col_idx].replace('', None).ffill()
            df_data[no_col] = df_data[no_col].replace('', None).ffill()

            for _, row in df_data.iterrows():
                no_val = str(row[no_col]).strip().upper()
                if not re.match(r'^[A-Z]$', no_val): break

                item_list = [str(row[k]).strip() for k in range(item_start_col, guide_start_col)
                             if str(row[k]).strip().lower() != 'nan' and str(row[k]).strip() != '']
                full_item_text = ", ".join(item_list)

                guide_list = [str(row[g]).strip() for g in range(guide_start_col, guide_end_col)
                              if str(row[g]).strip().lower() != 'nan' and str(row[g]).strip() != '']
                full_guide = ", ".join(guide_list)

                if full_guide:
                    all_extracted_data.append({
                        "Title": csv_file.replace('.csv', ''),
                        "Item": full_item_text,
                        "Guide": full_guide,
                        "Reason": ""
                    })
        except: continue

    semi_file_name = "preprocessed_data_semi.xlsx"
    if all_extracted_data:
        result_df = pd.DataFrame(all_extracted_data)
        final_result_folder = os.path.join(base_preprocess_folder, 'result')
        if not os.path.exists(final_result_folder): os.makedirs(final_result_folder)

        output_path = os.path.join(final_result_folder, semi_file_name)
        result_df[["Title", "Item", "Guide", "Reason"]].to_excel(output_path, index=False)
        print(f"1차 중간 데이터 저장 완료: {semi_file_name}")
        return semi_file_name
    return None

if __name__ == "__main__":
    current_dir = os.path.dirname(os.path.abspath(__file__))
    preprocess_root = os.path.join(current_dir, 'preprocess')
    
    # 1. Excel to CSV
    target_csv_folder = convert_all_excel_to_csv(preprocess_root)
    
    # 2. Data Extraction and Semi-save
    semi_file = process_and_save_checklists(preprocess_root, target_csv_folder)
    
    # 3. Final Preprocessing and Final-save
    if semi_file:
        run_2nd_preprocessing(preprocess_root, semi_file)