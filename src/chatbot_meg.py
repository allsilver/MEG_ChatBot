import os
import glob
import streamlit as st
from rag_engine import check_ollama, prepare_knowledge_base, setup_design_bot

# UI 설정
st.set_page_config(page_title="AI 설계 어시스턴트 챗봇", layout="wide")


# [보안 로직]
def check_password():
    if st.session_state.get("password_correct", False):
        return True
    login_placeholder = st.empty()
    with login_placeholder.container():
        st.title("🛡️ AI 설계 어시스턴트 접속 보안")
        password_input = st.text_input("접속 비밀번호를 입력하세요.", type="password", key="login_password")
        if st.button("접속하기"):
            if password_input in ["3차원!", "3ckdnjs!"]:
                st.session_state["password_correct"] = True
                login_placeholder.empty()
                st.rerun()
            else:
                st.error("❌ 비밀번호가 틀렸습니다.")
    return False


# [지식 베이스] @st.cache_resource는 Streamlit 의존성이므로 UI 파일에서 관리
@st.cache_resource
def load_knowledge_base(file_pattern):
    db = prepare_knowledge_base(file_pattern)
    return setup_design_bot(db)


# --- 메인 실행 프로세스 ---
if check_password():
    with st.sidebar:
        st.title("⚙️ 설정 및 도움말")
        st.markdown("---")
        if st.button("대화 기록 초기화"):
            st.session_state.messages = []
            st.rerun()

    st.title("🛡️ AI 설계 어시스턴트 챗봇")

    if not check_ollama():
        st.warning("⚠️ 서버의 AI 엔진(Ollama)이 실행되고 있지 않습니다.")
        st.stop()

    current_dir  = os.path.dirname(os.path.abspath(__file__))  # MEG_ChatBot/src/
    project_root = os.path.dirname(current_dir)                 # MEG_ChatBot/
    data_pattern = os.path.join(project_root, 'data', 'result', 'final_text_data_*.xlsx')

    if not glob.glob(data_pattern):
        st.error("❌ 정제된 데이터 파일을 찾을 수 없습니다. table_parser.py를 먼저 실행해주세요.")
        st.stop()

    if "bot" not in st.session_state:
        with st.spinner("지식 베이스 구축 중..."):
            st.session_state.bot = load_knowledge_base(data_pattern)

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
            with st.spinner("전문가 가이드를 분석 중입니다..."):
                try:
                    response = st.session_state.bot(user_input)
                    st.markdown(response)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {str(e)}")
