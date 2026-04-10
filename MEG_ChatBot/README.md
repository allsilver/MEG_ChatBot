# MEG_ChatBot

SEC 기구 설계 표준 체크리스트를 기반으로 한 **AI 설계 어시스턴트 챗봇**.
설계 항목을 자연어로 질문하면 RAG(검색 증강 생성) 방식으로 관련 설계 표준 가이드를 검색하여 핵심 수치 중심으로 답변합니다.
NX 캐드 작업 중 빠르게 설계 표준을 확인하는 용도로 설계되었습니다.

---

## 주요 기능

- **자연어 설계 질의응답** — 설계 항목·치수·조건을 자연어로 질문
- **RAG 기반 검색** — ChromaDB 벡터 검색으로 관련 표준 가이드 추출
- **다중 지식베이스** — 분야별 ChromaDB를 분리 구축, 챗봇에서 복수 선택 검색 가능
- **대화 문맥 유지** — 최근 3턴의 대화 기록을 문맥으로 활용 (후속 질문 지원)
- **스트리밍 출력** — 토큰 생성 즉시 화면에 출력하여 빠른 응답 체감
- **대화 로그 저장** — 질문·답변·타임스탬프를 JSONL 형식으로 누적 저장
- **Thinking 모드 선택** — 사이드바 토글로 빠른 응답 / 정확한 추론 전환
- **비밀번호 인증** — Streamlit 세션 기반 접근 제어
- **대화 기록 초기화** — 사이드바에서 언제든 초기화 가능

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| UI | Streamlit |
| LLM (생성) | Ollama (기본: qwen3:8b) |
| LLM (전처리) | Ollama (기본: qwen3:8b) |
| 임베딩 | OllamaEmbeddings (기본: qwen3-embedding:4b) |
| 벡터 DB | ChromaDB (분야별 분리 구축) |
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
ollama pull qwen3:8b                # 전처리 + 생성 모델 (권장)
ollama pull qwen3:14b               # 전처리 고품질 옵션
ollama pull qwen3-embedding:4b      # 임베딩 모델 (권장)
ollama pull gemma2                  # 대안 모델

ollama serve  # 서버 실행 (http://localhost:11434)
```

### 3. 지식베이스 구성 (최초 1회 또는 데이터 변경 시)

`src/db_registry.json`에서 분야별 DB를 정의합니다.

```json
{
  "mobile": {
    "display_name": "Mobile",
    "description": "SEC Mobile 설계수순서"
  },
  "folderable": {
    "display_name": "폴더블 특화구조",
    "description": "SEC 폴더블 특화구조 설계수순서"
  }
}
```

원본 Excel 파일을 `data/raw_data/<db_key>/` 폴더에 위치시킨 후:

```bash
python src/table_parser.py
```

실행 시 아래 질문에 답하면 이후 자동 진행됩니다.

```
처리할 DB 키를 입력하세요.
  단일: mobile
  복수: mobile,folderable,water_proof
  전체: all
입력 > mobile,folderable

[공통] Thinking 모드를 사용할까요? (y/n) > n
[공통] ChromaDB 를 새로 구축할까요? (y/n) > y
```

DB별로 순차 처리 후 성공/실패 요약이 출력됩니다.

### 4. 챗봇 앱 실행

```bash
streamlit run src/chatbot_meg.py
```

브라우저에서 `http://localhost:8501` 접속 후 비밀번호 입력.
사이드바에서 검색할 지식베이스를 선택(복수 선택 가능)하고 질문을 입력합니다.

---

## 디렉토리 구조

```
MEG_ChatBot/
├── src/
│   ├── chatbot_meg.py          # 메인 Streamlit 챗봇 앱
│   ├── rag_engine.py           # RAG 엔진 — 생성 모델 + 답변 생성
│   ├── vector_store.py         # 임베딩 모델 + ChromaDB 구축/로드
│   ├── preprocess_meg.py       # 데이터 전처리 (Windows 전용)
│   ├── table_parser.py         # 통합 실행 진입점 (전처리 → LLM 변환 → DB 구축)
│   └── db_registry.json        # 분야별 DB 목록 정의
│
└── data/                       # git 제외 폴더
    ├── raw_data/
    │   ├── mobile/             # ← 분야별 원본 Excel 파일
    │   ├── folderable/
    │   ├── water_proof/
    │   ├── wearable/
    │   ├── package/
    │   └── pc/
    ├── converted_csv/          # 변환된 CSV (자동 생성)
    │   └── <db_key>/
    ├── result/                 # 전처리 결과물 (자동 생성)
    │   └── <db_key>/
    │       ├── preprocessed_data_semi.xlsx
    │       ├── preprocessed_data_final.xlsx
    │       └── final_text_data_*.xlsx
    ├── chroma_db/              # ChromaDB (자동 생성)
    │   └── <db_key>/
    │       └── qwen3_embedding_4b/
    └── logs/
        └── chat_log.jsonl      # 대화 로그 (자동 생성)
```

---

## 모델 설정 및 전환

각 파일 상단 설정 블록에서 주석만 변경하면 모델 전환이 가능합니다.

### 생성 모델 (`src/rag_engine.py`)
```python
GENERATOR_MODEL = "qwen3:8b"      # 현재 설정 (권장)
# GENERATOR_MODEL = "gemma2"
# GENERATOR_MODEL = "qwen3:14b"
```

### 임베딩 모델 (`src/vector_store.py`)
```python
EMBEDDING_MODEL = "qwen3-embedding:4b"  # 현재 설정 (권장)
# EMBEDDING_MODEL = "gemma2"
```

### 전처리 LLM (`src/table_parser.py`)
```python
TABLE_PARSER_MODEL = "qwen3:8b"    # 현재 설정 (속도/품질 균형)
# TABLE_PARSER_MODEL = "qwen3:14b" # 고품질 옵션
```

> 임베딩 모델 변경 시 ChromaDB 재구축 필요 → `python src/table_parser.py` (ChromaDB y 선택)
> 생성 모델 변경 시 재구축 불필요 → 앱 재시작만 하면 됨

---

## 데이터 파이프라인

```
원본 Excel (data/raw_data/<db_key>/)
    └─► table_parser.py 실행
            ├─ Excel → CSV 변환 (win32com)
            ├─ No / Title / Item / Guide / Reason 컬럼 추출
            │         → preprocessed_data_semi.xlsx
            ├─ Title 정제 (숫자 인덱스·특수문자 제거)
            │         → preprocessed_data_final.xlsx
            ├─ LLM(TABLE_PARSER_MODEL)으로 자연어 서술형 변환
            │   · 대분류를 텍스트 앞뒤에 반복 삽입 (임베딩 가중치 강화)
            │         → final_text_data_1.xlsx, final_text_data_2.xlsx, ...
            └─ OllamaEmbeddings(EMBEDDING_MODEL) → ChromaDB 구축
                      (data/chroma_db/<db_key>/<모델명>/ 저장)
                              │
    └─► chatbot_meg.py (앱 구동 시)
            ├─ 사이드바: 검색할 DB 멀티셀렉트
            ├─ 선택된 DB들 로드
            ├─ 질문 → 전체 DB 벡터 검색 → 결과 합산 → 중복 제거
            ├─ 대화 히스토리 (최근 3턴) + 검색 결과 → LLM 답변 생성
            ├─ 스트리밍으로 화면 출력
            └─ 질문·답변 → data/logs/chat_log.jsonl 로그 저장
```

---

## 답변 방식 (스타일 C — 케이스 분기)

| 케이스 | 조건 | 답변 형식 |
|---|---|---|
| 1 | 표준이 명확히 검색됨 | `· [항목명] 수치/조건` 형식으로 나열 |
| 2 | 질문이 애매하거나 범위가 넓음 | 관련 항목 목록 나열 후 재질문 |
| 3 | 정확한 표준 없음, 유사 항목 있음 | 없음을 먼저 고지 후 유사 항목 제안 |
| 4 | 완전 무관 | 재질문 요청 |

---

## 대화 로그 활용

`data/logs/chat_log.jsonl`에 저장된 로그는 아래와 같이 읽을 수 있습니다.

```python
import json

with open("data/logs/chat_log.jsonl", encoding="utf-8") as f:
    logs = [json.loads(line) for line in f]

# 예: 가장 많이 질문된 키워드 분석
from collections import Counter
words = [w for log in logs for w in log["question"].split()]
print(Counter(words).most_common(20))
```

---

## 향후 개선 예정 사항

- `Reason` 컬럼 데이터 보강 후 프롬프트에 설계 근거 포함
- 비밀번호 하드코딩 제거 (환경변수로 교체)
- `preprocess_meg.py` Linux/Mac 호환 버전 작성 (win32com 제거)
- 로그 기반 Q&A 데이터 ChromaDB 누적 반영 (2-B 단계)
