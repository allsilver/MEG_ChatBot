import os
import requests
from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

# 대화 중 문맥으로 포함할 최근 턴 수 (1턴 = 질문 1개 + 답변 1개)
CHAT_HISTORY_TURNS = 3


def check_ollama():
    try:
        response = requests.get("http://localhost:11434")
        return response.status_code == 200
    except Exception:
        return False


def _load_prompt_template(prompt_file: str) -> str:
    """src/prompts/ 폴더에서 프롬프트 텍스트 파일을 읽어 반환"""
    current_dir = os.path.dirname(os.path.abspath(__file__))
    prompt_path = os.path.join(current_dir, "prompts", prompt_file)
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(
            f"프롬프트 파일을 찾을 수 없습니다: {prompt_path}\n"
            f"src/prompts/{prompt_file} 파일이 있는지 확인해주세요."
        )
    with open(prompt_path, encoding="utf-8") as f:
        return f.read()


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
    recent = chat_history[-(CHAT_HISTORY_TURNS * 2):]
    lines  = []
    for m in recent:
        role = "사용자" if m["role"] == "user" else "어시스턴트"
        lines.append(f"{role}: {m['content']}")
    return "\n".join(lines)


def setup_design_bot(vector_dbs, domain_config: dict, use_think: bool = False):
    """
    RAG 챗봇 핸들러 반환.

    vector_dbs   : dict[str, Chroma] — {db_key: vector_db}
                   단일 Chroma 객체도 하위 호환으로 수용 (dict로 래핑)
    domain_config: domain_registry.json 의 해당 분야 설정 dict
    use_think    : Thinking 모드 여부 (allow_think_toggle=True 인 분야만 의미 있음)
    """
    if not isinstance(vector_dbs, dict):
        vector_dbs = {"default": vector_dbs}

    model_name  = domain_config.get("model", "qwen3:8b")
    prompt_file = domain_config.get("prompt_file", "concise.txt")

    llm = OllamaLLM(model=model_name, temperature=0.1)

    # /no_think 접두사: thinking 모드 비활성화 시 삽입
    no_think_prefix  = "" if use_think else "/no_think\n"
    prompt_template  = no_think_prefix + _load_prompt_template(prompt_file)
    prompt           = ChatPromptTemplate.from_template(prompt_template)

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

    # domain_registry 로드
    domain_registry_path = os.path.join(current_dir, 'domain_registry.json')
    try:
        with open(domain_registry_path, encoding='utf-8') as f:
            domain_registry = json.load(f)
    except FileNotFoundError:
        print("❌ domain_registry.json 을 찾을 수 없습니다.")
        exit(1)

    # db_registry 로드
    db_registry_path = os.path.join(current_dir, 'db_registry.json')
    try:
        with open(db_registry_path, encoding='utf-8') as f:
            db_registry = json.load(f)
    except FileNotFoundError:
        print("❌ db_registry.json 을 찾을 수 없습니다.")
        exit(1)

    print("\n등록된 분야 목록:")
    for key, info in domain_registry.items():
        print(f"  [{key}] {info['display_name']} — 모델: {info['model']}")

    domain_key = input("\n사용할 분야 키를 입력하세요: ").strip()
    if domain_key not in domain_registry:
        print(f"❌ '{domain_key}' 는 등록된 분야가 아닙니다.")
        exit(1)

    domain_config = domain_registry[domain_key]
    default_dbs   = domain_config.get("db_keys", [])
    available_dbs = [k for k in default_dbs if k in db_registry]

    print(f"\n[{domain_config['display_name']}] 기본 DB 목록: {available_dbs}")
    keys_input = input("검색할 DB 키 (Enter = 전체 사용): ").strip()
    if keys_input:
        selected = [k.strip() for k in keys_input.split(",") if k.strip() in db_registry]
    else:
        selected = available_dbs

    vector_dbs = load_multiple_vector_dbs(selected)
    if not vector_dbs:
        print("❌ 로드된 DB 가 없습니다.")
        exit(1)

    use_think = False
    if domain_config.get("allow_think_toggle", False):
        answer    = input("\nThinking 모드를 사용할까요? (y/n, 기본값 n): ").strip().lower()
        use_think = (answer == 'y')
    else:
        use_think = domain_config.get("default_use_think", False)

    print(f"✅ 모델: {domain_config['model']} / {'Thinking 모드' if use_think else 'no_think 모드'}")

    bot = setup_design_bot(vector_dbs, domain_config, use_think=use_think)
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
        history.append({"role": "user",     "content": query})
        history.append({"role": "assistant", "content": answer})
