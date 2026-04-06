# MEG_ChatBot

SEC MEG(기구 설계) 표준 체크리스트를 기반으로 한 **AI 설계 어시스턴트 챗봇**.
설계 항목을 자연어로 질문하면 RAG(검색 증강 생성) 방식으로 관련 설계 표준 가이드를 검색하여 전문가 어투로 답변합니다.

---

## 주요 기능

- **자연어 설계 질의응답** — 설계 항목·치수·조건을 자연어로 질문
- **RAG 기반 검색** — ChromaDB 벡터 검색으로 관련 표준 가이드 추출
- **ChromaDB 영구 저장** — 임베딩 모델별로 DB를 저장, 재실행 시 즉시 로드
- **비밀번호 인증** — Streamlit 세션 기반 접근 제어
- **대화 기록 관리** — 사이드바에서 초기화 가능

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| UI | Streamlit |
| LLM (생성) | Ollama (기본: qwen3:8b) |
| LLM (전처리) | Ollama (기본: qwen3:14b) |
| 임베딩 | OllamaEmbeddings (기본: qwen3-embedding:4b) |
| 벡터 DB | ChromaDB (persist 방식, 임베딩 모델별 저장) |
| LLM 프레임워크 | LangChain |
| 데이터 처리 | pandas, openpyxl |
| Excel 자동화 | win32com (전처리 단계, Windows 전용) |

---

## 시스템 요구사항

- Python 3.9+
- [Ollama](https://ollama.ai) 설치 및 사용 모델 pull
- 전처리 단계: Windows 환경 필요 (win32com 사용)
- 챗봇 실행: 크로스플랫폼 가능
- 권장 GPU: NVIDIA RTX A4000 이상 (VRAM 16GB)

---

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install streamlit pandas openpyxl langchain langchain-community langchain-ollama langchain-chroma chromadb tqdm
```

### 2. Ollama 설치 및 모델 준비

```bash
ollama pull gemma2                  # 조합A 임베딩+생성
ollama pull gemma4:e4b              # 조합B 생성
ollama pull qwen3:8b                # 조합C 생성 (권장)
ollama pull qwen3:14b               # 전처리 LLM
ollama pull qwen3-embedding:4b      # 조합C 임베딩 (권장)

ollama serve  # 서버 실행 (http://localhost:11434)
```

### 3. 전처리 + LLM 변환 + ChromaDB 구축 (최초 1회 또는 데이터 변경 시)

원본 Excel 체크리스트 파일을 `data/raw_data/` 폴더에 위치시킨 후:

```bash
python src/table_parser.py
```

실행 시 아래 두 가지를 먼저 질문합니다. 입력 후 자리를 비워도 됩니다.

```
[1/2] 전처리를 다시 수행할까요? (y/n)
[2/2] ChromaDB를 새로 구축할까요? (y/n)
```

이후 자동으로 진행됩니다:
1. 전처리 (y 선택 시 또는 파일 없을 때 자동 수행)
2. LLM 마크다운 변환
3. ChromaDB 구축 (y 선택 시)

전처리만 단독 실행하려면:
```bash
python src/preprocess_meg.py  # Windows 전용
```

임베딩 모델만 변경 후 ChromaDB만 재구축하려면:
```bash
python src/vector_store.py
```

### 4. 챗봇 앱 실행

```bash
streamlit run src/chatbot_meg.py
```

브라우저에서 `http://localhost:8501` 접속 후 비밀번호 입력.
ChromaDB가 이미 구축되어 있으면 즉시 로드됩니다.

---

## 모델 설정 및 전환

각 파일 상단 설정 블록에서 주석만 변경하면 모델 전환이 가능합니다.

### 생성 모델 (`src/rag_engine.py`)
```python
GENERATOR_MODEL = "qwen3:8b"      # 현재 설정 (권장)
# GENERATOR_MODEL = "gemma2"
# GENERATOR_MODEL = "gemma4:e4b"
# GENERATOR_MODEL = "qwen3:14b"
```

### 임베딩 모델 (`src/vector_store.py`)
```python
EMBEDDING_MODEL = "qwen3-embedding:4b"  # 현재 설정 (권장)
# EMBEDDING_MODEL = "gemma2"
```

### 전처리 LLM (`src/table_parser.py`)
```python
TABLE_PARSER_MODEL = "qwen3:14b"   # 현재 설정 (한국어 특화)
# TABLE_PARSER_MODEL = "gemma2"
# TABLE_PARSER_MODEL = "gemma4:e4b"
```

> 임베딩 모델 변경 시 ChromaDB 재구축 필요 → `python src/vector_store.py` 실행
> 생성 모델 변경 시 재구축 불필요 → 앱 재시작만 하면 됨

---

## 데이터 파이프라인

```
원본 Excel 체크리스트 (data/raw_data/)
    └─► table_parser.py 실행
            ├─ [자동] 제외 키워드(OLD, old, 삭제) 포함 파일 필터링
            ├─ [자동] Excel → CSV 변환 (win32com)
            ├─ [자동] No / Title / Item / Guide / Reason 컬럼 추출
            │         → preprocessed_data_semi.xlsx
            ├─ [자동] Title 정제 (숫자 인덱스·특수문자 제거, 2D/2.5D/3D 보호)
            │         → preprocessed_data_final.xlsx
            ├─ LLM(TABLE_PARSER_MODEL)으로 마크다운 서술형 텍스트 변환
            │         → final_text_data_1.xlsx, final_text_data_2.xlsx, ...
            └─ OllamaEmbeddings(EMBEDDING_MODEL) → ChromaDB 구축
                      (data/chroma_db/<모델명>/ 저장)
                              │
    └─► chatbot_meg.py (앱 구동 시)
            ├─ ChromaDB 로드 (구축 없음, 즉시 로드)
            └─ 질문 → 벡터 검색 → LLM(GENERATOR_MODEL) 답변
```

---

## 디렉토리 구조

```
MEG_ChatBot/
├── .gitignore
├── src/
│   ├── chatbot_meg.py          # 메인 Streamlit 챗봇 앱
│   ├── rag_engine.py           # RAG 엔진 - 생성 모델 설정 + 답변 생성
│   ├── vector_store.py         # 임베딩 모델 설정 + ChromaDB 구축/로드
│   ├── preprocess_meg.py       # 데이터 전처리 스크립트 (Windows 전용)
│   └── table_parser.py         # 통합 실행 진입점
│
└── data/                       # git 제외 폴더
    ├── raw_data/               # ← 원본 Excel 파일을 여기에 위치
    ├── converted_csv/          # 변환된 CSV 파일
    ├── chroma_db/              # ChromaDB 저장 (임베딩 모델별 하위 폴더)
    │   └── qwen3_embedding_4b/ # 현재 사용 중인 DB
    └── result/                 # 전처리 결과물
        ├── preprocessed_data_semi.xlsx
        ├── preprocessed_data_final.xlsx
        └── final_text_data_*.xlsx
```

---

## 답변 방식

LLM은 검색 결과에 따라 3단계로 답변합니다:

1. **표준 확인** — 관련 데이터가 충분할 때: *"확인된 설계 표준 가이드는 다음과 같습니다."*
2. **유사 사례** — 완전 일치하지 않지만 관련 데이터 있을 때: *"정확한 표준은 확인되지 않지만, 가장 유사한 사례를 기반으로 안내해 드립니다."*
3. **재질문 요청** — 관련 데이터 없을 때

수치(mm, T 등)와 설계 조건은 반드시 포함되며, 구어체로 자연스럽게 서술됩니다.
