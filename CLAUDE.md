# CLAUDE.md — MEG_ChatBot 개발 가이드

## 프로젝트 개요

SEC MEG(기구 설계) 표준 체크리스트를 기반으로 한 **RAG(검색 증강 생성) 설계 어시스턴트 챗봇**.
설계 담당자가 자연어로 설계 항목을 질문하면, 사전 구축된 지식 베이스에서 관련 표준 가이드를 검색하여 전문가 어투로 답변한다.

---

## 디렉토리 구조

```
MEG_ChatBot/
├── data/                               # 전처리 데이터 폴더 (git 제외)
│   ├── raw_data/                       # 원본 Excel 체크리스트 파일 위치
│   ├── converted_csv/                  # Excel → CSV 변환 결과
│   ├── error/                          # 단계별 에러 로그 (error_log_*.txt)
│   └── result/
│       ├── preprocessed_data_semi.xlsx   # 1차 추출 결과
│       ├── preprocessed_data_final.xlsx  # 2차 정제 완료 결과
│       └── final_text_data_*.xlsx        # LLM 마크다운 변환 결과 (500행 단위 청크)
│
└── src/
    ├── chatbot_meg.py      # 메인 Streamlit 앱 + RAG 챗봇 엔진
    ├── preprocess_meg.py   # 원본 Excel → 정제 데이터 전처리 (Windows 전용)
    └── table_parser.py     # 정제 데이터 → LLM 마크다운 텍스트 변환
```

---

## 데이터 처리 파이프라인

```
[원본 Excel 체크리스트] (data/raw_data/)
        ↓  preprocess_meg.py (1단계)
  Excel → win32com → CSV 변환 (data/converted_csv/)
  NO / ITEM / GUIDE 컬럼 추출
        ↓
  preprocessed_data_semi.xlsx  (data/result/, 1차 중간 저장)
        ↓  preprocess_meg.py (2단계)
  Title 컬럼 정제 (숫자 인덱스·특수문자 제거)
        ↓
  preprocessed_data_final.xlsx  (data/result/)
        ↓  table_parser.py
  Ollama gemma2 LLM으로 마크다운 서술형 텍스트 변환
  (500행 단위 청크 분할 저장)
        ↓
  final_text_data_1.xlsx, final_text_data_2.xlsx, ... (data/result/)
        ↓  chatbot_meg.py (앱 구동 시)
  OllamaEmbeddings → ChromaDB 벡터 인덱싱
        ↓
  RAG 검색 + gemma2 LLM 답변 생성
```

---

## 각 파일 상세

### `src/chatbot_meg.py`

- **UI**: Streamlit (`st.set_page_config`, `st.chat_input` 등)
- **인증**: `check_password()` — 세션 기반 비밀번호 인증
- **지식베이스**: `prepare_knowledge_base(file_pattern)` — `@st.cache_resource`로 캐싱, `data/result/final_text_data_*.xlsx` 로드
- **RAG 엔진**: `setup_design_bot(vector_db)` — ChromaDB retriever + gemma2 LLM
  - `search_type="similarity_score_threshold"`, `k=10`, `score_threshold=0.3`
  - `similarity_search_with_relevance_scores`로 2차 필터링 (`score > 0.2`)
  - 결과 없을 시 상위 1개 강제 포함 (유사 답변 유도)
- **Query Expansion**: `expand_query(query, llm)` — 방향어(상/하/좌/우/전/후), 단위, 유의어 보강
- **Ollama 상태 확인**: `check_ollama()` — `http://localhost:11434` 헬스체크

**LLM 프롬프트 답변 규칙**
1. 밀접한 데이터 → "확인된 설계 표준 가이드는 다음과 같습니다."
2. 유사 데이터 → "정확한 표준은 확인되지 않지만, 가장 유사한 사례를 기반으로 안내해 드립니다."
3. 수치·조건(mm, T 등) 누락 금지
4. 마크다운 기호 노출 금지, 구어체 사용
5. 완전 무관 시 질문 재입력 요청

---

### `src/preprocess_meg.py`

- **플랫폼**: Windows 전용 (`win32com.client` 사용)
- **경로 기준**: `src/preprocess_meg.py` 위치에서 상위 폴더(`project_root`)의 `data/` 사용
- **`convert_all_excel_to_csv(data_root)`**: `data/raw_data/` 하위 모든 `.xlsx`를 COM 자동화로 CSV 변환
  - 파일명에 `[`, `]` 포함 시 `converted_csv/`에 괄호 제거한 이름으로 복사 후 처리, 완료 후 삭제
  - CSV 경로 길이 218자 초과 시 스킵 (`MAX_CSV_PATH_LENGTH` 상수)
  - Excel 초기화 실패 시 최대 3회 재시도
  - 실패 파일 목록 → `data/error/error_log_excel_to_csv_*.txt`
- **`process_and_save_checklists(data_root, csv_folder)`**: CSV에서 헤더 행(`NO`, `ITEM`, `GUIDE` 포함) 탐색 후 데이터 추출
  - `NO` 컬럼이 단일 알파벳(`A`~`Z`)인 행만 유효 데이터로 처리 (`continue`로 빈 행 허용)
  - ITEM 다중 컬럼 병합, GUIDE 다중 컬럼 병합 (콤마 구분)
  - `FIGURE` 컬럼 이전까지만 GUIDE로 인식
  - 실패 파일 목록 → `data/error/error_log_extract_checklists_*.txt`
- **`run_2nd_preprocessing(data_root, input_file_name)`**: Title 컬럼 정제
  - 앞 숫자 인덱스 제거 (`re.sub(r'^[0-9\s.\-_]+'...`)
  - 괄호·특수기호 → 공백 치환

---

### `src/table_parser.py`

- **입력**: `data/result/preprocessed_data_final.xlsx` (Title, Item, Guide, Reason 컬럼)
- **출력**: `data/result/final_text_data_{n}.xlsx` (Text 컬럼, 500행 단위 청크)
- **LLM**: `OllamaLLM(model="gemma2", temperature=0.0)` — 재현성 최우선
- **마크다운 출력 형식**:
  ```
  # [품목: {item}] [주제: {title}]
  ---
  ## 설계 표준 가이드
  (서술형 내용...)
  ```
- LLM 호출 실패 시 원본 Guide 텍스트로 폴백
- `Reason` 컬럼은 현재 미사용 (향후 보강 예정)

---

## 개발 시 주의사항

### 보안
- `chatbot_meg.py` — 비밀번호가 소스코드에 하드코딩되어 있음
  ```python
  if password_input in ["3차원!", "3ckdnjs!"]:
  ```
  → 환경변수 또는 외부 시크릿 관리로 교체 필요

### 플랫폼 의존성
- `preprocess_meg.py`는 `win32com` 사용으로 **Windows에서만 실행 가능**
- `chatbot_meg.py`와 `table_parser.py`는 크로스플랫폼 동작

### LLM / Ollama
- 로컬에 Ollama 서버가 `http://localhost:11434`에서 실행 중이어야 함
- 사용 모델: `gemma2` (임베딩 + 생성 모두 동일 모델 사용)
- `chatbot_meg.py`의 `collection_name="design_bot_final_v8"` — 버전 변경 시 컬렉션명 업데이트 필요

### 데이터 파일
- `data/result/final_text_data_*.xlsx` 파일이 없으면 앱이 에러를 표시하고 종료

---

## 실행 방법

### 1. 전처리 (최초 1회, Windows 환경)
```bash
# Excel 원본을 data/raw_data/ 에 위치시킨 후
python src/preprocess_meg.py

# LLM 마크다운 변환 (Ollama 실행 필요)
python src/table_parser.py
```

### 2. 챗봇 앱 실행
```bash
streamlit run src/chatbot_meg.py
```

---

## 향후 개선 예정 사항

- `Reason` 컬럼 데이터 보강 후 프롬프트에 설계 근거 포함
- 비밀번호 하드코딩 제거
- `preprocess_meg.py` Linux/Mac 호환 버전 작성 (win32com 제거)
