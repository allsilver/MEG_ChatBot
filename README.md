# MEG_ChatBot

SEC MEG(기구 설계) 표준 체크리스트를 기반으로 한 **AI 설계 어시스턴트 챗봇**.  
설계 항목을 자연어로 질문하면 RAG(검색 증강 생성) 방식으로 관련 설계 표준 가이드를 검색하여 전문가 어투로 답변합니다.

---

## 주요 기능

- **자연어 설계 질의응답** — 설계 항목·치수·조건을 자연어로 질문
- **RAG 기반 검색** — ChromaDB 벡터 검색으로 관련 표준 가이드 추출
- **Query Expansion** — 방향어(상/하/좌/우/전/후), 단위, 유의어 자동 보강으로 검색 정확도 향상
- **비밀번호 인증** — Streamlit 세션 기반 접근 제어
- **대화 기록 관리** — 사이드바에서 초기화 가능

---

## 기술 스택

| 분류 | 기술 |
|------|------|
| UI | Streamlit |
| LLM | Ollama (gemma2) |
| 임베딩 | OllamaEmbeddings (gemma2) |
| 벡터 DB | ChromaDB |
| LLM 프레임워크 | LangChain |
| 데이터 처리 | pandas, openpyxl |
| Excel 자동화 | win32com (전처리 단계, Windows 전용) |

---

## 시스템 요구사항

- Python 3.9+
- [Ollama](https://ollama.ai) 설치 및 `gemma2` 모델 pull
- 전처리 단계: Windows 환경 필요 (win32com 사용)
- 챗봇 실행: 크로스플랫폼 가능

---

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install streamlit pandas openpyxl langchain langchain-community langchain-ollama chromadb tqdm
```

### 2. Ollama 설치 및 모델 준비

```bash
# Ollama 설치 후
ollama pull gemma2
ollama serve  # 서버 실행 (http://localhost:11434)
```

### 3. 데이터 전처리 (최초 1회, Windows)

원본 Excel 체크리스트 파일을 `src/preprocess/data/` 폴더에 위치시킨 후:

```bash
# Step 1: Excel → CSV 변환 및 데이터 추출
python src/preprocess_meg.py

# Step 2: 정제 데이터 → LLM 마크다운 변환
python src/table_parser.py
```

### 4. 챗봇 앱 실행

```bash
streamlit run src/chatbot.py
```

브라우저에서 `http://localhost:8501` 접속 후 비밀번호 입력.

---

## 데이터 파이프라인

```
원본 Excel 체크리스트
    └─► preprocess_meg.py
            ├─ Excel → CSV 변환 (win32com)
            ├─ NO / ITEM / GUIDE 컬럼 추출
            └─ Title 정제 (숫자 인덱스·특수문자 제거)
                    │
                    ▼
        preprocessed_data_final.xlsx
                    │
    └─► table_parser.py
            └─ gemma2 LLM으로 마크다운 서술형 텍스트 변환
               (500행 단위 청크 분할 저장)
                    │
                    ▼
        final_text_data_1.xlsx, final_text_data_2.xlsx, ...
                    │
    └─► chatbot.py (앱 구동 시 자동 실행)
            ├─ OllamaEmbeddings → ChromaDB 인덱싱
            └─ 질문 → Query Expansion → 벡터 검색 → LLM 답변
```

---

## 디렉토리 구조

```
MEG_ChatBot/
├── src/
│   ├── chatbot.py              # 메인 Streamlit 챗봇 앱
│   ├── preprocess_meg.py       # 데이터 전처리 스크립트 (Windows 전용)
│   └── table_parser.py         # LLM 마크다운 텍스트 변환 스크립트
│
└── src/preprocess/             # 전처리 작업 폴더 (런타임 생성)
    ├── data/                   # ← 원본 Excel 파일을 여기에 위치
    ├── converted_csv/          # 변환된 CSV 파일
    └── result/                 # 전처리 결과물
        └── final_text_data_*.xlsx  # 챗봇이 읽는 최종 지식베이스
```

---

## 답변 방식

LLM은 검색 결과에 따라 3단계로 답변합니다:

1. **표준 확인** — 관련 데이터가 충분할 때: *"확인된 설계 표준 가이드는 다음과 같습니다."*
2. **유사 사례** — 완전 일치하지 않지만 관련 데이터 있을 때: *"정확한 표준은 확인되지 않지만, 가장 유사한 사례를 기반으로 안내해 드립니다."*
3. **재질문 요청** — 관련 데이터 없을 때

수치(mm, T 등)와 설계 조건은 반드시 포함되며, 구어체로 자연스럽게 서술됩니다.
