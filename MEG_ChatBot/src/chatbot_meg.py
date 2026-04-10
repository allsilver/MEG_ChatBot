import os
import json
import streamlit as st
from datetime import datetime
from vector_store import load_multiple_vector_dbs
from rag_engine import check_ollama, setup_design_bot

st.set_page_config(page_title="AI 설계 어시스턴트 챗봇", layout="wide")


# ── 로그 저장 ────────────────────────────────────────────────────
def save_log(question: str, answer: str, domain_key: str, selected_keys: list):
    try:
        current_dir  = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(current_dir)
        log_dir      = os.path.join(project_root, "data", "logs")
        os.makedirs(log_dir, exist_ok=True)

        log_entry = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "domain":    domain_key,
            "db_keys":   selected_keys,
            "question":  question,
            "answer":    answer,
        }
        log_path = os.path.join(log_dir, "chat_log.jsonl")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


# ── 인증 ─────────────────────────────────────────────────────────
def check_password():
    if st.session_state.get("password_correct", False):
        return True
    placeholder = st.empty()
    with placeholder.container():
        st.title("🛡️ AI 설계 어시스턴트 접속 보안")
        pw = st.text_input("접속 비밀번호를 입력하세요.", type="password", key="login_password")
        if st.button("접속하기"):
            if pw in ["3차원!", "3ckdnjs!"]:
                st.session_state["password_correct"] = True
                placeholder.empty()
                st.rerun()
            else:
                st.error("❌ 비밀번호가 틀렸습니다.")
    return False


# ── Registry 로드 ─────────────────────────────────────────────────
def load_registries() -> tuple[dict, dict]:
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    def _load(filename):
        for base in [current_dir, project_root]:
            path = os.path.join(base, filename)
            if os.path.exists(path):
                with open(path, encoding='utf-8') as f:
                    return json.load(f)
        return {}

    return _load('domain_registry.json'), _load('db_registry.json')


# ── 지식베이스 로드 (캐싱) ────────────────────────────────────────
@st.cache_resource
def load_knowledge_base(domain_key: str, selected_keys_tuple: tuple, use_think: bool):
    """도메인·DB조합·think 모드 중 하나라도 바뀌면 캐시 무효화"""
    dbs = load_multiple_vector_dbs(domain_key, list(selected_keys_tuple))
    if not dbs:
        raise FileNotFoundError("선택한 지식베이스를 하나도 로드할 수 없습니다.")
    domain_registry, _ = load_registries()
    domain_config = domain_registry[domain_key]
    return setup_design_bot(dbs, domain_config, use_think=use_think)


# ── 메인 ─────────────────────────────────────────────────────────
if check_password():
    domain_registry, db_registry = load_registries()
    domain_keys = list(domain_registry.keys())

    with st.sidebar:
        st.title("⚙️ 설정 및 도움말")
        st.markdown("---")

        # ── 분야 선택 ─────────────────────────────────────────────
        st.subheader("분야")
        selected_domain_key = st.selectbox(
            label="분야 선택",
            options=domain_keys,
            index=0,
            format_func=lambda k: domain_registry[k]["display_name"],
            label_visibility="collapsed",
        )
        domain_config = domain_registry[selected_domain_key]
        st.caption(domain_config.get("description", ""))

        st.markdown("---")

        # ── 지식베이스 선택 ───────────────────────────────────────
        available_db_keys = [k for k in domain_config.get("db_keys", []) if k in db_registry]

        if available_db_keys:
            st.subheader("검색할 지식베이스")
            selected_keys = st.multiselect(
                label="지식베이스 선택",
                options=available_db_keys,
                default=[available_db_keys[0]],
                format_func=lambda k: db_registry[k]["display_name"],
                label_visibility="collapsed",
            )
            for k in selected_keys:
                st.caption(f"• {db_registry[k].get('description', '')}")
        else:
            st.info("이 분야는 아직 지식베이스가 없습니다.")
            selected_keys = []

        st.markdown("---")

        # ── Thinking 모드 (allow_think_toggle 분야만 표시) ────────
        if domain_config.get("allow_think_toggle", False):
            use_think = st.toggle(
                "Thinking 모드",
                value=domain_config.get("default_use_think", False),
                help="활성화 시 더 깊이 추론합니다. 응답 속도가 느려집니다.",
            )
            st.caption("현재: Thinking 모드 (느림/정확)" if use_think else "현재: 빠른 응답 모드")
            st.markdown("---")
        else:
            use_think = domain_config.get("default_use_think", False)

        if st.button("대화 기록 초기화"):
            st.session_state.messages = []
            st.rerun()

    # ── 메인 채팅 영역 ────────────────────────────────────────────
    st.title(f"🛡️ AI 설계 어시스턴트 — {domain_config['display_name']}")

    if not check_ollama():
        st.warning("⚠️ AI 엔진(Ollama)이 실행되고 있지 않습니다.")
        st.stop()

    if not selected_keys:
        st.info("사이드바에서 검색할 지식베이스를 선택해주세요.")
        st.stop()

    # 분야·DB·모드 변경 시 봇 재초기화 + 대화 자동 초기화
    current_state = (selected_domain_key, tuple(sorted(selected_keys)), use_think)
    if st.session_state.get("bot_state") != current_state:
        with st.spinner("지식 베이스 로드 중..."):
            try:
                st.session_state.bot       = load_knowledge_base(
                    selected_domain_key, tuple(sorted(selected_keys)), use_think
                )
                st.session_state.bot_state = current_state
                st.session_state.messages  = []
            except FileNotFoundError as e:
                st.error(f"❌ {e}")
                st.stop()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    if user_input := st.chat_input("설계 항목을 입력하세요..."):
        st.session_state.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        with st.chat_message("assistant"):
            try:
                response = st.write_stream(
                    st.session_state.bot.stream(
                        user_input,
                        chat_history=st.session_state.messages[:-1],
                    )
                )
                st.session_state.messages.append({"role": "assistant", "content": response})
                save_log(user_input, response, selected_domain_key, selected_keys)
            except Exception as e:
                st.error(f"오류가 발생했습니다: {str(e)}")
