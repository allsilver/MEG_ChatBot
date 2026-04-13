# MEG_ChatBot

SEC 기구 설계 표준 체크리스트를 기반으로 한 **AI 설계 어시스턴트 챗봇**.
설계 항목을 자연어로 질문하면 RAG(검색 증강 생성) 방식으로 관련 설계 표준 가이드를 검색하여 핵심 수치 중심으로 답변합니다.
NX 캐드 작업 중 빠르게 설계 표준을 확인하는 용도로 설계되었습니다.

---

## 주요 기능

- **다중 분야 지원** — 설계수순서, DFC, 공정 표준 등 분야별 최적화된 모델·프롬프트 적용
- **자연어 설계 질의응답** — 설계 항목·치수·조건을 자연어로 질문
- **RAG 기반 검색** — ChromaDB 벡터 검색으로 관련 표준 가이드 추출
- **계층형 Title** — 폴더 구조를 `"A > B > C"` 형식으로 Title에 반영하여 검색 정확도 향상
- **다중 지식베이스** — 분야별·DB별 ChromaDB를 분리 구축, 챗봇에서 복수 선택 검색 가능
- **대화 문맥 유지** — 최근 3턴의 대화 기록을 문맥으로 활용 (후속 질문 지원)
- **스트리밍 출력** — 토큰 생성 즉시 화면에 출력하여 빠른 응답 체감
- **대화 로그 저장** — 질문·답변·타임스탬프를 JSONL 형식으로 누적 저장
- **Thinking 모드 선택** — 특정 분야(DFC 등)에서 사이드바 토글로 추론 모드 전환
- **비밀번호 인증** — Streamlit 세션 기반 접근 제어

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| UI | Streamlit |
| LLM (생성) | Ollama — 분야별 모델 상이 (기본: qwen3:8b) |
| LLM (전처리) | Ollama (기본: qwen3:8b) |
| 임베딩 | OllamaEmbeddings (기본: qwen3-embedding:4b) |
| 벡터 DB | ChromaDB (분야별·DB별 분리 구축) |
| LLM 프레임워크 | LangChain |
| 데이터 처리 | pandas, openpyxl |

---

## 시스템 요구사항

- Python 3.9+
- [Ollama](https://ollama.ai) 설치 및 사용 모델 pull
- 전처리·챗봇 실행 모두 크로스플랫폼 가능

---

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install streamlit pandas openpyxl langchain langchain-community langchain-ollama langchain-chroma chromadb tqdm
```

### 2. Ollama 모델 준비

```bash
ollama pull qwen3:8b                # 전처리 + 설계수순서·공정표준 생성 모델
ollama pull qwen3:14b               # DFC 생성 모델
ollama pull qwen3-embedding:4b      # 임베딩 모델

ollama serve  # 서버 실행 (http://localhost:11434)
```

### 3. 설정 파일 구성

**`src/domain_registry.json`** — 분야별 설정 관리 (`db_keys` 없이 사용):

```json
{
  "MEG_STANDARD": {
    "display_name": "설계수순서",
    "model": "qwen3:8b",
    "prompt_file": "MEG_STANDARD.txt",
    "allow_think_toggle": false,
    "default_use_think": false
  }
}
```

**`data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json`** — DB 목록 (단일 진실 공급원):

```json
{
  "mobile": { "display_name": "Mobile", "description": "SEC Mobile 설계수순서" },
  "foldable": { "display_name": "폴더블 특화구조", "description": "..." }
}
```

### 4. 지식베이스 구성

원본 Excel 파일을 `data/<DOMAIN_KEY>/raw_data/<db_key>/` 폴더에 배치 후:

```bash
# 전처리만 먼저 실행 (선택적)
python src/preprocess_meg.py

# LLM 변환 + ChromaDB 구축
python src/table_parser.py
```

```
도메인 키 입력 > MEG_STANDARD
처리할 DB 키를 입력하세요 (단일 입력, 쉼표로 복수 입력, 또는 all)
입력 > all
[공통] Thinking 모드를 사용할까요? (y/n) > n
[공통] ChromaDB 를 새로 구축할까요? (y/n) > y
```

### 5. 챗봇 앱 실행

```bash
streamlit run src/chatbot_meg.py
```

---

## 디렉토리 구조

```
MEG_ChatBot/
├── src/
│   ├── chatbot_meg.py          # 메인 Streamlit 챗봇 앱
│   ├── rag_engine.py           # RAG 엔진 — 생성 모델 + 답변 생성
│   ├── vector_store.py         # 임베딩 모델 + ChromaDB 구축/로드
│   ├── preprocess_meg.py       # MEG_STANDARD 전용 전처리 (단독 실행 가능)
│   ├── table_parser.py         # 통합 실행 진입점
│   ├── domain_registry.json    # 분야(도메인) 목록 정의
│   └── prompts/
│       ├── MEG_STANDARD.txt    # 설계수순서 프롬프트
│       ├── DFC.txt             # DFC 프롬프트
│       └── MECHA.txt           # 공정 표준 프롬프트
│
└── data/                       # git 제외 폴더
    ├── MEG_STANDARD/
    │   ├── db_registry_MEG_STANDARD.json   # DB 목록 (단일 진실 공급원)
    │   ├── raw_data/
    │   │   └── <db_key>/       # 폴더 계층 구조 허용
    │   ├── result/             # 자동 생성
    │   │   └── <db_key>/
    │   │       ├── preprocessed_data_final.xlsx
    │   │       ├── footnote_review.xlsx
    │   │       └── final_text_data_*.xlsx
    │   ├── chroma_db/          # 자동 생성
    │   └── error/              # 자동 생성
    ├── DFC/
    │   ├── db_registry_DFC.json
    │   └── raw_data/
    ├── MECHA/
    │   ├── db_registry_MECHA.json
    │   └── raw_data/
    └── logs/
        └── chat_log.jsonl
```

---

## 데이터 파이프라인

```
원본 Excel (data/<DOMAIN_KEY>/raw_data/<db_key>/ — 폴더 계층 구조 허용)
    └─► preprocess_meg.py 실행 (단독 실행 가능)
            ├─ xlsx 직접 읽기 (openpyxl, 첫 번째 시트만)
            ├─ Title = 폴더 계층 + 파일명 ("A > B > C" 형식)
            ├─ Guide 서브헤더 감지 → "서브헤더 : 값" 형태 조합
            ├─ Guide 실제 값 2개 → " : " / 3개+ → ", "
            ├─ 주석 번호 자동 제거 (footnote_review.xlsx 별도 생성)
            └─ preprocessed_data_final.xlsx 생성
    └─► table_parser.py 실행
            ├─ preprocessed_data_final.xlsx 있으면 → 전처리 스킵
            ├─ 없으면 → 도메인별 전처리 모듈 자동 실행
            ├─ LLM으로 자연어 서술형 변환 (계층 Title 포함)
            │         → final_text_data_*.xlsx
            └─ OllamaEmbeddings → ChromaDB 구축
    └─► chatbot_meg.py (앱 구동 시)
            ├─ db_registry_<DOMAIN>.json 에서 DB 목록 로드
            ├─ 선택된 DB들 로드 → 질문 → 벡터 검색 → 중복 제거
            ├─ 대화 히스토리(최근 3턴) + 검색 결과 → LLM 답변
            └─ 스트리밍 출력 + 로그 저장
```

---

## 분야/DB 추가 방법

### 새 분야 추가

1. `src/domain_registry.json`에 항목 추가 (`db_keys` 없이)
2. `src/prompts/<DOMAIN_KEY>.txt` 프롬프트 작성
3. `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json` 생성
4. `src/preprocess_<DOMAIN_KEY>.py` 작성 (`run_preprocess` 인터페이스 준수)
5. `table_parser.py`의 `PREPROCESS_MODULE_MAP`에 추가
6. `data/<DOMAIN_KEY>/raw_data/<db_key>/`에 Excel 배치
7. `python src/table_parser.py` 실행

### 기존 분야에 DB 추가

1. `data/<DOMAIN_KEY>/db_registry_<DOMAIN_KEY>.json`에 DB 항목 추가
2. `data/<DOMAIN_KEY>/raw_data/<db_key>/`에 Excel 배치
3. `python src/preprocess_meg.py` 또는 `python src/table_parser.py` 실행

---

## 향후 개선 예정 사항

- `Reason` 컬럼 데이터 보강 후 프롬프트에 설계 근거 포함
- 비밀번호 하드코딩 제거 (환경변수로 교체)
- DFC, MECHA 전용 전처리 모듈 작성
- 로그 기반 Q&A 데이터 ChromaDB 누적 반영 (2-B 단계)
