import os
import pandas as pd
import streamlit as st
import requests
import glob
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_ollama import OllamaEmbeddings, OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

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

# [상태 체크]
def check_ollama():
    try:
        response = requests.get("http://localhost:11434")
        return response.status_code == 200
    except:
        return False

# [RAG 로직] 지식 베이스 구축
@st.cache_resource
def prepare_knowledge_base(file_pattern):
    all_files = glob.glob(file_pattern)
    if not all_files:
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_pattern}")
    
    combined_df = pd.concat([pd.read_excel(f) for f in all_files], ignore_index=True)
    
    documents = []
    for _, row in combined_df.iterrows():
        if pd.notna(row['Text']):
            documents.append(Document(page_content=str(row['Text']).strip()))
    
    embeddings = OllamaEmbeddings(model="gemma2")
    # 검색 정확도를 위해 새로운 컬렉션 생성
    vector_db = Chroma.from_documents(
        documents=documents, 
        embedding=embeddings, 
        collection_name="design_bot_final_v8"
    )
    return vector_db

# [개선] Query Expansion (좌/우, 상/하 등 대칭 키워드 보강)
def expand_query(query, llm):
    expansion_template = """
    너는 기구 설계 전문가야. 사용자의 질문을 분석하여 검색에 도움이 될 단어들을 추가해줘.
    특히 방향(상/하/좌/우/전/후), 단위, 부품 명칭의 유의어를 포함하라.
    결과는 콤마(,)로 구분된 단어들만 출력해.
    
    사용자 질문: {query}
    결과:"""
    prompt = ChatPromptTemplate.from_template(expansion_template)
    chain = prompt | llm | StrOutputParser()
    try:
        expanded_terms = chain.invoke({"query": query})
        return f"{query}, {expanded_terms}"
    except:
        return query

# [RAG 로직] 챗봇 엔진 설정
def setup_design_bot(vector_db):
    llm = OllamaLLM(model="gemma2", temperature=0.1)
    
    # [수정] 유사도 임계치를 낮추고 검색 후보(k)를 10개로 대폭 확대
    # 이렇게 하면 '좌/우'처럼 미세하게 밀려난 데이터도 검색 범위에 들어옵니다.
    retriever = vector_db.as_retriever(
        search_type="similarity_score_threshold",
        search_kwargs={
            "k": 10, 
            "score_threshold": 0.3  # 임계치를 0.3으로 낮추어 넓게 탐색
        }
    )

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
        # 1. 쿼리 확장 (상하좌우 등 누락 방지)
        expanded_q = expand_query(query, llm)
        
        # 2. 문서 검색 (유사도 점수 포함 탐색)
        docs_with_scores = vector_db.similarity_search_with_relevance_scores(expanded_q, k=10)
        
        # 3. 임계치에 따른 필터링 (최소한의 관련성 확보)
        valid_docs = [doc for doc, score in docs_with_scores if score > 0.2]
        
        # 만약 점수가 너무 낮다면 상위 1~2개만 강제로 context에 넣음 (유사 답변 유도)
        if not valid_docs and docs_with_scores:
            valid_docs = [docs_with_scores[0][0]]
            
        context_text = "\n\n".join(doc.page_content for doc in valid_docs)
        
        chain = prompt | llm | StrOutputParser()
        response = chain.invoke({"context": context_text, "question": query})
        return response

    return rag_handler

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

    current_dir = os.path.dirname(os.path.abspath(__file__))
    data_pattern = os.path.join(current_dir, 'preprocess', 'result', 'final_text_data_*.xlsx')

    if glob.glob(data_pattern):
        if "bot" not in st.session_state:
            with st.spinner("지식 베이스 구축 중..."):
                db = prepare_knowledge_base(data_pattern)
                st.session_state.bot = setup_design_bot(db)

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
    else:
        st.error("정제된 데이터 파일을 찾을 수 없습니다.")
