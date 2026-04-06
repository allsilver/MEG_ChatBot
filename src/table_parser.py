import os
import pandas as pd
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from tqdm import tqdm

def transform_table_to_markdown():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    input_path = os.path.join(current_dir, 'preprocess', 'result', 'preprocessed_result.xlsx')
    output_folder = os.path.join(current_dir, 'preprocess', 'result')

    if not os.path.exists(input_path):
        print(f"원본 파일을 찾을 수 없습니다: {input_path}")
        return

    df = pd.read_excel(input_path)
    total_rows = len(df)
    print(f"총 {total_rows}개의 데이터를 마크다운 구조화 및 앵커링 처리 중입니다. (500행 단위 분할 저장)")

    llm = OllamaLLM(model="gemma2", temperature=0.0)

    # Reason 항목을 제외하고 프롬프트 재구성
    template = """
    너는 기구 설계 가이드라인 전문 작가야. 아래 데이터를 이용하여 RAG 검색에 최적화된 마크다운(Markdown) 형식의 전문 문장으로 서술하라.
    
    [입력 데이터]
    - 분류(Title): {title}
    - 상세항목(Item): {item}
    - 설계 가이드라인(Guide): {guide}
   
    [필수 작성 규칙]
    1. 최상단 메타데이터 앵커링: 반드시 첫 줄은 '# [품목: {item}] [주제: {title}]' 형식으로 작성하여 검색 이정표를 만들어라.
    2. 마크다운 구조화: 구분선(---)을 사용하고, '## 설계 표준 가이드'라는 소제목을 반드시 포함하라.
    3. 기술 용어 정제: 
       - 기호(→, ↑, ↓ 등)는 문맥에 맞게 '변경', '이상', '이하' 등의 단어로 풀어서 써라.
       - 수치 뒤에 단위가 없다면 설계 맥락상 적절한 'mm' 단위를 붙여라.
       - 전문 용어는 유지하되, 검색 확장을 위해 유의어나 약어를 '()' 또는 '/'로 병기하라.
    4. 강조: 핵심 수치나 중요한 설계 조건은 '** **'를 사용하여 볼드 처리하라.
    5. 무결성: 제공된 데이터의 사실만 기술하고, 절대 새로운 정보를 지어내지 마라. 미사여구는 배제하고 정보 중심으로 작성하라.

    [출력 양식]
    # [품목: {item}] [주제: {title}]
    ---
    ## 설계 표준 가이드
    (서술형 내용...)
    """
    
    prompt = ChatPromptTemplate.from_template(template)
    chain = prompt | llm

    chunk_size = 500
    current_chunk_texts = []
    chunk_count = 1
    
    for index, row in tqdm(df.iterrows(), total=total_rows, desc="마크다운 서술형 변환 진행 중"):
        raw_title = str(row['Title']).strip()
        raw_item = str(row['Item']).strip()
        raw_guide = str(row['Guide']).strip()
        
        # 나중에 Reason 행이 채워지면 아래 변수에 row['Reason']을 할당하고 프롬프트에 추가할 것
        # raw_reason = str(row['Reason']).strip() if pd.notna(row['Reason']) else ""
        
        try:
            response = chain.invoke({
                "title": raw_title,
                "item": raw_item,
                "guide": raw_guide
            })
            current_chunk_texts.append(response.strip())
        except Exception as e:
            fallback = f"# [품목: {raw_item}] [주제: {raw_title}]\n---\n## 설계 표준 가이드\n{raw_guide}"
            current_chunk_texts.append(fallback)

    # 500개 단위 분할 저장 (파일명: final_text_data_*)
        if (index + 1) % chunk_size == 0 or (index + 1) == total_rows:
            output_filename = f'final_text_data_{chunk_count}.xlsx'
            output_path = os.path.join(output_folder, output_filename)
            
            result_df = pd.DataFrame({"Text": current_chunk_texts})
            result_df.to_excel(output_path, index=False, engine='openpyxl')
            
            print(f"\n[저장 완료] {output_path} (누적 {index + 1}행 처리됨)")
            
            current_chunk_texts = []
            chunk_count += 1

    print("모든 데이터가 Reason을 제외한 마크다운 텍스트로 정제되었습니다.")

if __name__ == "__main__":
    transform_table_to_markdown()