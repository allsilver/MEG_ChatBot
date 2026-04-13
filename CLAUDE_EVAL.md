# CLAUDE_EVAL.md — MEG_ChatBot 성능 평가 시스템 가이드

> 기존 `CLAUDE.md` 와 별도로 관리되는 문서입니다.
> 평가 관련 작업 시 이 파일을 함께 첨부하세요.

---

## 개요

RAG 챗봇의 성능을 **모델 조합별로 정량 평가**하고 비교하기 위한 시스템입니다.
LLM-as-Judge 방식으로 로컬 Ollama만 사용하며, 외부 API 없이 동작합니다.

---

## 추가된 파일 (기존 파일 수정 없음)

```
MEG_ChatBot/
└── src/
    ├── eval_question_gen.py   ← 평가용 질문셋 자동 생성
    └── eval_ragas.py          ← 성능 평가 및 리포트 생성
```

---

## 폴더 구조

```
MEG_ChatBot/
└── eval/
    ├── eval_summary.xlsx                        ← 전체 실험 누적 비교표
    │     시트1: 지표설명  — 각 지표 의미 및 해석 방법
    │     시트2: 실험결과  — 실험별 점수 누적
    │
    ├── questions/                               ← 질문셋 보관
    │   └── <db_key>/
    │       ├── eval_questions_draft.xlsx        ← LLM 자동 생성 초안
    │       └── eval_questions.xlsx             ← 검토 완료본 (eval_ragas.py 가 읽음)
    │
    └── <임베딩모델>_<생성모델>/                 ← 모델 조합별 폴더
        └── <db_key>/                           ← DB별 폴더
            └── eval_report_<timestamp>.xlsx    ← 상세 리포트
```

---

## 실행 순서

### 1단계 — 질문셋 생성 (최초 1회 또는 DB 변경 시)

```bash
python src/eval_question_gen.py
```

- 실행 시 DB 키 입력 (예: `mobile`)
- ChromaDB에서 25개 문서 샘플링 → LLM이 질문 + 정답 항목 자동 생성
- 출력: `eval/questions/<db_key>/eval_questions_draft.xlsx`

**검토 절차 (1~2시간, 도메인 전문가가 직접 수행)**

| 컬럼 | 작업 |
|---|---|
| `사용여부` | 어색한 질문은 `X` 로 변경 |
| `정답_1` ~ `정답_8` | 틀린 수치 수정 / 빠진 항목 추가 / 무관한 항목 삭제 |

검토 완료 후 파일명을 `eval_questions.xlsx` 로 변경하여 같은 폴더에 저장.

### 2단계 — 성능 평가 실행

```bash
python src/eval_ragas.py
# 실험명 직접 지정 시
python src/eval_ragas.py --run-name "qwen3_8b_실험1"
```

- 실행 시 DB 키 입력 (쉼표로 복수 선택 가능, 예: `mobile,folderable`)
- 자동으로 `eval/<임베딩>_<생성>/` 폴더 생성 후 리포트 저장
- `eval/eval_summary.xlsx` 에 결과 누적

---

## 평가 지표

### ★ 메인 지표 (임원 보고용)

| 지표 | 측정 내용 | 낮을 때 의심 |
|---|---|---|
| **Precision** | 챗봇이 말한 내용 중 정답 항목과 일치하는 비율 | 없는 내용을 지어냄 (환각) |
| **Recall** | 정답 항목 중 챗봇이 실제로 언급한 비율 | DB 안의 정보를 빠뜨림 (누락) |
| **F1 Score** | Precision 과 Recall 의 조화평균 | 정확성 또는 완전성이 낮음 |
| **ROUGE-L** | 챗봇 답변과 정답의 최장 공통 부분 문자열 기반 유사도 | 표현 방식이 정답과 많이 다름 |

**F1 Score 를 단일 대표 지표로 사용 권장.**

> **ROUGE-L 해석 주의**: 표현이 달라도 의미가 같으면 낮게 나올 수 있음.
> F1이 높고 ROUGE-L이 낮으면 → 정보는 맞는데 표현 방식이 다른 것. 실용적으로는 괜찮음.

### [참고] RAGAS 지표 (LLM-as-Judge)

| 지표 | 측정 내용 | 낮을 때 의심 |
|---|---|---|
| **Faithfulness** | 답변이 검색 문서에만 근거하는가 | LLM이 자체 지식으로 답변 |
| **Answer Relevancy** | 답변이 질문과 직접 관련 있는가 | 프롬프트 개선 필요 |
| **Context Precision** | 검색된 문서가 질문과 관련 있는가 | 임베딩 모델 교체 고려 |
| **Answer Similarity** | 생성 답변과 정답의 의미적 유사도 | 모델 교체 또는 질문셋 재검토 |

> **주의**: RAGAS 지표는 평가자 LLM의 주관이 개입됩니다.
> 절대 수치보다 **동일 질문셋으로 측정한 실험 간 상대 비교**에 의미가 있습니다.

---

## 모델 비교 방법

### 생성 모델만 바꿀 때 (ChromaDB 재구축 불필요)

`rag_engine.py` 상단의 `GENERATOR_MODEL` 변경 후 바로 실행:

```bash
python src/eval_ragas.py --run-name "gemma2"
```

`eval_summary.xlsx` 의 실험결과 시트에 행이 누적되어 자동 비교됩니다.

### 임베딩 모델을 바꿀 때 (ChromaDB 재구축 필요)

`vector_store.py` 상단의 `EMBEDDING_MODEL` 변경 후:

```bash
python src/table_parser.py   # ChromaDB 재구축 (y 선택)
python src/eval_ragas.py --run-name "new_embedding"
```

---

## 설정 상수 요약

| 파일 | 상수 | 기본값 | 설명 |
|---|---|---|---|
| `eval_question_gen.py` | `GEN_MODEL` | `qwen3:8b` | 질문 생성 LLM |
| `eval_question_gen.py` | `SAMPLE_COUNT` | `25` | ChromaDB 샘플링 수 |
| `eval_question_gen.py` | `MAX_ANSWER_ITEMS` | `8` | 정답 항목 최대 개수 |
| `eval_ragas.py` | `JUDGE_MODEL` | `qwen3:8b` | RAGAS 평가자 LLM |
| `eval_ragas.py` | `MAX_ANSWER_ITEMS` | `8` | eval_question_gen.py 와 동일하게 유지 |
| `eval_ragas.py` | `MATCH_THRESHOLD` | `0.5` | 정답 항목 포함 여부 판단 임계값 |
| `eval_ragas.py` | `RETRIEVAL_K` | `10` | rag_engine.py 와 동일하게 유지 |
| `eval_ragas.py` | `SCORE_THRESHOLD` | `0.2` | rag_engine.py 와 동일하게 유지 |

---

## 의존성

```bash
pip install rouge-score   # ROUGE-L 계산 (오프라인 동작)
```

기존 의존성(`langchain`, `langchain-ollama`, `chromadb`, `openpyxl`, `tqdm`)은
`CLAUDE.md` 참고.

---

## 주요 결정 사항 및 배경

### BERTScore 대신 ROUGE-L을 사용하는 이유
회사 네트워크 방화벽으로 HuggingFace 접속이 차단되어 BERTScore 모델 다운로드가 불가능합니다.
ROUGE-L은 외부 다운로드 없이 완전 오프라인으로 동작합니다.
네트워크 환경이 개선되면 BERTScore로 교체를 권장합니다 (`pip install bert-score`).

### Precision = Recall 인 이유
챗봇 답변에서 "말한 항목 수"를 자동으로 파싱하기 어려워,
정답 항목 수를 공통 분모로 사용하는 근사 방식을 채택했습니다.
이 경우 P = R = F1 로 수렴합니다.
향후 챗봇 답변 파싱 로직 추가 시 분리 가능합니다.

### 논문(MechRAG) 지표와의 차이
MechRAG 논문의 Accuracy/Precision/F1은 **분류 태스크** 기준입니다.
우리 챗봇은 **자유 형식 생성 태스크**이므로 동일 지표를 그대로 적용할 수 없고,
정보 검색(Information Retrieval) 방식으로 재정의하여 사용합니다.
