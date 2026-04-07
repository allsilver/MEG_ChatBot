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

# 대화 중 문맥으로 포함할 최근 턴 수 (1턴 = 질문 1개 + 답변 1개)
CHAT_HISTORY_TURNS = 3


def check_ollama():
    try:
        response = requests.get("http://localhost:11434")
        return response.status_code == 200
    except Exception:
        return False


def _search_docs(vector_dbs: dict, query: str):
    """모든 DB에서 검색 후 중복 제거한 문서 리스트 반환"""
    all_docs = []
    for vdb in vector_dbs.values():
        results = vdb.similarity_search_with_relevance_scores(query, k=10)
        valid   = [doc for doc, score in results if score > 0.2]
        if not valid and results:
            valid = [results[0][0]]
        all_docs.extend(valid)

    seen, deduped = set(), []
    for doc in all_docs:
        if doc.page_content not in seen:
            seen.add(doc.page_content)
            deduped.append(doc)
    return deduped


def _format_history(chat_history: list[dict]) -> str:
    """
    chat_history: [{"role": "user"/"assistant", "content": "..."}] 형태
    최근 CHAT_HISTORY_TURNS 턴만 포함해서 문자열로 변환
    """
    if not chat_history:
        return ""
    # 최근 N턴 = 최근 N*2개 메시지
    recent = chat_history[-(CHAT_HISTORY_TURNS * 2):]
    lines  = []
    for m in recent:
        role = "사용자" if m["role"] == "user" else "어시스턴트"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)


def setup_design_bot(vector_dbs, use_think: bool = False):
    """
    RAG 챗봇 핸들러 반환.

    vector_dbs: dict[str, Chroma] — {db_key: vector_db}
                단일 Chroma 객체도 하위 호환으로 수용 (dict로 래핑)
    use_think : Thinking 모드 여부
    """
    if not isinstance(vector_dbs, dict):
        vector_dbs = {"default": vector_dbs}

    llm = OllamaLLM(model=GENERATOR_MODEL, temperature=0.1)

    no_think_prefix = "" if use_think else "/no_think\n"
    template = no_think_prefix + \
"""너는 기구 설계 표준 검색 어시스턴트야. NX 작업 중인 설계자를 위해 빠르고 정확한 답변을 제공한다.

[케이스별 답변 형식]

케이스 1 — 표준이 명확히 검색된 경우:
항목과 수치를 아래 형식으로 나열하라.
  · [항목명] 수치/조건
  · [항목명] 수치/조건
필요한 경우 한 문장 이내로 주의사항을 추가한다.

케이스 2 — 질문이 애매하거나 범위가 넓은 경우:
"다음 항목들과 관련이 있습니다:"로 시작하여 관련 항목명을 나열하고,
"어떤 항목을 확인하시겠어요?"로 마무리하라.

케이스 3 — 정확한 표준은 없지만 유사 항목이 있는 경우:
"해당 항목의 표준은 확인되지 않습니다."라고 먼저 말하고,
"가장 유사한 항목: [항목명] — 수치/조건"으로 이어라.

케이스 4 — 완전히 관련 없는 경우:
"관련 표준을 찾지 못했습니다. 질문을 다시 입력해주세요."

[공통 규칙]
- 수치와 단위(mm, T, °C 등)는 절대 생략하지 않는다.
- 마크다운 기호(##, ---, *, 백틱 등), 인사말, 서두 없이 바로 본문만 출력한다.
- [이전 대화]가 있으면 문맥을 파악해 답변에 활용하라. 없으면 무시하라.

[이전 대화]
{chat_history}

[참조 데이터]
{context}

질문: {question}
답변:"""

    prompt = ChatPromptTemplate.from_template(template)

    def rag_handler(query: str, chat_history: list[dict] = None) -> str:
        docs         = _search_docs(vector_dbs, query)
        context_text = "\n\n".join(doc.page_content for doc in docs)
        history_text = _format_history(chat_history or [])

        chain = prompt | llm | StrOutputParser()
        return chain.invoke({
            "context":      context_text,
            "question":     query,
            "chat_history": history_text,
        })

    def rag_handler_stream(query: str, chat_history: list[dict] = None):
        """스트리밍 출력용 제너레이터 — st.write_stream()에서 사용"""
        docs         = _search_docs(vector_dbs, query)
        context_text = "\n\n".join(doc.page_content for doc in docs)
        history_text = _format_history(chat_history or [])

        chain = prompt | llm | StrOutputParser()
        for chunk in chain.stream({
            "context":      context_text,
            "question":     query,
            "chat_history": history_text,
        }):
            yield chunk

    rag_handler.stream = rag_handler_stream
    return rag_handler


# --- 터미널 테스트 모드 ---
if __name__ == "__main__":
    import os
    import sys
    import json
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from vector_store import load_multiple_vector_dbs

    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    print("Ollama 연결 확인 중...")
    if not check_ollama():
        print("❌ Ollama 서버가 실행되고 있지 않습니다. 'ollama serve' 를 먼저 실행해주세요.")
        exit(1)
    print("✅ Ollama 연결 확인")

    registry_path = os.path.join(current_dir, 'db_registry.json')
    try:
        with open(registry_path, encoding='utf-8') as f:
            registry = json.load(f)
    except FileNotFoundError:
        print("❌ db_registry.json 을 찾을 수 없습니다.")
        exit(1)

    print("\n등록된 DB 목록:")
    for key, info in registry.items():
        print(f"  [{key}] {info['display_name']}")

    keys_input = input("\n검색할 DB 키 (쉼표 구분): ").strip()
    selected   = [k.strip() for k in keys_input.split(",") if k.strip() in registry]
    if not selected:
        print("❌ 유효한 DB 키가 없습니다.")
        exit(1)

    vector_dbs = load_multiple_vector_dbs(selected)
    if not vector_dbs:
        print("❌ 로드된 DB 가 없습니다.")
        exit(1)

    answer    = input("\nThinking 모드를 사용할까요? (y/n, 기본값 n): ").strip().lower()
    use_think = (answer == 'y')
    print(f"✅ {'Thinking 모드' if use_think else '빠른 응답 모드 (no_think)'} 선택됨")

    bot = setup_design_bot(vector_dbs, use_think=use_think)
    print("✅ 준비 완료. 질문을 입력하세요. (종료: q)\n")

    history = []
    while True:
        query = input("질문 > ").strip()
        if query.lower() == 'q':
            print("종료합니다.")
            break
        if not query:
            continue
        print("─" * 50)
        answer = bot(query, chat_history=history)
        print(answer)
        print("─" * 50 + "\n")
        history.append({"role": "user",      "content": query})
        history.append({"role": "assistant",  "content": answer})
