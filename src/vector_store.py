import os
import glob
import pandas as pd

# ============ 임베딩 모델 설정 (여기만 변경) ============
EMBEDDING_MODEL = "qwen3-embedding:4b"
# EMBEDDING_MODEL = "gemma2"
# ======================================================

from langchain_core.documents import Document
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings


def prepare_knowledge_base(file_pattern):
    """
    ChromaDB 구축 전용 함수 (table_parser.py 또는 단독 실행 시 호출)
    - 기존 DB 삭제 후 새로 구축
    - 호출 전에 반드시 기존 persist_dir 삭제 처리할 것
    """
    all_files = glob.glob(file_pattern)
    if not all_files:
        raise FileNotFoundError(f"파일을 찾을 수 없습니다: {file_pattern}")

    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    db_name      = EMBEDDING_MODEL.replace(":", "_").replace("-", "_")
    persist_dir  = os.path.join(project_root, "data", "chroma_db", db_name)

    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)

    print(f"ChromaDB 신규 구축 중 (임베딩 모델: {EMBEDDING_MODEL})")
    combined_df = pd.concat(
        [pd.read_excel(f, engine='openpyxl') for f in all_files],
        ignore_index=True
    )

    documents = []
    for _, row in combined_df.iterrows():
        if pd.notna(row['Text']):
            documents.append(Document(page_content=str(row['Text']).strip()))

    print(f"총 {len(documents)}개의 문서를 벡터화합니다.")

    vector_db = Chroma.from_documents(
        documents=documents,
        embedding=embeddings,
        persist_directory=persist_dir,
    )
    print(f"ChromaDB 저장 완료: {persist_dir}")
    return vector_db


def load_vector_db():
    """
    저장된 ChromaDB 로드 전용 함수 (chatbot_meg.py에서 호출)
    - ChromaDB가 없으면 에러 발생 → table_parser.py 또는 vector_store.py 실행 안내
    """
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    db_name      = EMBEDDING_MODEL.replace(":", "_").replace("-", "_")
    persist_dir  = os.path.join(project_root, "data", "chroma_db", db_name)

    if not os.path.exists(persist_dir):
        raise FileNotFoundError(
            f"ChromaDB가 없습니다: {persist_dir}\n"
            f"먼저 'python src/table_parser.py' 또는 'python src/vector_store.py'를 실행해주세요."
        )

    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    print(f"저장된 ChromaDB 로드 중: {persist_dir}")
    vector_db = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )
    print(f"총 {vector_db._collection.count()}개의 문서를 로드했습니다.")
    return vector_db


# --- 단독 실행 시: 임베딩 모델 변경 후 ChromaDB 재구축 ---
if __name__ == "__main__":
    import sys
    import shutil

    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    data_pattern = os.path.join(project_root, 'data', 'result', 'final_text_data_*.xlsx')
    db_name      = EMBEDDING_MODEL.replace(":", "_").replace("-", "_")
    persist_dir  = os.path.join(project_root, "data", "chroma_db", db_name)

    if os.path.exists(persist_dir):
        answer = input(f"기존 ChromaDB({db_name})를 삭제하고 재구축할까요? (y/n): ").strip().lower()
        if answer != 'y':
            print("⚠️  취소했습니다.")
            sys.exit(0)
        shutil.rmtree(persist_dir)
        print(f"기존 ChromaDB 삭제 완료: {persist_dir}")

    print(f"\nChromaDB 구축 시작 (임베딩 모델: {EMBEDDING_MODEL})")
    try:
        prepare_knowledge_base(data_pattern)
        print("✅ ChromaDB 구축 완료.")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
