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
│   ├── chatbot_meg.py        # 메인 Streamlit 앱
│   ├── rag_engine.py         # 생성 모델 설정 + RAG 답변 생성
│   ├── vector_store.py       # 임베딩 모델 설정 + ChromaDB 구축/로드
│   ├── preprocess_meg.py     # MEG_STANDARD 전용 전처리 (단독 실행 가능)
│   ├── table_parser.py       # 통합 실행 진입점 (전처리 + LLM 변환 + ChromaDB 구축)
│   ├── domain_registry.json  # 분야(도메인) 목록 정의
│   └── prompts/
│       ├── MEG_STANDARD.txt  # 설계수순서 분야 프롬프트
│       ├── DFC.txt           # DFC 분야 프롬프트
│       └── MECHA.txt         # 공정 표준 분야 프롬프트
│
└── data/                     # git 제외 폴더
    ├── MEG_STANDARD/         # 분야별 데이터 루트
    │   ├── db_registry_MEG_STANDARD.json  # 이 분야의 DB 목록 정의
    │   ├── raw_data/
    │   │   └── <db_key>/     # 분야별 원본 Excel 파일 (폴더 계층 구조 허용)
    │   ├── result/           # 전처리 결과물 (자동 생성)
    │   │   └── <db_key>/
    │   │       ├── preprocessed_data_final.xlsx
    │   │       ├── footnote_review.xlsx   # 주석 제거 검토 파일
    │   │       └── final_text_data_*.xlsx
    │   ├── chroma_db/        # ChromaDB (자동 생성)
    │   │   └── <db_key>/
    │   │       └── qwen3_embedding_4b/
    │   └── error/            # 전처리 에러 로그 (자동 생성)
    ├── DFC/
    │   ├── db_registry_DFC.json
    │   └── raw_data/ ...
    ├── MECHA/
    │   ├── db_registry_MECHA.json
    │   └── raw_data/ ...
    └── logs/
        └── chat_log.jsonl    # 대화 로그 (자동 생성, JSONL 형식)
```

---

## 설정 파일 구조

### `src/domain_registry.json`

분야(도메인) 목록을 정의하는 파일. **분야 추가·삭제·수정 시 이 파일만 수정하면 됨.**
`db_keys` 필드는 사용하지 않음 — DB 목록은 `db_registry_<DOMAIN_KEY>.json`이 단일 진실 공급원.

```json
{
  "MEG_STANDARD": {
    "display_name": "설계수순서",
    "description": "기구 설계 표준 체크리스트 검색",
    "model": "qwen3:8b",
    "prompt_file": "MEG_STANDARD.txt",
    "allow_think_toggle": false,
    "default_use_think": false
  },
  "DFC": {
    "display_name": "DFC",
    "description": "Design For Cost 가이드라인",
    "model": "qwen3:14b",
    "prompt_file": "DFC.txt",
    "allow_think_toggle": true,
    "default_use_think": true
  },
  "MECHA": {
    "display_name": "공정 표준",
    "description": "공정 설계 표준 검색",
    "model": "qwen3:8b",
    "prompt_file": "MECHA.txt",
    "allow_think_toggle": false,
    "default_use_think": false
  }
}
```

| 필드 | 설명 |
|---|---|
| `display_name` | 챗봇 UI에 표시되는 분야 이름 |
| `model` | 이 분야에서 사용할 Ollama 생성 모델 |
| `prompt_file` | `src/prompts/` 폴더 내 프롬프트 파일명 |
| `allow_think_toggle` | 사이드바에 Thinking 모드 토글 표시 여부 |
| `default_use_think` | Thinking 모드 기본값 |

### `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json`

해당 분야의 DB 목록 및 상세 정보. **DB 추가·삭제 시 이 파일만 수정하면 됨.**
파일명 형식: `db_registry_MEG_STANDARD.json`, `db_registry_DFC.json` 등.

```json
{
  "mobile": {
    "display_name": "Mobile",
    "description": "SEC Mobile 설계수순서"
  },
  "foldable": {
    "display_name": "폴더블 특화구조",
    "description": "SEC 폴더블 특화구조 설계수순서"
  }
}
```

- 키 이름은 폴더명이 되므로 **영문 소문자 + 언더스코어**만 사용
- `domain_registry.json`에 `db_keys` 없이 이 파일만으로 DB 목록 관리

### `src/prompts/<DOMAIN_KEY>.txt`

분야별 LLM 프롬프트 파일. `{chat_history}`, `{context}`, `{question}` 세 변수를 반드시 포함해야 함.

---

## 데이터 처리 파이프라인

```
[원본 Excel] (data/<DOMAIN_KEY>/raw_data/<db_key>/ — 폴더 계층 구조 허용)
        ↓  preprocess_meg.py 실행 (단독 실행 가능)
  xlsx 직접 읽기 (openpyxl, 첫 번째 시트만)
  No / Title / Item / Guide 컬럼 추출
  · Title = db_key 하위 폴더 계층 + 파일명 ("A > B > C" 형식)
  · Guide 서브헤더 감지 → "서브헤더 : 값" 형태로 조합
  · Guide 실제 값 2개 → " : " 연결 / 3개 이상 → ", " 연결
  · Item/Guide 주석 번호 자동 제거 (검토 파일 별도 생성)
  · 순수 숫자 No → 에러 로그 기록
        ↓
  preprocessed_data_final.xlsx (data/<DOMAIN_KEY>/result/<db_key>/)
  footnote_review.xlsx (주석 제거 검토용, 필요 시 수동 수정)
        ↓  table_parser.py 실행
  preprocessed_data_final.xlsx 존재 시 → 전처리 스킵, 바로 LLM 변환
  존재하지 않으면 → 도메인에 맞는 전처리 모듈 자동 실행
        ↓
  LLM(TABLE_PARSER_MODEL)으로 자연어 서술형 변환
  · "[Title] {변환 텍스트} (분류: Title)" 형태로 계층 정보 포함
  · 500행 단위 청크 분할 저장
        ↓
  final_text_data_1.xlsx ... (data/<DOMAIN_KEY>/result/<db_key>/)
        ↓
  OllamaEmbeddings(EMBEDDING_MODEL) → ChromaDB 구축
  (data/<DOMAIN_KEY>/chroma_db/<db_key>/<모델명>/ 저장)
        ↓  chatbot_meg.py 앱 구동 시
  사이드바: 분야 선택 → db_registry_<DOMAIN>.json 에서 DB 목록 로드
  선택된 DB들 로드 → 질문 → 전체 DB 벡터 검색 → 합산·중복제거
  대화 히스토리(최근 3턴) + 검색 결과 → LLM 답변 스트리밍 출력
  질문·답변 → data/logs/chat_log.jsonl 로그 저장
```

---

## 각 파일 상세

### `src/chatbot_meg.py`

- **UI**: Streamlit
- **인증**: `check_password()` — 세션 기반 비밀번호 인증
- **사이드바**:
  - 분야 선택 셀렉트박스 (`domain_registry.json` 기반 동적 생성)
  - 지식베이스 멀티셀렉트 (`db_registry_<DOMAIN>.json` 기반, `db_keys` 미사용)
  - Thinking 모드 토글 (`allow_think_toggle: true` 분야에서만 표시)
  - 대화 기록 초기화 버튼
- **Registry 로드**:
  - `load_domain_registry()` — `src/domain_registry.json` 로드
  - `load_db_registry(domain_key)` — `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json` 로드
  - `available_db_keys = list(db_registry.keys())` — `db_keys` 대신 db_registry 키 직접 사용
- **지식베이스 로드**: `load_knowledge_base()` — `@st.cache_resource`로 캐싱
- **답변 출력**: `st.write_stream()` — 토큰 생성 즉시 스트리밍 출력
- **로그 저장**: `save_log()` — `data/logs/chat_log.jsonl`에 JSONL 누적 저장

---

### `src/rag_engine.py`

- **역할**: 생성 모델 설정 + RAG 답변 생성 전담
- **모델 설정 블록** (파일 상단)
  ```python
  CHAT_HISTORY_TURNS = 3
  ```
- **`setup_design_bot(vector_dbs, domain_config, use_think)`**: RAG 핸들러 반환

---

### `src/vector_store.py`

- **역할**: 임베딩 모델 설정 + ChromaDB 구축/로드 전담
- **모델 설정 블록** (파일 상단)
  ```python
  EMBEDDING_MODEL = "qwen3-embedding:4b"
  ```
- **단독 실행 시**: `db_registry_<DOMAIN>.json` 직접 읽어 DB 목록 구성 (`db_keys` 미사용)

---

### `src/preprocess_meg.py`

- **MEG_STANDARD 전용** 전처리 모듈 (도메인 고정)
- **플랫폼**: 크로스플랫폼 (openpyxl 사용, win32com 제거)
- **단독 실행 가능**: `python src/preprocess_meg.py` → DB 키 입력 → `preprocessed_data_final.xlsx` 생성
- **주요 함수**:
  - `build_title(file_path, raw_data_folder)` — 폴더 계층 → `"A > B > C"` 형식 Title 생성
  - `extract_from_xlsx(file_path, title)` — xlsx 첫 번째 시트에서 데이터 추출
  - `process_and_save_checklists(domain_data_root, db_key)` — 전체 처리 및 저장
  - `run_preprocess(domain_data_root, db_key)` — table_parser.py 호출용 진입점
- **Guide 조합 규칙**:
  - 서브헤더 있음 → `"서브헤더 : 값"` 형태, 값 하나뿐이면 값만
  - 실제 값 2개 → `"값1 : 값2"`
  - 실제 값 1개 또는 3개 이상 → `"값1, 값2, ..."`
- **No 컬럼 규칙**:
  - 알파벳 기반(5자 이내, 공백·하이픈·숫자 조합 허용): 유효
  - No=None이어도 Guide에 값 있으면 이전 No/Item 유지하며 별도 행 저장
  - 순수 숫자: 에러 로그(`numeric_no_detected`) 기록
  - 공백·문장·알 수 없는 값 연속 3회: 표 종료로 판단
- **주석 제거**: Item/Guide에서 `(1)`, `1)` 형태의 순수 정수 주석 번호 자동 제거
  - 제거된 항목은 `footnote_review.xlsx`에 별도 기록
- **DB 목록**: `db_registry_MEG_STANDARD.json` 직접 읽기 (`db_keys` 미사용)

---

### `src/table_parser.py`

- **통합 실행 진입점** — 전처리 → LLM 변환 → ChromaDB 구축 일괄 처리
- **모델 설정 블록** (파일 상단)
  ```python
  TABLE_PARSER_MODEL = "qwen3:8b"
  ```
- **도메인별 전처리 모듈 매핑** (`PREPROCESS_MODULE_MAP`):
  ```python
  PREPROCESS_MODULE_MAP = {
      "MEG_STANDARD": "preprocess_meg",
      # "DFC":    "preprocess_dfc",    # 추후 추가
      # "MECHA":  "preprocess_mecha",  # 추후 추가
  }
  ```
- **실행 시 순서**:
  1. 도메인 키 입력
  2. `db_registry_<DOMAIN>.json` 직접 읽어 DB 목록 구성
  3. 처리할 DB 키 입력
  4. Thinking 모드, ChromaDB 재구축 여부 선택
  5. 이후 자동 순차 실행
- **전처리 스킵 조건**: `preprocessed_data_final.xlsx`가 이미 있으면 스킵 → 바로 LLM 변환
- **LLM 프롬프트**: `분류 계층` 변수로 계층 Title을 자연어로 풀어쓰도록 유도
- **DB 목록**: `db_registry_<DOMAIN>.json` 직접 읽기 (`db_keys` 미사용)

---

## 모델 설정 요약

| 파일 | 설정 위치 | 현재 기본값 | 변경 시 ChromaDB 재구축 |
|---|---|---|---|
| `table_parser.py` | 파일 상단 `TABLE_PARSER_MODEL` | `qwen3:8b` | 필요 |
| `vector_store.py` | 파일 상단 `EMBEDDING_MODEL` | `qwen3-embedding:4b` | 필요 |
| `rag_engine.py` | `domain_registry.json`의 `model` 필드 | 분야별 상이 | 불필요 |
| `rag_engine.py` | 파일 상단 `CHAT_HISTORY_TURNS` | `3` | 불필요 |

---

## 개발 시 주의사항

### DB 목록 관리 (단일 진실 공급원)
- DB 목록은 `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json` **한 곳에서만** 관리
- `domain_registry.json`에 `db_keys` 필드 **없음** — 과거 버전과 혼동 주의
- 새 DB 추가 시: `db_registry_<DOMAIN>.json`에만 추가하면 모든 코드에 자동 반영

### 전처리 실행 순서
```
# 1단계: 전처리만 먼저 (선택적)
python src/preprocess_meg.py

# 2단계: LLM 변환 + ChromaDB 구축
python src/table_parser.py
# → preprocessed_data_final.xlsx 있으면 전처리 자동 스킵
```

### 보안
- `chatbot_meg.py` — 비밀번호가 소스코드에 하드코딩되어 있음
  → 환경변수 또는 외부 시크릿 관리로 교체 필요

### LLM / Ollama
- 로컬에 Ollama 서버가 `http://localhost:11434`에서 실행 중이어야 함
- 사용 모델은 사전에 `ollama pull <모델명>`으로 설치 필요

### 데이터 파일
- `preprocessed_data_final.xlsx` 없으면 → `preprocess_meg.py` 또는 `table_parser.py` 실행
- `final_text_data_*.xlsx` 없으면 → `table_parser.py` 실행
- `chroma_db/` 없으면 → `table_parser.py` 또는 `vector_store.py` 실행
- 원본 데이터 변경 시: `preprocessed_data_final.xlsx` 삭제 후 재실행

### 새 도메인 전처리 추가 시
1. `preprocess_<DOMAIN_KEY>.py` 작성 (`run_preprocess` 함수 인터페이스 준수)
2. `table_parser.py`의 `PREPROCESS_MODULE_MAP`에 항목 추가

### git 제외 항목 (.gitignore)
```
data/
```

---

## 실행 방법

### 1. 모델 설치 (최초 1회)
```bash
ollama pull qwen3:8b
ollama pull qwen3:14b
ollama pull qwen3-embedding:4b
```

### 2. 전처리 (단독 실행)
```bash
python src/preprocess_meg.py
# DB 키 입력 후 자동 실행
# → preprocessed_data_final.xlsx 생성
```

### 3. LLM 변환 + ChromaDB 구축
```bash
python src/table_parser.py
# 도메인 키 입력
# DB 키 입력
# Thinking 모드, ChromaDB 재구축 여부 선택 후 자동 진행
```

### 4. ChromaDB만 재구축 (임베딩 모델 변경 시)
```bash
python src/vector_store.py
```

### 5. 챗봇 앱 실행
```bash
streamlit run src/chatbot_meg.py
```

---

## 새 분야(도메인) 추가 방법

1. `src/domain_registry.json`에 새 분야 항목 추가 (`db_keys` 없이)
2. `src/prompts/<DOMAIN_KEY>.txt` 프롬프트 파일 작성
3. `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json` 생성
4. `src/preprocess_<DOMAIN_KEY>.py` 작성 (`run_preprocess` 인터페이스 준수)
5. `table_parser.py`의 `PREPROCESS_MODULE_MAP`에 추가
6. `data/<DOMAIN_KEY>/raw_data/<db_key>/`에 Excel 파일 배치
7. `python src/table_parser.py` 실행

## 새 DB 추가 방법 (기존 분야에)

1. `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json`에 새 DB 항목 추가
2. `data/<DOMAIN_KEY>/raw_data/<db_key>/`에 Excel 파일 배치
3. `python src/preprocess_meg.py` 또는 `python src/table_parser.py` 실행

---

## 향후 개선 예정 사항

- `Reason` 컬럼 데이터 보강 후 프롬프트에 설계 근거 포함
- 비밀번호 하드코딩 제거 (환경변수로 교체)
- DFC, MECHA 전용 전처리 모듈 작성 (`preprocess_dfc.py`, `preprocess_mecha.py`)
- 로그 기반 Q&A 데이터 ChromaDB 누적 반영 (2-B 단계)
