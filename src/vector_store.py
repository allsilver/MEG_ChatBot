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


def _get_persist_dir(db_key: str) -> str:
    """db_key에 해당하는 ChromaDB 경로 반환"""
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    db_name      = EMBEDDING_MODEL.replace(":", "_").replace("-", "_")
    return os.path.join(project_root, "data", "chroma_db", db_key, db_name)


def prepare_knowledge_base(db_key: str):
    """
    ChromaDB 구축 전용 함수 (table_parser.py 또는 단독 실행 시 호출)
    - db_key 에 해당하는 result/ 폴더의 final_text_data_*.xlsx 를 읽어 구축
    - 호출 전에 반드시 기존 persist_dir 삭제 처리할 것
    """
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    file_pattern = os.path.join(project_root, "data", "result", db_key, "final_text_data_*.xlsx")

    all_files = glob.glob(file_pattern)
    if not all_files:
        raise FileNotFoundError(
            f"변환 결과 파일을 찾을 수 없습니다: {file_pattern}\n"
            f"먼저 table_parser.py 를 실행해 LLM 변환을 완료해주세요."
        )

    persist_dir = _get_persist_dir(db_key)
    embeddings  = OllamaEmbeddings(model=EMBEDDING_MODEL)

    print(f"ChromaDB 신규 구축 중 [{db_key}] (임베딩 모델: {EMBEDDING_MODEL})")
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


def load_vector_db(db_key: str):
    """
    저장된 ChromaDB 로드 전용 함수
    - db_key 에 해당하는 ChromaDB 를 로드
    - DB 없으면 FileNotFoundError 발생
    """
    persist_dir = _get_persist_dir(db_key)

    if not os.path.exists(persist_dir):
        raise FileNotFoundError(
            f"ChromaDB 가 없습니다 [{db_key}]: {persist_dir}\n"
            f"먼저 'python src/table_parser.py' 를 실행해 DB 를 구축해주세요."
        )

    embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
    print(f"ChromaDB 로드 중 [{db_key}]: {persist_dir}")
    vector_db = Chroma(
        persist_directory=persist_dir,
        embedding_function=embeddings,
    )
    print(f"  → {vector_db._collection.count()}개 문서 로드 완료")
    return vector_db


def load_multiple_vector_dbs(db_keys: list[str]) -> dict:
    """
    여러 db_key 에 해당하는 ChromaDB 를 dict 로 반환
    로드 실패한 DB 는 건너뛰고 경고 출력
    """
    result = {}
    for key in db_keys:
        try:
            result[key] = load_vector_db(key)
        except FileNotFoundError as e:
            print(f"⚠️  [{key}] 로드 실패 — 건너뜁니다: {e}")
    return result


# --- 단독 실행 시: 특정 DB 재구축 ---
if __name__ == "__main__":
    import sys
    import json
    import shutil

    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    # registry 에서 DB 목록 읽기
    registry_path = os.path.join(project_root, "src", "db_registry.json")
    if not os.path.exists(registry_path):
        registry_path = os.path.join(project_root, "db_registry.json")

    try:
        with open(registry_path, encoding="utf-8") as f:
            registry = json.load(f)
    except FileNotFoundError:
        print("❌ db_registry.json 을 찾을 수 없습니다.")
        sys.exit(1)

    print("등록된 DB 목록:")
    for key, info in registry.items():
        print(f"  {key}: {info['display_name']}")

    db_key = input("\n재구축할 DB 키를 입력하세요: ").strip()
    if db_key not in registry:
        print(f"❌ '{db_key}' 는 registry 에 없는 키입니다.")
        sys.exit(1)

    persist_dir = _get_persist_dir(db_key)
    if os.path.exists(persist_dir):
        answer = input(f"기존 ChromaDB [{db_key}] 를 삭제하고 재구축할까요? (y/n): ").strip().lower()
        if answer != 'y':
            print("⚠️  취소했습니다.")
            sys.exit(0)
        shutil.rmtree(persist_dir)
        print(f"기존 ChromaDB 삭제 완료: {persist_dir}")

    try:
        prepare_knowledge_base(db_key)
        print(f"✅ [{db_key}] ChromaDB 구축 완료.")
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
