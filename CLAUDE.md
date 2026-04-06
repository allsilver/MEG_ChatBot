# CLAUDE.md — MEG_ChatBot 개발 가이드

## 프로젝트 개요

SEC MEG(기구 설계) 표준 체크리스트를 기반으로 한 **RAG(검색 증강 생성) 설계 어시스턴트 챗봇**.
설계 담당자가 자연어로 설계 항목을 질문하면, 사전 구축된 지식 베이스에서 관련 표준 가이드를 검색하여 전문가 어투로 답변한다.

---

## 디렉토리 구조

```
MEG_ChatBot/
├── .gitignore
├── data/                               # 전처리 데이터 폴더 (git 제외)
│   ├── raw_data/                       # 원본 Excel 체크리스트 파일 위치
│   ├── converted_csv/                  # Excel → CSV 변환 결과
│   ├── error/                          # 단계별 에러 로그 (error_log_*.txt)
│   ├── chroma_db/                      # ChromaDB 저장 폴더 (git 제외)
│   │   └── qwen3_embedding_4b/         # 현재 사용 중인 DB (임베딩 모델별 생성)
│   └── result/
│       ├── preprocessed_data_semi.xlsx   # 1차 추출 결과 (No, Title, Item, Guide, Reason)
│       ├── preprocessed_data_final.xlsx  # 2차 정제 완료 결과 (Title, Item, Guide, Reason)
│       └── final_text_data_*.xlsx        # LLM 마크다운 변환 결과 (500행 단위 청크)
│
└── src/
    ├── chatbot_meg.py      # 메인 Streamlit 앱 — ChromaDB 로드 + 답변
    ├── rag_engine.py       # 생성 모델 설정 + RAG 답변 생성
    ├── vector_store.py     # 임베딩 모델 설정 + ChromaDB 구축/로드
    ├── preprocess_meg.py   # 원본 Excel → 정제 데이터 전처리 (Windows 전용)
    └── table_parser.py     # 통합 실행 진입점 (전처리 + LLM 변환 + ChromaDB 구축)
```

---

## 데이터 처리 파이프라인

```
[원본 Excel 체크리스트] (data/raw_data/)
        ↓  table_parser.py 실행
  [필터링] 제외 키워드(OLD, old, 삭제) 포함 파일 제외
        ↓
  Excel → win32com → CSV 변환 (data/converted_csv/)
  No / Title / Item / Guide / Reason 컬럼 추출
        ↓
  preprocessed_data_semi.xlsx  (data/result/, 1차 중간 저장)
        ↓
  Title 컬럼 정제 (숫자 인덱스·특수문자 제거, 2D/2.5D/3D 예외 보호)
        ↓
  preprocessed_data_final.xlsx  (data/result/)
        ↓
  Ollama LLM (TABLE_PARSER_MODEL) 으로 마크다운 서술형 텍스트 변환
  (500행 단위 청크 분할 저장)
        ↓
  final_text_data_1.xlsx, final_text_data_2.xlsx, ... (data/result/)
        ↓
  OllamaEmbeddings (EMBEDDING_MODEL) → ChromaDB 구축
  (data/chroma_db/<모델명>/ 에 저장)
        ↓  chatbot_meg.py (앱 구동 시)
  ChromaDB 로드만 수행 (구축 없음, 즉시 로드)
        ↓
  RAG 검색 + LLM (GENERATOR_MODEL) 답변 생성
```

---

## 각 파일 상세

### `src/chatbot_meg.py`

- **UI**: Streamlit (`st.set_page_config`, `st.chat_input` 등)
- **인증**: `check_password()` — 세션 기반 비밀번호 인증
- **지식베이스**: `load_knowledge_base()` — `@st.cache_resource`로 캐싱
  - `load_vector_db()` 호출 → ChromaDB 로드만 수행 (구축 없음)
  - ChromaDB 없으면 에러 메시지 출력 후 종료
- **Ollama 상태 확인**: `check_ollama()` — `http://localhost:11434` 헬스체크

---

### `src/rag_engine.py`

- **역할**: 생성 모델 설정 + RAG 답변 생성 전담
- **모델 설정 블록** (파일 상단)
  ```python
  GENERATOR_MODEL = "qwen3:8b"      # 현재 설정 (권장)
  # GENERATOR_MODEL = "gemma2"
  # GENERATOR_MODEL = "gemma4:e4b"
  # GENERATOR_MODEL = "qwen3:14b"
  ```
- **`setup_design_bot(vector_db)`**: RAG 챗봇 핸들러 반환
  - `similarity_search_with_relevance_scores` — k=10, score > 0.2 필터링
  - 결과 없을 시 상위 1개 강제 포함 (유사 답변 유도)
  - `/no_think` 프롬프트 접두사로 qwen3 thinking 모드 비활성화 (속도 개선)
- **생성 모델만 변경 시**: `rag_engine.py` 상단 주석 변경 후 앱 재시작만 하면 됨 (ChromaDB 재구축 불필요)

**LLM 프롬프트 답변 규칙**
1. 밀접한 데이터 → "확인된 설계 표준 가이드는 다음과 같습니다."
2. 유사 데이터 → "정확한 표준은 확인되지 않지만, 가장 유사한 사례를 기반으로 안내해 드립니다."
3. 수치·조건(mm, T 등) 누락 금지
4. 마크다운 기호 노출 금지, 구어체 사용
5. 완전 무관 시 질문 재입력 요청

---

### `src/vector_store.py`

- **역할**: 임베딩 모델 설정 + ChromaDB 구축/로드 전담
- **모델 설정 블록** (파일 상단)
  ```python
  EMBEDDING_MODEL = "qwen3-embedding:4b"  # 현재 설정 (권장)
  # EMBEDDING_MODEL = "gemma2"
  ```
- **`prepare_knowledge_base(file_pattern)`**: ChromaDB 신규 구축 전용
  - `data/chroma_db/<모델명>/` 에 저장
  - `table_parser.py` 또는 단독 실행 시 호출
- **`load_vector_db()`**: ChromaDB 로드 전용
  - `chatbot_meg.py`에서 호출
  - DB 없으면 `FileNotFoundError` 발생 → 에러 메시지로 실행 안내
- **단독 실행** (`python src/vector_store.py`): 임베딩 모델 변경 후 ChromaDB만 재구축할 때 사용

---

### `src/preprocess_meg.py`

- **플랫폼**: Windows 전용 (`win32com.client` 사용)
- **경로 기준**: `src/preprocess_meg.py` 위치에서 상위 폴더(`project_root`)의 `data/` 사용
- **`convert_all_excel_to_csv(data_root)`**: `data/raw_data/` 하위 모든 `.xlsx`를 COM 자동화로 CSV 변환
  - **제외 키워드 필터**: 파일명에 `OLD`, `old`, `삭제` 포함 시 수집 단계에서 제외
  - 파일명에 `[`, `]` 포함 시 `converted_csv/`에 괄호 제거한 이름으로 복사 후 처리, 완료 후 삭제
  - CSV 경로 길이 218자 초과 시 스킵 (`MAX_CSV_PATH_LENGTH` 상수)
  - Excel 초기화 실패 시 최대 3회 재시도
  - 실패 파일 목록 → `data/error/error_log_excel_to_csv_*.txt`
- **`process_and_save_checklists(data_root, csv_folder)`**: CSV에서 헤더 행(`NO`, `ITEM`, `GUIDE` 포함) 탐색 후 데이터 추출
  - `NO` 컬럼이 단일 알파벳(`A`~`Z`)인 행만 유효 데이터로 처리
  - ITEM 다중 컬럼 병합, GUIDE 다중 컬럼 병합 (콤마 구분)
  - `FIGURE` 컬럼 이전까지만 GUIDE로 인식
  - 출력 컬럼: `No, Title, Item, Guide, Reason`
  - 실패 파일 목록 → `data/error/error_log_extract_checklists_*.txt`
- **`run_2nd_preprocessing(data_root, input_file_name)`**: Title 컬럼 정제
  - 앞 숫자 인덱스 제거 (`re.sub(r'^[0-9\s.\-_]+'...`)
  - 괄호·특수기호 → 공백 치환
  - **예외 보호**: `2D`, `2.5D`, `3D` 키워드는 정제 과정에서 보호 후 복원
  - 출력 컬럼: `Title, Item, Guide, Reason` (No 제외)

---

### `src/table_parser.py`

- **통합 실행 진입점** — 이 파일 하나로 전처리 → LLM 변환 → ChromaDB 구축까지 처리
- **모델 설정 블록** (파일 상단)
  ```python
  # TABLE_PARSER_MODEL = "gemma2"
  # TABLE_PARSER_MODEL = "gemma4:e4b"
  TABLE_PARSER_MODEL = "qwen3:14b"   # 현재 설정 (한국어 특화)
  ```
- **실행 시작 시 모든 질문을 먼저 받음** (이후 자동 실행)
  ```
  [1/2] 전처리 다시 수행할까요? (y/n)
  [2/2] ChromaDB를 새로 구축할까요? (y/n)
  → "자리를 비워도 됩니다." 출력 후 자동 진행
  ```
- **실행 흐름**:
  1. 전처리 (y 선택 또는 파일 없을 때 자동 수행)
  2. LLM 마크다운 변환
  3. ChromaDB 구축 (y 선택 시, `vector_store.prepare_knowledge_base()` 호출)
- LLM 호출 실패 시 원본 Guide 텍스트로 폴백
- `Reason` 컬럼은 현재 미사용 (향후 보강 예정)

---

## 모델 설정 요약

| 파일 | 설정 상수 | 현재 값 | 변경 시 ChromaDB 재구축 |
|---|---|---|---|
| `table_parser.py` | `TABLE_PARSER_MODEL` | `qwen3:14b` | 필요 (데이터 재생성) |
| `vector_store.py` | `EMBEDDING_MODEL` | `qwen3-embedding:4b` | 필요 |
| `rag_engine.py` | `GENERATOR_MODEL` | `qwen3:8b` | 불필요 |

---

## 개발 시 주의사항

### 보안
- `chatbot_meg.py` — 비밀번호가 소스코드에 하드코딩되어 있음
  → 환경변수 또는 외부 시크릿 관리로 교체 필요

### 플랫폼 의존성
- `preprocess_meg.py`는 `win32com` 사용으로 **Windows에서만 실행 가능**
- `chatbot_meg.py`, `rag_engine.py`, `vector_store.py`, `table_parser.py`는 크로스플랫폼 동작

### LLM / Ollama
- 로컬에 Ollama 서버가 `http://localhost:11434`에서 실행 중이어야 함
- 사용 모델은 사전에 `ollama pull <모델명>` 으로 설치 필요
- ChromaDB는 `data/chroma_db/<임베딩모델명>/` 에 모델별로 저장됨

### 데이터 파일
- `data/result/final_text_data_*.xlsx` 없으면 앱 에러 → `table_parser.py` 실행 필요
- `data/chroma_db/` 없으면 앱 에러 → `table_parser.py` 또는 `vector_store.py` 실행 필요
- 원본 데이터 변경 시: `table_parser.py` 실행 (질문에서 y/y 선택)

### git 제외 항목 (.gitignore)
```
data/chroma_db/
data/raw_data/
data/converted_csv/
data/result/
```

---

## 실행 방법

### 1. 모델 설치 (최초 1회)
```bash
ollama pull qwen3:14b
ollama pull qwen3:8b
ollama pull qwen3-embedding:4b
ollama pull gemma2           # 조합A 비교용
ollama pull gemma4:e4b       # 조합B 비교용
```

### 2. 전처리 + LLM 변환 + ChromaDB 구축 (데이터 변경 시마다)
```bash
python src/table_parser.py
# 실행 직후 두 가지 질문에 답하면 이후 자동 진행
```

### 3. 전처리만 단독 실행 (필요 시)
```bash
python src/preprocess_meg.py  # Windows 전용
```

### 4. 임베딩 모델 변경 후 ChromaDB만 재구축 (필요 시)
```bash
# vector_store.py 상단 EMBEDDING_MODEL 변경 후
python src/vector_store.py
```

### 5. 챗봇 앱 실행
```bash
streamlit run src/chatbot_meg.py
```

---

## 향후 개선 예정 사항

- `Reason` 컬럼 데이터 보강 후 프롬프트에 설계 근거 포함
- 비밀번호 하드코딩 제거 (환경변수로 교체)
- `preprocess_meg.py` Linux/Mac 호환 버전 작성 (win32com 제거)
