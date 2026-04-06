import os
import glob
import pandas as pd
import requests
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


def check_ollama():
    """Ollama 서버 실행 여부 확인"""
    try:
        response = requests.get("http://localhost:11434")
        return response.status_code == 200
    except Exception:
        return False


def prepare_knowledge_base(file_pattern):
    """
    final_text_data_*.xlsx 파일을 읽어 ChromaDB 벡터 DB 구축
    @st.cache_resource는 Streamlit 의존성이므로 chatbot_meg.py에서 감싸서 적용
    """
    all_files = glob.glob(file_pattern)
    if not all_files:
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_pattern}")

    combined_df = pd.concat(
        [pd.read_excel(f, engine='openpyxl') for f in all_files],
        ignore_index=True
    )

    documents = []
    for _, row in combined_df.iterrows():
        if pd.notna(row['Text']):
            documents.append(Document(page_content=str(row['Text']).strip()))

    print(f"총 {len(documents)}개의 문서를 로드했습니다.")

    embeddings = OllamaEmbeddings(model="gemma2")
    vector_db  = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        collection_name="design_bot_final_v8"
    )
    return vector_db


def expand_query(query, llm):
    """방향어(상/하/좌/우) 등 유의어를 추가하여 검색 범위 확장"""
    expansion_template = """
    너는 기구 설계 전문가야. 사용자의 질문을 분석하여 검색에 도움이 될 단어들을 추가해줘.
    특히 방향(상/하/좌/우/전/후), 단위, 부품 명칭의 유의어를 포함하라.
    결과는 콤마(,)로 구분된 단어들만 출력해.

    사용자 질문: {query}
    결과:"""
    prompt = ChatPromptTemplate.from_template(expansion_template)
    chain  = prompt | llm | StrOutputParser()
    try:
        expanded_terms = chain.invoke({"query": query})
        return f"{query}, {expanded_terms}"
    except Exception:
        return query


def setup_design_bot(vector_db):
    """RAG 챗봇 핸들러 함수 반환"""
    llm = OllamaLLM(model="gemma2", temperature=0.1)

    template = """너는 숙련된 기구 설계 시니어 엔지니어로서 후배에게 설계 표준을 설명해주는 전문가야.
제공된 [참조 데이터]를 바탕으로 질문에 답변하되, 아래 규칙을 반드시 지켜라.

[작성 규칙]
1. 검색된 데이터가 질문과 매우 밀접하다면 "확인된 설계 표준 가이드는 다음과 같습니다."라고 시작하며 설명하라.
2. 질문과 정확히 일치하지는 않지만 관련이 있는 데이터를 찾았다면 "정확한 표준은 확인되지 않지만, 가장 유사한 사례를 기반으로 안내해 드립니다."라고 말하라.
3. 데이터에 언급된 수치나 조건(mm, T 등)은 절대로 빠뜨리지 말고 상세히 풀어서 설명하라.
4. 마크다운 기호(##, --- 등)를 노출하지 말고, 구어체 문장으로 자연스럽게 설명하라.
5. (나중에 Reason 데이터가 보강되면 설계 근거를 포함하여 보완할 것)
6. 정말로 관련이 없는 데이터만 있다면 질문을 다시 해달라고 정중히 요청하라.

[참조 데이터]
{context}

사용자 질문: {question}

전문가 답변:"""

    prompt = ChatPromptTemplate.from_template(template)

    def rag_handler(query):
        # 1. 쿼리 확장
        expanded_q = expand_query(query, llm)

        # 2. 유사도 점수 포함 문서 검색 (k=10으로 넓게 탐색)
        docs_with_scores = vector_db.similarity_search_with_relevance_scores(expanded_q, k=10)

        # 3. 임계치(0.2) 이상인 문서만 사용
        valid_docs = [doc for doc, score in docs_with_scores if score > 0.2]

        # 점수 미달이어도 상위 1개는 강제 포함하여 유사 답변 유도
        if not valid_docs and docs_with_scores:
            valid_docs = [docs_with_scores[0][0]]

        context_text = "\n\n".join(doc.page_content for doc in valid_docs)

        chain    = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context_text, "question": query})
        return response

    return rag_handler


# --- 터미널 테스트 모드 ---
if __name__ == "__main__":
    current_dir  = os.path.dirname(os.path.abspath(__file__))  # MEG_ChatBot/src/
    project_root = os.path.dirname(current_dir)                 # MEG_ChatBot/
    data_pattern = os.path.join(project_root, 'data', 'result', 'final_text_data_*.xlsx')

    print("Ollama 연결 확인 중...")
    if not check_ollama():
        print("❌ Ollama 서버가 실행되고 있지 않습니다. 'ollama serve'를 먼저 실행해주세요.")
        exit(1)
    print("✅ Ollama 연결 확인")

    print(f"\n지식 베이스 구축 중...")
    try:
        vector_db = prepare_knowledge_base(data_pattern)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        exit(1)

    bot = setup_design_bot(vector_db)
    print("✅ 준비 완료. 질문을 입력하세요. (종료: q)\n")

    while True:
        query = input("질문 > ").strip()
        if query.lower() == 'q':
            print("종료합니다.")
            break
        if not query:
            continue
        print("─" * 50)
        print(bot(query))
        print("─" * 50 + "\n")
