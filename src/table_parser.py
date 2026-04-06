import os
import sys
import pandas as pd

# ============ 모델 설정 ============
# TABLE_PARSER_MODEL = "gemma2"
# TABLE_PARSER_MODEL = "gemma4:e4b"
TABLE_PARSER_MODEL = "qwen3:14b"
# ==================================

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from tqdm import tqdm

# preprocess_meg.py를 같은 src/ 폴더에서 import
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preprocess_meg import convert_all_excel_to_csv, process_and_save_checklists, run_2nd_preprocessing


def transform_table_to_markdown():
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    data_root    = os.path.join(project_root, 'data')

    input_path    = os.path.join(data_root, 'result', 'preprocessed_data_final.xlsx')
    output_folder = os.path.join(data_root, 'result')

    if not os.path.exists(input_path):
        print(f"원본 파일을 찾을 수 없습니다: {input_path}")
        return

    df = pd.read_excel(input_path, engine='openpyxl')
    total_rows = len(df)
    print(f"총 {total_rows}개의 데이터를 마크다운 구조화 처리 중입니다. (500행 단위 분할 저장)")

    llm = OllamaLLM(model=TABLE_PARSER_MODEL, temperature=0.0)

    template = """
너는 기구 설계 가이드라인 데이터를 RAG 검색에 최적화된 형식으로 정리하는 기술 편집자야.
아래 입력 데이터의 내용을 절대 변경하거나 추가하지 말고, 주어진 정보만으로 마크다운 문서를 작성하라.

[입력 데이터]
- 분류(Title): {title}
- 상세항목(Item): {item}
- 설계 가이드라인(Guide): {guide}

[작성 규칙]
1. 첫 줄은 반드시 '# [품목: {item}] [주제: {title}]' 형식으로 작성하라.
2. '## 설계 표준 가이드' 소제목을 포함하라.
3. Guide의 내용을 빠짐없이 자연스러운 한국어 기술 문장으로 풀어서 서술하라.
   단어나 기호(→, ↑, ↓, T, φ 등)는 문맥에 맞게 '이상', '이하', '두께', '직경' 등으로 풀어써라.
4. 입력 데이터에 명시된 수치와 단위는 반드시 그대로 포함하라. 없는 수치나 단위를 임의로 추가하지 마라.
5. 입력 데이터에 없는 부품명, 조건, 규격, 사례를 절대 지어내지 마라.
6. 검색 키워드 보강을 위해 Guide에 이미 등장한 용어의 한자어/영문 표기를 괄호로 병기하는 것은 허용한다.
   단, Guide에 없는 새로운 개념이나 용어를 추가하는 것은 금지한다.

[출력 형식]
# [품목: {item}] [주제: {title}]
---
## 설계 표준 가이드
(Guide 내용을 풀어쓴 서술형 문장)
"""

    prompt = ChatPromptTemplate.from_template(template)
    chain  = prompt | llm

    chunk_size          = 500
    current_chunk_texts = []
    chunk_count         = 1

    for index, row in tqdm(df.iterrows(), total=total_rows, desc="마크다운 서술형 변환 진행 중"):
        raw_title = str(row['Title']).strip()
        raw_item  = str(row['Item']).strip()
        raw_guide = str(row['Guide']).strip()

        try:
            response = chain.invoke({
                "title": raw_title,
                "item":  raw_item,
                "guide": raw_guide
            })
            current_chunk_texts.append(response.strip())
        except Exception as e:
            print(f"\nLLM 호출 실패 (index={index}): {e} → 원본 텍스트로 폴백")
            fallback = f"# [품목: {raw_item}] [주제: {raw_title}]\n---\n## 설계 표준 가이드\n{raw_guide}"
            current_chunk_texts.append(fallback)

        # 500행 단위 또는 마지막 행에서 청크 저장
        if (index + 1) % chunk_size == 0 or (index + 1) == total_rows:
            output_filename = f'final_text_data_{chunk_count}.xlsx'
            output_path     = os.path.join(output_folder, output_filename)

            result_df = pd.DataFrame({"Text": current_chunk_texts})
            result_df.to_excel(output_path, index=False, engine='openpyxl')

            print(f"\n[저장 완료] {output_path} (누적 {index + 1}행 처리됨)")

            current_chunk_texts = []
            chunk_count += 1

    print("모든 데이터가 마크다운 텍스트로 변환 완료되었습니다.")


if __name__ == "__main__":
    import shutil
    from vector_store import prepare_knowledge_base, EMBEDDING_MODEL

    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    data_root    = os.path.join(project_root, 'data')

    semi_path  = os.path.join(data_root, 'result', 'preprocessed_data_semi.xlsx')
    final_path = os.path.join(data_root, 'result', 'preprocessed_data_final.xlsx')

    # =============================================
    # 실행 전 모든 질문을 먼저 받아둠 (이후 자동 실행)
    # =============================================
    print("=" * 50)
    print("실행 전 설정을 확인합니다.")
    print("=" * 50)

    # 질문1: 전처리 여부 (semi/final 이미 있는 경우만 질문)
    run_preprocess = False
    if os.path.exists(semi_path) and os.path.exists(final_path):
        answer = input("\n[1/2] preprocessed_data 파일이 이미 존재합니다. 전처리를 다시 수행할까요? (y/n): ").strip().lower()
        run_preprocess = (answer == 'y')
    else:
        print("\n[1/2] preprocessed_data 파일 없음 → 전처리를 자동으로 수행합니다.")
        run_preprocess = True

    # 질문2: ChromaDB 재구축 여부
    db_name     = EMBEDDING_MODEL.replace(":", "_").replace("-", "_")
    persist_dir = os.path.join(data_root, 'chroma_db', db_name)
    answer = input(f"\n[2/2] ChromaDB를 새로 구축할까요? (y/n): ").strip().lower()
    rebuild_chroma = (answer == 'y')
    if not rebuild_chroma:
        print("⚠️  ChromaDB를 유지합니다. 새 데이터가 반영되지 않을 수 있습니다.")

    print("\n설정 완료. 이후 자동으로 실행됩니다. 자리를 비워도 됩니다.")
    print("=" * 50)

    # =============================================
    # [1단계] 전처리
    # =============================================
    if run_preprocess:
        print("\n=== [1단계] 전처리 시작 ===")
        csv_folder = convert_all_excel_to_csv(data_root)
        semi_file  = process_and_save_checklists(data_root, csv_folder)
        if semi_file:
            run_2nd_preprocessing(data_root, semi_file)
        else:
            print("❌ 전처리 실패. 종료합니다.")
            sys.exit(1)
    else:
        print("\n=== [1단계 스킵] 기존 전처리 파일을 사용합니다. ===")

    # =============================================
    # [2단계] LLM 마크다운 변환
    # =============================================
    print("\n=== [2단계] LLM 마크다운 변환 시작 ===")
    transform_table_to_markdown()

    # =============================================
    # [3단계] ChromaDB 구축
    # =============================================
    if rebuild_chroma:
        print("\n=== [3단계] ChromaDB 구축 시작 ===")
        if os.path.exists(persist_dir):
            shutil.rmtree(persist_dir)
            print(f"기존 ChromaDB 삭제 완료: {persist_dir}")
        data_pattern = os.path.join(data_root, 'result', 'final_text_data_*.xlsx')
        prepare_knowledge_base(data_pattern)
        print("✅ ChromaDB 구축 완료.")
    else:
        print("\n=== [3단계 스킵] ChromaDB를 유지합니다. ===")

    print("\n✅ 모든 작업 완료. 앱을 실행하세요: streamlit run src/chatbot_meg.py")
