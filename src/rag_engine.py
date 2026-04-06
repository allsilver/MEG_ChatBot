import requests
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# ============ 생성 모델 설정 (여기만 변경) ============
GENERATOR_MODEL = "qwen3:8b"
# GENERATOR_MODEL = "gemma2"
# GENERATOR_MODEL = "gemma4:e4b"
# GENERATOR_MODEL = "qwen3:14b"
# =====================================================


def check_ollama():
    """Ollama 서버 실행 여부 확인"""
    try:
        response = requests.get("http://localhost:11434")
        return response.status_code == 200
    except Exception:
        return False


def setup_design_bot(vector_db):
    """RAG 챗봇 핸들러 함수 반환"""
    llm = OllamaLLM(model=GENERATOR_MODEL, temperature=0.1)

    template = """/no_think
너는 숙련된 기구 설계 시니어 엔지니어로서 후배에게 설계 표준을 설명해주는 전문가야.
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
        # 유사도 점수 포함 문서 검색 (k=10으로 넓게 탐색)
        docs_with_scores = vector_db.similarity_search_with_relevance_scores(query, k=10)

        # 임계치(0.2) 이상인 문서만 사용
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
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from vector_store import load_vector_db

    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    print("Ollama 연결 확인 중...")
    if not check_ollama():
        print("❌ Ollama 서버가 실행되고 있지 않습니다. 'ollama serve'를 먼저 실행해주세요.")
        exit(1)
    print("✅ Ollama 연결 확인")

    print("\n지식 베이스 로드 중...")
    try:
        vector_db = load_vector_db()
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
