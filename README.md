# MEG_ChatBot

SEC MEG(기구 설계) 표준 체크리스트를 기반으로 한 **AI 설계 어시스턴트 챗봇**.
설계 항목을 자연어로 질문하면 RAG(검색 증강 생성) 방식으로 관련 설계 표준 가이드를 검색하여 전문가 어투로 답변합니다.

---

## 주요 기능

- **자연어 설계 질의응답** — 설계 항목·치수·조건을 자연어로 질문
- **RAG 기반 검색** — ChromaDB 벡터 검색으로 관련 표준 가이드 추출
- **Query Expansion** — 방향어(상/하/좌/우/전/후), 단위, 유의어 자동 보강으로 검색 정확도 향상
- **터미널 테스트 모드** — UI 없이 `python src/rag_engine.py`로 RAG 성능 직접 확인
- **UI/RAG 분리 구조** — `chatbot_meg.py`(UI)와 `rag_engine.py`(RAG)를 독립적으로 수정·협업 가능
- **비밀번호 인증** — Streamlit 세션 기반 접근 제어

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
- RAG 테스트 및 챗봇 실행: 크로스플랫폼 가능

---

## 설치 및 실행

### 1. 의존성 설치

```bash
pip install streamlit pandas openpyxl langchain langchain-community langchain-ollama chromadb tqdm requests
```

### 2. Ollama 설치 및 모델 준비

```bash
ollama pull gemma2
ollama serve  # 서버 실행 (http://localhost:11434)
```

### 3. 데이터 전처리 (최초 1회, Windows)

원본 Excel 체크리스트 파일을 `data/raw_data/` 폴더에 위치시킨 후:

```bash
# Step 1: Excel → CSV 변환 및 데이터 추출
python src/preprocess_meg.py

# Step 2: 정제 데이터 → LLM 마크다운 변환
python src/table_parser.py
```

### 4. RAG 성능 터미널 테스트

```bash
python src/rag_engine.py
```

```
Ollama 연결 확인 중...
✅ Ollama 연결 확인
지식 베이스 구축 중...
✅ 준비 완료. 질문을 입력하세요. (종료: q)

질문 > 나사 체결 토크 기준이 뭐야?
──────────────────────────────────────────────────
확인된 설계 표준 가이드는 다음과 같습니다. ...
──────────────────────────────────────────────────
```

### 5. 챗봇 앱 실행

```bash
streamlit run src/chatbot_meg.py
```

브라우저에서 `http://localhost:8501` 접속 후 비밀번호 입력.

---

## 데이터 파이프라인

```
data/raw_data/ (원본 Excel)
    └─► preprocess_meg.py
            ├─ Excel → CSV 변환 (win32com, Windows 전용)
            ├─ No / Title / Item / Guide 컬럼 추출
            └─ Title 정제 (숫자 인덱스·특수문자 제거)
                    │
            semi:  No, Title, Item, Guide, Reason
            final: Title(정제됨), Item, Guide, Reason
                    │
    └─► table_parser.py
            └─ gemma2 LLM으로 마크다운 서술형 변환 (500행 단위)
                    │
            data/result/final_text_data_*.xlsx
                    │
    └─► rag_engine.py
            ├─ OllamaEmbeddings → ChromaDB 인덱싱
            └─ Query Expansion → 벡터 검색 → LLM 답변
                    │
    └─► chatbot_meg.py (Streamlit UI)
```

---

## 디렉토리 구조

```
MEG_ChatBot/
├── data/
│   ├── raw_data/       ← 원본 Excel 파일을 여기에 위치
│   ├── converted_csv/  ← 변환된 CSV 파일
│   ├── error/          ← 단계별 에러 로그
│   └── result/         ← 전처리 결과 및 최종 지식베이스
│       └── final_text_data_*.xlsx
└── src/
    ├── chatbot_meg.py  ← Streamlit UI (streamlit run)
    ├── rag_engine.py   ← RAG 엔진 (python으로 터미널 테스트 가능)
    ├── preprocess_meg.py
    └── table_parser.py
```

---

## 답변 방식

LLM은 검색 결과에 따라 3단계로 답변합니다:

1. **표준 확인** — 관련 데이터가 충분할 때: *"확인된 설계 표준 가이드는 다음과 같습니다."*
2. **유사 사례** — 완전 일치하지 않을 때: *"정확한 표준은 확인되지 않지만, 가장 유사한 사례를 기반으로 안내해 드립니다."*
3. **재질문 요청** — 관련 데이터 없을 때

수치(mm, T 등)와 설계 조건은 반드시 포함되며, 구어체로 자연스럽게 서술됩니다.
