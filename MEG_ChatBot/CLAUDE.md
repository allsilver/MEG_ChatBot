# CLAUDE.md — MEG_ChatBot 개발 가이드

## 프로젝트 개요

SEC 기구 설계 표준 체크리스트를 기반으로 한 **RAG(검색 증강 생성) 설계 어시스턴트 챗봇**.
NX 캐드 작업 중인 설계자가 자연어로 설계 항목을 질문하면, 분야별로 분리 구축된 지식 베이스에서 관련 표준을 검색하여 핵심 수치 중심으로 답변한다.

---

## 디렉토리 구조

```
MEG_ChatBot/
├── .gitignore
├── src/
│   ├── chatbot_meg.py      # 메인 Streamlit 앱
│   ├── rag_engine.py       # 생성 모델 설정 + RAG 답변 생성
│   ├── vector_store.py     # 임베딩 모델 설정 + ChromaDB 구축/로드
│   ├── preprocess_meg.py   # 원본 Excel → 정제 데이터 전처리 (Windows 전용)
│   ├── table_parser.py     # 통합 실행 진입점 (전처리 + LLM 변환 + ChromaDB 구축)
│   └── db_registry.json    # 분야별 DB 목록 정의
│
└── data/                   # git 제외 폴더
    ├── raw_data/
    │   └── <db_key>/       # 분야별 원본 Excel 파일
    ├── converted_csv/
    │   └── <db_key>/       # Excel → CSV 변환 결과 (자동 생성)
    ├── result/
    │   └── <db_key>/       # 전처리 결과 xlsx (자동 생성)
    ├── chroma_db/
    │   └── <db_key>/       # ChromaDB (임베딩 모델명 하위 폴더, 자동 생성)
    │       └── qwen3_embedding_4b/
    └── logs/
        └── chat_log.jsonl  # 대화 로그 (자동 생성, JSONL 형식)
```

---

## 데이터 처리 파이프라인

```
[원본 Excel] (data/raw_data/<db_key>/)
        ↓  table_parser.py 실행 — db_key 지정
  Excel → win32com → CSV (data/converted_csv/<db_key>/)
  No / Title / Item / Guide / Reason 컬럼 추출
        ↓
  preprocessed_data_semi.xlsx (data/result/<db_key>/)
        ↓
  Title 정제 (숫자 인덱스·특수문자 제거, 2D/2.5D/3D 예외 보호)
        ↓
  preprocessed_data_final.xlsx (data/result/<db_key>/)
        ↓
  LLM(TABLE_PARSER_MODEL)으로 자연어 서술형 변환
  · 대분류를 텍스트 앞뒤 반복 삽입: "[Title] {변환 텍스트} (분류: Title)"
  · 500행 단위 청크 분할 저장
        ↓
  final_text_data_1.xlsx, final_text_data_2.xlsx ... (data/result/<db_key>/)
        ↓
  OllamaEmbeddings(EMBEDDING_MODEL) → ChromaDB 구축
  (data/chroma_db/<db_key>/<모델명>/ 저장)
        ↓  chatbot_meg.py 앱 구동 시
  사이드바에서 검색할 DB 멀티셀렉트
  선택된 DB들 로드 → 질문 → 전체 DB 벡터 검색 → 합산·중복제거
  대화 히스토리(최근 3턴) + 검색 결과 → LLM 답변 스트리밍 출력
  질문·답변 → data/logs/chat_log.jsonl 로그 저장
```

---

## 각 파일 상세

### `src/db_registry.json`

분야별 DB 목록을 정의하는 설정 파일. **새 DB 추가 시 이 파일만 수정하면 됨.**

```json
{
  "mobile":      { "display_name": "Mobile",        "description": "SEC Mobile 설계수순서" },
  "folderable":  { "display_name": "폴더블 특화구조", "description": "SEC 폴더블 특화구조 설계수순서" },
  "water_proof": { "display_name": "방수 특화구조",   "description": "SEC 방수 특화구조 설계수순서" },
  "wearable":    { "display_name": "응용제품 특화구조","description": "SEC 응용제품 특화구조 설계수순서" },
  "package":     { "display_name": "패키지 특화구조", "description": "SEC 패키지 특화구조 설계수순서" },
  "pc":          { "display_name": "PC 설계 특화구조","description": "SEC PC 설계 특화구조 설계수순서" }
}
```

- 키 이름은 폴더명이 되므로 **영문 소문자 + 언더스코어**만 사용
- 추가 후 해당 `data/raw_data/<db_key>/` 폴더에 Excel 배치 → `table_parser.py` 실행

---

### `src/chatbot_meg.py`

- **UI**: Streamlit
- **인증**: `check_password()` — 세션 기반 비밀번호 인증
- **사이드바**:
  - 지식베이스 멀티셀렉트 (db_registry.json 기반 동적 생성)
  - Thinking 모드 토글
  - 대화 기록 초기화 버튼
- **지식베이스 로드**: `load_knowledge_base()` — `@st.cache_resource`로 캐싱
  - 선택된 DB 키 조합 또는 모드가 바뀌면 자동 재초기화
- **답변 출력**: `st.write_stream()` — 토큰 생성 즉시 스트리밍 출력
- **대화 히스토리**: `st.session_state.messages[:-1]`를 `chat_history`로 전달
- **로그 저장**: `save_log()` — `data/logs/chat_log.jsonl`에 JSONL 누적 저장
  - 저장 실패 시에도 챗봇 동작 유지 (try-except로 보호)

---

### `src/rag_engine.py`

- **역할**: 생성 모델 설정 + RAG 답변 생성 전담
- **모델 설정 블록** (파일 상단)
  ```python
  GENERATOR_MODEL    = "qwen3:8b"
  CHAT_HISTORY_TURNS = 3          # 문맥으로 포함할 최근 턴 수
  ```
- **`_search_docs(vector_dbs, query)`**: 모든 DB에서 검색 후 중복 제거
  - k=10, score > 0.2 필터링
  - 결과 없을 시 상위 1개 강제 포함
- **`_format_history(chat_history)`**: 최근 N턴을 문자열로 변환
- **`setup_design_bot(vector_dbs, use_think)`**: RAG 핸들러 반환
  - `vector_dbs`: `dict[str, Chroma]` — 단일 Chroma도 하위 호환 수용
  - `rag_handler(query, chat_history)`: 완성 문자열 반환 (터미널 테스트용)
  - `rag_handler.stream(query, chat_history)`: 스트리밍 제너레이터 (챗봇 UI용)
  - `/no_think` 프롬프트 접두사로 qwen3 thinking 모드 제어

**LLM 프롬프트 답변 규칙 (스타일 C — 케이스 분기형)**
- 케이스 1: 표준 명확 → `· [항목명] 수치/조건` 형식 나열
- 케이스 2: 질문 애매 → 관련 항목 목록 나열 + 재질문
- 케이스 3: 정확한 표준 없음 → 없음 고지 후 유사 항목 제안
- 케이스 4: 완전 무관 → 재질문 요청

---

### `src/vector_store.py`

- **역할**: 임베딩 모델 설정 + ChromaDB 구축/로드 전담
- **모델 설정 블록** (파일 상단)
  ```python
  EMBEDDING_MODEL = "qwen3-embedding:4b"
  ```
- **`_get_persist_dir(db_key)`**: db_key에 해당하는 ChromaDB 경로 반환
- **`prepare_knowledge_base(db_key)`**: ChromaDB 신규 구축
  - `data/result/<db_key>/final_text_data_*.xlsx` 읽어서 벡터화
  - `data/chroma_db/<db_key>/<모델명>/`에 저장
- **`load_vector_db(db_key)`**: ChromaDB 로드
- **`load_multiple_vector_dbs(db_keys)`**: 복수 DB 로드 → dict 반환
  - 로드 실패한 DB는 경고 출력 후 건너뜀
- **단독 실행** (`python src/vector_store.py`): 특정 DB의 ChromaDB만 재구축

---

### `src/preprocess_meg.py`

- **플랫폼**: Windows 전용 (`win32com.client` 사용)
- **`convert_all_excel_to_csv(data_root, db_key)`**: `data/raw_data/<db_key>/` → CSV 변환
  - 제외 키워드 필터: `OLD`, `old`, `삭제`
  - 경로 길이 218자 초과 시 스킵
- **`process_and_save_checklists(data_root, db_key, csv_folder)`**: CSV → semi xlsx
  - NO 컬럼이 단일 알파벳(A~Z)인 행만 유효 데이터로 처리
- **`run_2nd_preprocessing(data_root, db_key, input_file_name)`**: Title 컬럼 정제
  - 앞 숫자 인덱스 제거, 괄호·특수기호 → 공백
  - 2D/2.5D/3D 예외 보호

---

### `src/table_parser.py`

- **통합 실행 진입점** — 전처리 → LLM 변환 → ChromaDB 구축까지 일괄 처리
- **모델 설정 블록** (파일 상단)
  ```python
  TABLE_PARSER_MODEL = "qwen3:8b"
  ```
- **다중 DB 순차 처리**: 쉼표 구분 또는 `all` 입력으로 여러 DB를 한 번에 처리
  ```
  입력 > mobile,folderable,water_proof   또는   all
  ```
- **실행 전 공통 질문** (한 번만 입력):
  - Thinking 모드 여부
  - ChromaDB 재구축 여부
- **전처리 스킵 조건**: `preprocessed_data_final.xlsx`가 이미 있으면 자동 스킵
  - 강제 재전처리가 필요하면 해당 파일을 직접 삭제 후 실행
- **`transform_to_natural_text(db_key, use_think)`**: LLM 자연어 변환
  - `/no_think` 접두사로 thinking 모드 제어
  - 대분류 텍스트 앞뒤 반복: `[Title] {변환 텍스트} (분류: Title)`
  - LLM 실패 시 원본 텍스트로 폴백
- **`run_single_db(...)`**: 단일 DB 처리 함수 (다중 처리 루프에서 호출)
- 처리 완료 후 성공/실패 DB 목록 요약 출력

---

## 모델 설정 요약

| 파일 | 설정 상수 | 현재 값 | 변경 시 ChromaDB 재구축 |
|---|---|---|---|
| `table_parser.py` | `TABLE_PARSER_MODEL` | `qwen3:8b` | 필요 (데이터 재생성) |
| `vector_store.py` | `EMBEDDING_MODEL` | `qwen3-embedding:4b` | 필요 |
| `rag_engine.py` | `GENERATOR_MODEL` | `qwen3:8b` | 불필요 |
| `rag_engine.py` | `CHAT_HISTORY_TURNS` | `3` | 불필요 |

---

## 개발 시 주의사항

### 보안
- `chatbot_meg.py` — 비밀번호가 소스코드에 하드코딩되어 있음
  → 환경변수 또는 외부 시크릿 관리로 교체 필요

### 플랫폼 의존성
- `preprocess_meg.py`는 `win32com` 사용으로 **Windows에서만 실행 가능**
- 나머지 파일들은 크로스플랫폼 동작

### LLM / Ollama
- 로컬에 Ollama 서버가 `http://localhost:11434`에서 실행 중이어야 함
- 사용 모델은 사전에 `ollama pull <모델명>`으로 설치 필요
- ChromaDB는 `data/chroma_db/<db_key>/<임베딩모델명>/`에 DB별로 저장됨

### 데이터 파일
- `data/result/<db_key>/final_text_data_*.xlsx` 없으면 앱 에러 → `table_parser.py` 실행 필요
- `data/chroma_db/<db_key>/` 없으면 앱 에러 → `table_parser.py` 또는 `vector_store.py` 실행 필요
- 원본 데이터 변경 시: 해당 db_key의 `preprocessed_data_final.xlsx` 삭제 후 `table_parser.py` 실행

### git 제외 항목 (.gitignore)
```
data/chroma_db/
data/raw_data/
data/converted_csv/
data/result/
data/logs/
```

---

## 실행 방법

### 1. 모델 설치 (최초 1회)
```bash
ollama pull qwen3:8b
ollama pull qwen3-embedding:4b
ollama pull qwen3:14b           # 고품질 전처리 옵션
ollama pull gemma2              # 대안 모델
```

### 2. 전처리 + LLM 변환 + ChromaDB 구축
```bash
python src/table_parser.py
# 처리할 DB 키 입력 (단일/복수/all)
# Thinking 모드, ChromaDB 재구축 여부 선택 후 자동 진행
```

### 3. 임베딩 모델 변경 후 ChromaDB만 재구축
```bash
# vector_store.py 상단 EMBEDDING_MODEL 변경 후
python src/vector_store.py
```

### 4. 챗봇 앱 실행
```bash
streamlit run src/chatbot_meg.py
```

---

## 향후 개선 예정 사항

- `Reason` 컬럼 데이터 보강 후 프롬프트에 설계 근거 포함
- 비밀번호 하드코딩 제거 (환경변수로 교체)
- `preprocess_meg.py` Linux/Mac 호환 버전 작성 (win32com 제거)
- 로그 기반 Q&A 데이터 ChromaDB 누적 반영 (2-B 단계)
