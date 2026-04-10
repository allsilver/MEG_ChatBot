"""
eval_ragas.py — RAG 성능 평가 및 모델 비교 리포트 생성기
==========================================================
eval_questions.xlsx 의 질문셋으로 RAG 시스템을 평가하고
결과를 엑셀 리포트로 저장합니다.

[평가 지표]
★ 메인 지표 (임원 보고용)
  - Precision  : 챗봇이 말한 내용 중 정답 항목과 일치하는 비율 (환각 감지)
  - Recall     : 정답 항목 중 챗봇이 실제로 언급한 비율 (누락 감지)
  - F1 Score   : Precision 과 Recall 의 조화평균 (종합 성능)
  - ROUGE-L    : 챗봇 답변과 정답의 최장 공통 부분 문자열 기반 유사도
                 (외부 다운로드 없이 완전 오프라인 동작)

[참고 지표] RAGAS 기반, LLM-as-Judge
  - Faithfulness      : 답변이 검색 문서에 근거하는가
  - Answer Relevancy  : 답변이 질문과 관련 있는가
  - Context Precision : 검색된 문서가 질문과 관련 있는가
  - Answer Similarity : 정답과 생성 답변의 의미적 유사도

실행:
    python src/eval_ragas.py
    python src/eval_ragas.py --run-name "실험명"

출력 폴더 구조:
    MEG_ChatBot/
    └── eval/
        ├── eval_summary.xlsx                        ← 전체 실험 누적 비교표 (지표 설명 포함)
        ├── questions/                               ← 질문셋 (eval_question_gen.py 가 생성)
        │   └── <db_key>/
        │       └── eval_questions.xlsx
        └── <임베딩모델>_<생성모델>/                 ← 모델 조합별 폴더
            └── <db_key>/                            ← DB별 폴더 (복수면 "db1+db2")
                └── eval_report_<timestamp>.xlsx     ← 상세 리포트

의존성:
    pip install langchain langchain-ollama langchain-chroma chromadb
                openpyxl tqdm rouge-score
"""

import os
import sys
import json
import argparse
import re
import pandas as pd
from datetime import datetime
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vector_store import load_multiple_vector_dbs, EMBEDDING_MODEL
from rag_engine import setup_design_bot, GENERATOR_MODEL

# ============ 평가 설정 ============
JUDGE_MODEL      = "qwen3:8b"  # RAGAS 참고 지표 평가자 LLM
QUESTIONS_FILE   = "eval_questions.xlsx"
MAX_ANSWER_ITEMS = 8           # eval_question_gen.py 와 동일하게
RETRIEVAL_K      = 10          # rag_engine.py 와 동일하게
SCORE_THRESHOLD  = 0.2         # rag_engine.py 와 동일하게
MATCH_THRESHOLD  = 0.5         # 정답 항목 포함 여부 판단 임계값
# ===================================

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


# ══════════════════════════════════════════════════════════════
# 경로 헬퍼
# ══════════════════════════════════════════════════════════════

def get_project_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def get_eval_root() -> str:
    """MEG_ChatBot/eval/"""
    return os.path.join(get_project_root(), "eval")


def get_questions_path(db_key: str) -> str:
    """MEG_ChatBot/eval/questions/<db_key>/eval_questions.xlsx"""
    return os.path.join(get_eval_root(), "questions", db_key, QUESTIONS_FILE)


def get_report_dir(target_keys: list[str]) -> str:
    """
    MEG_ChatBot/eval/<임베딩모델>_<생성모델>/<db_key>/
    모델명의 특수문자(:)는 하이픈으로 치환하여 폴더명으로 안전하게 사용
    복수 DB 는 알파벳 순 정렬 후 "+" 로 연결
    """
    emb_tag   = EMBEDDING_MODEL.replace(":", "-").replace("/", "_")
    gen_tag   = GENERATOR_MODEL.replace(":", "-").replace("/", "_")
    model_dir = os.path.join(get_eval_root(), f"{emb_tag}_{gen_tag}")
    db_folder = "+".join(sorted(target_keys))
    return os.path.join(model_dir, db_folder)


def get_summary_path() -> str:
    """MEG_ChatBot/eval/eval_summary.xlsx"""
    return os.path.join(get_eval_root(), "eval_summary.xlsx")


# ══════════════════════════════════════════════════════════════
# [1] 메인 지표 — Precision / Recall / F1
# ══════════════════════════════════════════════════════════════

ITEM_MATCH_PROMPT = """/no_think
아래 [챗봇 답변]이 [정답 항목]의 내용을 포함하고 있는지 판단하라.
수치와 단위가 일치해야 하며, 표현이 달라도 같은 의미면 포함된 것으로 본다.

[정답 항목]
{answer_item}

[챗봇 답변]
{bot_answer}

반드시 아래 형식으로만 출력하라:
점수: (포함되어 있으면 1.0, 아니면 0.0)
이유: (한 줄 설명)"""


def parse_score(text: str) -> tuple[float, str]:
    score, reason = -1.0, ""
    for line in text.strip().splitlines():
        line = line.strip()
        if line.startswith("점수:"):
            try:
                score = float(re.search(r"[\d.]+", line).group())
                score = max(0.0, min(1.0, score))
            except Exception:
                score = -1.0
        elif line.startswith("이유:"):
            reason = line.replace("이유:", "").strip()
    return score, reason


def check_item_match(judge_llm, answer_item: str, bot_answer: str) -> tuple[float, str]:
    try:
        prompt = ChatPromptTemplate.from_template(ITEM_MATCH_PROMPT)
        chain  = prompt | judge_llm | StrOutputParser()
        output = chain.invoke({"answer_item": answer_item, "bot_answer": bot_answer})
        score, reason = parse_score(output)
        matched = 1.0 if score >= MATCH_THRESHOLD else 0.0
        return matched, reason
    except Exception as e:
        return 0.0, f"판단 오류: {e}"


def calc_precision_recall_f1(judge_llm, answer_items: list[str], bot_answer: str) -> dict:
    """
    정답 항목 목록과 챗봇 답변을 비교하여 Precision / Recall / F1 계산.

    [분모 설명]
    - Precision 분모: 정답 항목 수 (챗봇 답변에서 항목을 자동 파싱하기 어려워
                      정답 항목 수를 공통 분모로 사용하는 근사 방식)
    - Recall 분모   : 전체 정답 항목 수 (정의 그대로)
    - 두 분모가 같으므로 P = R, F1 = P 로 수렴하나
      ROUGE-L · RAGAS 와 함께 보면 충분히 의미 있음
    """
    if not answer_items:
        return {"precision": -1.0, "recall": -1.0, "f1": -1.0,
                "matched_items": [], "match_reasons": []}

    matched_items, match_reasons, matched_count = [], [], 0
    for item in answer_items:
        score, reason = check_item_match(judge_llm, item, bot_answer)
        matched_items.append(score)
        match_reasons.append(reason)
        if score >= MATCH_THRESHOLD:
            matched_count += 1

    n         = len(answer_items)
    precision = round(matched_count / n, 4)
    recall    = round(matched_count / n, 4)
    f1        = round(2 * precision * recall / (precision + recall), 4) \
                if (precision + recall) > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1,
            "matched_items": matched_items, "match_reasons": match_reasons}


# ══════════════════════════════════════════════════════════════
# [2] 메인 지표 — ROUGE-L
# ══════════════════════════════════════════════════════════════

def calc_rougel_batch(predictions: list[str], references: list[str]) -> list[float]:
    """
    ROUGE-L F1 배치 계산 (완전 오프라인 동작).
    ROUGE-L : 챗봇 답변과 정답의 최장 공통 부분 문자열(LCS) 기반 유사도.
    단어 순서를 고려하며, 부분 일치에도 점수를 부여함.
    pip install rouge-score 만 필요 (외부 모델 다운로드 없음).
    """
    try:
        from rouge_score import rouge_scorer
        scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=False)
        scores = []
        for pred, ref in zip(predictions, references):
            result = scorer.score(ref, pred)
            scores.append(round(result["rougeL"].fmeasure, 4))
        return scores
    except ImportError:
        print("⚠️  rouge-score 미설치 → ROUGE-L 은 -1 로 기록됩니다.")
        print("    설치: pip install rouge-score")
        return [-1.0] * len(predictions)
    except Exception as e:
        print(f"⚠️  ROUGE-L 계산 오류: {e}")
        return [-1.0] * len(predictions)


# ══════════════════════════════════════════════════════════════
# [3] 참고 지표 — RAGAS (LLM-as-Judge)
# ══════════════════════════════════════════════════════════════

FAITHFULNESS_PROMPT = """/no_think
아래 [답변]이 [참조 문서]의 내용에만 근거하여 작성되었는지 평가하라.

[참조 문서]
{context}

[답변]
{answer}

[평가 기준]
- 1.0: 답변 전체가 참조 문서에 근거함
- 0.7: 대부분 근거 있으나 일부 추론 포함
- 0.4: 절반 정도만 근거 있음
- 0.0: 참조 문서와 무관한 내용

반드시 아래 형식으로만 출력하라:
점수: (0.0~1.0 사이 숫자)
이유: (한 줄 설명)"""

RELEVANCY_PROMPT = """/no_think
아래 [답변]이 [질문]에 얼마나 관련 있고 직접적으로 답하는지 평가하라.

[질문]
{question}

[답변]
{answer}

[평가 기준]
- 1.0: 질문에 완전히 직접적으로 답함
- 0.7: 관련 있으나 일부 불필요한 내용 포함
- 0.4: 간접적으로만 관련 있음
- 0.0: 질문과 무관한 답변

반드시 아래 형식으로만 출력하라:
점수: (0.0~1.0 사이 숫자)
이유: (한 줄 설명)"""

CONTEXT_PRECISION_PROMPT = """/no_think
아래 [검색된 문서들]이 [질문]에 답하기 위해 얼마나 정확한 내용을 포함하는지 평가하라.

[질문]
{question}

[검색된 문서들]
{context}

[평가 기준]
- 1.0: 검색 문서 대부분이 질문과 직접 관련 있음
- 0.7: 절반 이상 관련 있음
- 0.4: 일부만 관련 있음
- 0.0: 검색 문서가 질문과 무관함

반드시 아래 형식으로만 출력하라:
점수: (0.0~1.0 사이 숫자)
이유: (한 줄 설명)"""

SIMILARITY_PROMPT = """/no_think
아래 [생성된 답변]과 [정답]이 의미적으로 얼마나 유사한지 평가하라.

[정답]
{ground_truth}

[생성된 답변]
{answer}

[평가 기준]
- 1.0: 정답과 동일한 정보를 전달함
- 0.7: 핵심 정보는 일치하나 세부 사항 차이 있음
- 0.4: 부분적으로만 일치함
- 0.0: 정답과 전혀 다른 내용

반드시 아래 형식으로만 출력하라:
점수: (0.0~1.0 사이 숫자)
이유: (한 줄 설명)"""


def evaluate_ragas(judge_llm, question, bot_answer, context, gt_full) -> dict:
    results = {}
    prompts = {
        "ragas_faithfulness":      (FAITHFULNESS_PROMPT,     {"context": context,         "answer": bot_answer}),
        "ragas_answer_relevancy":  (RELEVANCY_PROMPT,         {"question": question,       "answer": bot_answer}),
        "ragas_context_precision": (CONTEXT_PRECISION_PROMPT, {"question": question,       "context": context}),
        "ragas_answer_similarity": (SIMILARITY_PROMPT,        {"ground_truth": gt_full,    "answer": bot_answer}),
    }
    for metric, (template, variables) in prompts.items():
        try:
            chain  = ChatPromptTemplate.from_template(template) | judge_llm | StrOutputParser()
            output = chain.invoke(variables)
            score, reason          = parse_score(output)
            results[metric]        = score
            results[f"{metric}_이유"] = reason
        except Exception as e:
            results[metric]           = -1.0
            results[f"{metric}_이유"] = f"오류: {e}"
    return results


# ══════════════════════════════════════════════════════════════
# 공통 유틸
# ══════════════════════════════════════════════════════════════

def load_registry() -> dict:
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = get_project_root()
    for path in [
        os.path.join(current_dir,  "db_registry.json"),
        os.path.join(project_root, "db_registry.json"),
    ]:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return {}


def get_answer_items(row: pd.Series) -> list[str]:
    items = []
    for i in range(1, MAX_ANSWER_ITEMS + 1):
        col = f"정답_{i}"
        if col in row.index:
            val = str(row[col]).strip()
            if val and val.lower() not in ("nan", "none", ""):
                items.append(val)
    return items


def get_rag_response_with_context(vector_dbs: dict, query: str) -> tuple[str, str]:
    all_docs = []
    for vdb in vector_dbs.values():
        results = vdb.similarity_search_with_relevance_scores(query, k=RETRIEVAL_K)
        valid   = [doc for doc, score in results if score > SCORE_THRESHOLD]
        if not valid and results:
            valid = [results[0][0]]
        all_docs.extend(valid)

    seen, deduped = set(), []
    for doc in all_docs:
        if doc.page_content not in seen:
            seen.add(doc.page_content)
            deduped.append(doc)

    context_text = "\n\n---\n\n".join(doc.page_content for doc in deduped)
    answer       = setup_design_bot(vector_dbs)(query)
    return answer, context_text


def avg_valid(values: list[float]) -> float:
    valid = [v for v in values if v >= 0]
    return round(sum(valid) / len(valid), 4) if valid else -1.0


# ══════════════════════════════════════════════════════════════
# eval_summary.xlsx 지표 설명 시트
# ══════════════════════════════════════════════════════════════

def make_guide_df() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "구분":          "★ 메인 지표",
            "지표명":        "Precision (정확성)",
            "측정 내용":     "챗봇이 말한 내용 중 정답 항목과 일치하는 비율",
            "낮을 때 의심":  "챗봇이 없는 내용을 지어내고 있음 (환각, Hallucination)",
            "범위":          "0 ~ 1",
            "비고":          "1.0 에 가까울수록 좋음",
        },
        {
            "구분":          "★ 메인 지표",
            "지표명":        "Recall (완전성)",
            "측정 내용":     "정답 항목 중 챗봇이 실제로 언급한 비율",
            "낮을 때 의심":  "챗봇이 DB 안의 정보를 빠뜨리고 있음 (누락)",
            "범위":          "0 ~ 1",
            "비고":          "1.0 에 가까울수록 좋음",
        },
        {
            "구분":          "★ 메인 지표",
            "지표명":        "F1 Score (종합 성능)",
            "측정 내용":     "Precision 과 Recall 의 조화평균 — 두 지표를 동시에 반영한 대표 지표",
            "낮을 때 의심":  "정확성 또는 완전성 중 하나 이상이 낮음",
            "범위":          "0 ~ 1",
            "비고":          "임원 보고용 단일 대표 지표로 사용 권장",
        },
        {
            "구분":          "★ 메인 지표",
            "지표명":        "ROUGE-L (문장 유사도)",
            "측정 내용":     "챗봇 답변과 정답의 최장 공통 부분 문자열(LCS) 기반 유사도. 단어 순서를 고려하며 부분 일치에도 점수 부여",
            "낮을 때 의심":  "답변의 표현 방식이 정답과 많이 다름 (단, 의미는 같을 수 있어 RAGAS 지표와 함께 해석 필요)",
            "범위":          "0 ~ 1",
            "비고":          "외부 모델 다운로드 없이 완전 오프라인 동작. pip install rouge-score",
        },
        {
            "구분":          "[참고] RAGAS 지표",
            "지표명":        "Faithfulness",
            "측정 내용":     "답변이 검색된 문서에만 근거하는가",
            "낮을 때 의심":  "LLM이 검색 결과를 무시하고 자체 학습 지식으로 답변함",
            "범위":          "0 ~ 1",
            "비고":          "LLM-as-Judge 방식 (평가자 LLM의 주관 개입 있음)",
        },
        {
            "구분":          "[참고] RAGAS 지표",
            "지표명":        "Answer Relevancy",
            "측정 내용":     "답변이 질문과 얼마나 직접적으로 관련 있는가",
            "낮을 때 의심":  "질문과 동떨어진 답변 생성 → 프롬프트 개선 필요",
            "범위":          "0 ~ 1",
            "비고":          "LLM-as-Judge 방식",
        },
        {
            "구분":          "[참고] RAGAS 지표",
            "지표명":        "Context Precision",
            "측정 내용":     "검색된 문서가 질문과 얼마나 관련 있는가",
            "낮을 때 의심":  "벡터 검색이 엉뚱한 문서를 가져옴 → 임베딩 모델 교체 고려",
            "범위":          "0 ~ 1",
            "비고":          "LLM-as-Judge 방식",
        },
        {
            "구분":          "[참고] RAGAS 지표",
            "지표명":        "Answer Similarity",
            "측정 내용":     "생성된 답변과 정답 전체의 의미적 유사도",
            "낮을 때 의심":  "정답과 내용이 다름 → 질문셋 정답 재검토 또는 모델 교체",
            "범위":          "0 ~ 1",
            "비고":          "LLM-as-Judge 방식. ROUGE-L 과 보완적으로 해석",
        },
        {
            "구분":          "⚠ 주의사항",
            "지표명":        "상대 비교 원칙",
            "측정 내용":     "모든 지표는 절대 수치보다 동일 질문셋으로 측정한 실험 간 상대 비교에 의미가 있음",
            "낮을 때 의심":  "-",
            "범위":          "-",
            "비고":          "반드시 동일한 eval_questions.xlsx 로 비교할 것",
        },
    ])


# ══════════════════════════════════════════════════════════════
# 메인
# ══════════════════════════════════════════════════════════════

def main(run_name: str = None):
    registry = load_registry()
    if not registry:
        print("❌ db_registry.json 을 찾을 수 없습니다.")
        sys.exit(1)

    # ── DB 선택 ──
    print("등록된 DB 목록:")
    for key, info in registry.items():
        print(f"  [{key}] {info['display_name']}")

    keys_input  = input("\n평가할 DB 키 (쉼표 구분, 예: mobile,folderable): ").strip()
    target_keys = [k.strip() for k in keys_input.split(",") if k.strip() in registry]
    invalid     = [k.strip() for k in keys_input.split(",") if k.strip() not in registry]
    if invalid:
        print(f"⚠️  registry 에 없는 키 제외: {invalid}")
    if not target_keys:
        print("❌ 유효한 DB 키가 없습니다.")
        sys.exit(1)

    print(f"\n평가 대상 DB: {target_keys}")

    # ── 질문셋 로드 ──
    # 경로: MEG_ChatBot/eval/questions/<db_key>/eval_questions.xlsx
    df_list = []
    for key in target_keys:
        q_path = get_questions_path(key)
        if not os.path.exists(q_path):
            print(f"⚠️  [{key}] 질문셋 없음, 건너뜁니다.")
            print(f"    경로: {q_path}")
            continue
        df_tmp = pd.read_excel(q_path, engine="openpyxl")
        df_tmp["_db_key"] = key
        df_list.append(df_tmp)

    if not df_list:
        print("❌ 사용 가능한 질문셋이 없습니다.")
        print("   먼저 eval_question_gen.py 를 실행하고 eval_questions.xlsx 를 준비하세요.")
        sys.exit(1)

    df_q = pd.concat(df_list, ignore_index=True)
    if "사용여부" in df_q.columns:
        df_q = df_q[df_q["사용여부"].astype(str).str.strip().str.upper() == "O"]
    df_q = df_q.reset_index(drop=True)

    if df_q.empty:
        print("❌ 사용할 질문이 없습니다. '사용여부' 컬럼을 확인하세요.")
        sys.exit(1)

    print(f"평가할 질문 수: {len(df_q)}개")

    # ── 실험명 자동 생성 ──
    if not run_name:
        db_tag   = "+".join(sorted(target_keys))
        emb_tag  = EMBEDDING_MODEL.replace(":", "-").replace("/", "_")
        gen_tag  = GENERATOR_MODEL.replace(":", "-").replace("/", "_")
        run_name = f"{db_tag}__{emb_tag}__{gen_tag}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 모델 로드 ──
    print(f"\n모델 로드 중...")
    print(f"  임베딩 모델 : {EMBEDDING_MODEL}")
    print(f"  생성 모델   : {GENERATOR_MODEL}")
    print(f"  평가자 모델 : {JUDGE_MODEL}")

    vector_dbs = load_multiple_vector_dbs(target_keys)
    if not vector_dbs:
        print("❌ 로드된 DB 가 없습니다.")
        sys.exit(1)

    judge_llm = OllamaLLM(model=JUDGE_MODEL, temperature=0.0)

    # ── 평가 실행 ──
    print(f"\n평가 시작 (실험명: {run_name})")
    print("  [단계 1/2] Precision / Recall / F1 + RAGAS 계산 중...\n")

    detail_rows = []
    all_bot_ans = []
    all_gt_full = []

    for i, row in tqdm(df_q.iterrows(), total=len(df_q), desc="질문 평가 중"):
        question     = str(row["질문"]).strip()
        answer_items = get_answer_items(row)
        gt_full      = " | ".join(answer_items)
        src_db_key   = str(row.get("_db_key", ""))

        try:
            bot_answer, context = get_rag_response_with_context(vector_dbs, question)
        except Exception as e:
            print(f"\n  RAG 오류 (index={i}): {e}")
            bot_answer, context = f"오류: {e}", ""

        prf   = calc_precision_recall_f1(judge_llm, answer_items, bot_answer)
        ragas = evaluate_ragas(judge_llm, question, bot_answer, context, gt_full)

        all_bot_ans.append(bot_answer)
        all_gt_full.append(gt_full)

        # 항목별 매칭 결과 문자열
        item_match_str = ""
        for idx, (item, matched, reason) in enumerate(
            zip(answer_items, prf["matched_items"], prf["match_reasons"]), 1
        ):
            mark = "✓" if matched >= MATCH_THRESHOLD else "✗"
            item_match_str += f"[{mark}] 정답_{idx}: {item} → {reason}\n"

        detail_rows.append({
            "출처DB":          src_db_key,
            "질문":            question,
            "정답(전체)":      gt_full,
            "정답 항목 수":    len(answer_items),
            "생성된 답변":     bot_answer,
            "검색된 컨텍스트": context[:400] + "..." if len(context) > 400 else context,
            # ── 메인 지표 ──
            "precision":       prf["precision"],
            "recall":          prf["recall"],
            "f1":              prf["f1"],
            "rougel":          -1.0,
            # ── 참고: RAGAS ──
            "ragas_faithfulness":          ragas.get("ragas_faithfulness",          -1),
            "ragas_answer_relevancy":      ragas.get("ragas_answer_relevancy",      -1),
            "ragas_context_precision":     ragas.get("ragas_context_precision",     -1),
            "ragas_answer_similarity":     ragas.get("ragas_answer_similarity",     -1),
            "ragas_faithfulness_이유":     ragas.get("ragas_faithfulness_이유",     ""),
            "ragas_answer_relevancy_이유": ragas.get("ragas_answer_relevancy_이유", ""),
            "ragas_context_precision_이유":ragas.get("ragas_context_precision_이유",""),
            "ragas_answer_similarity_이유":ragas.get("ragas_answer_similarity_이유",""),
            "항목별_매칭_결과": item_match_str.strip(),
        })

    # ── [단계 2/2] ROUGE-L 배치 계산 ──
    print("\n  [단계 2/2] ROUGE-L 계산 중...")
    rouge_scores = calc_rougel_batch(all_bot_ans, all_gt_full)
    for idx, bs in enumerate(rouge_scores):
        detail_rows[idx]["rougel"] = bs

    df_detail = pd.DataFrame(detail_rows)

    # ── 평균 집계 ──
    main_metrics  = ["precision", "recall", "f1", "rougel"]
    ragas_metrics = ["ragas_faithfulness", "ragas_answer_relevancy",
                     "ragas_context_precision", "ragas_answer_similarity"]

    avg_main  = {m: avg_valid(df_detail[m].tolist()) for m in main_metrics}
    avg_ragas = {m: avg_valid(df_detail[m].tolist()) for m in ragas_metrics}

    # ── 저장 경로 구성 ──
    # 상세 리포트: MEG_ChatBot/eval/<임베딩_생성>/<db>/eval_report_<timestamp>.xlsx
    # summary    : MEG_ChatBot/eval/eval_summary.xlsx
    report_dir  = get_report_dir(target_keys)
    os.makedirs(report_dir, exist_ok=True)
    os.makedirs(get_eval_root(), exist_ok=True)

    report_filename = f"eval_report_{timestamp}.xlsx"
    report_path     = os.path.join(report_dir, report_filename)
    summary_path    = get_summary_path()

    # summary 에 표시할 상대 경로 (eval/ 기준)
    report_rel_path = os.path.relpath(report_path, get_eval_root())

    # ── 상세 리포트 저장 ──
    with pd.ExcelWriter(report_path, engine="openpyxl") as writer:

        # 시트1: 요약 (임원 보고용)
        pd.DataFrame([{
            "실험명":                   run_name,
            "평가일시":                 timestamp,
            "평가 DB":                  ", ".join(target_keys),
            "임베딩 모델":              EMBEDDING_MODEL,
            "생성 모델":                GENERATOR_MODEL,
            "평가자 모델":              JUDGE_MODEL,
            "질문 수":                  len(df_detail),
            "★ Precision (정확성)":     avg_main["precision"],
            "★ Recall    (완전성)":     avg_main["recall"],
            "★ F1 Score  (종합)":       avg_main["f1"],
            "★ ROUGE-L   (문장유사도)": avg_main["rougel"],
            "[참고] Faithfulness":      avg_ragas["ragas_faithfulness"],
            "[참고] Answer Relevancy":  avg_ragas["ragas_answer_relevancy"],
            "[참고] Context Precision": avg_ragas["ragas_context_precision"],
            "[참고] Answer Similarity": avg_ragas["ragas_answer_similarity"],
        }]).to_excel(writer, sheet_name="요약(임원보고용)", index=False)

        # 시트2: 상세 결과
        df_detail.to_excel(writer, sheet_name="상세결과", index=False)

        # 시트3: DB별 소계 (복수 DB 시)
        if len(target_keys) > 1:
            db_rows = []
            for key, grp in df_detail.groupby("출처DB"):
                g_main  = {m: avg_valid(grp[m].tolist()) for m in main_metrics}
                g_ragas = {m: avg_valid(grp[m].tolist()) for m in ragas_metrics}
                db_rows.append({
                    "출처DB":                   key,
                    "질문 수":                  len(grp),
                    "★ Precision":              g_main["precision"],
                    "★ Recall":                 g_main["recall"],
                    "★ F1 Score":               g_main["f1"],
                    "★ ROUGE-L":                g_main["rougel"],
                    "[참고] Faithfulness":      g_ragas["ragas_faithfulness"],
                    "[참고] Answer Relevancy":  g_ragas["ragas_answer_relevancy"],
                    "[참고] Context Precision": g_ragas["ragas_context_precision"],
                    "[참고] Answer Similarity": g_ragas["ragas_answer_similarity"],
                })
            pd.DataFrame(db_rows).to_excel(writer, sheet_name="DB별소계", index=False)

    print(f"\n✅ 상세 리포트 저장: {report_path}")

    # ── eval_summary.xlsx 갱신 ──
    new_row = pd.DataFrame([{
        "실험명":                   run_name,
        "평가일시":                 timestamp,
        "평가 DB":                  ", ".join(target_keys),
        "임베딩 모델":              EMBEDDING_MODEL,
        "생성 모델":                GENERATOR_MODEL,
        "질문 수":                  len(df_detail),
        "★ Precision":              avg_main["precision"],
        "★ Recall":                 avg_main["recall"],
        "★ F1 Score":               avg_main["f1"],
        "★ ROUGE-L":               avg_main["rougel"],
        "[참고] Faithfulness":      avg_ragas["ragas_faithfulness"],
        "[참고] Answer Relevancy":  avg_ragas["ragas_answer_relevancy"],
        "[참고] Context Precision": avg_ragas["ragas_context_precision"],
        "[참고] Answer Similarity": avg_ragas["ragas_answer_similarity"],
        "상세 리포트 경로":         report_rel_path,
    }])

    # 기존 summary 에서 실험결과 시트만 읽어 누적
    if os.path.exists(summary_path):
        try:
            df_existing = pd.read_excel(summary_path, sheet_name="실험결과", engine="openpyxl")
            df_summary  = pd.concat([df_existing, new_row], ignore_index=True)
        except Exception:
            # 시트 이름이 다른 구버전 파일이면 그냥 덮어씀
            df_summary = new_row
    else:
        df_summary = new_row

    # 지표 설명 시트를 첫 번째로, 실험결과 시트를 두 번째로 저장
    with pd.ExcelWriter(summary_path, engine="openpyxl") as writer:
        make_guide_df().to_excel(writer, sheet_name="지표설명",  index=False)
        df_summary.to_excel(writer,      sheet_name="실험결과",  index=False)

    print(f"✅ 누적 비교표 갱신: {summary_path}")

    # ── 터미널 결과 출력 ──
    print()
    print("=" * 60)
    print(f"  실험명 : {run_name}")
    print(f"  평가 DB: {', '.join(target_keys)}")
    print("-" * 60)
    print("  ★ 메인 지표 (임원 보고용)")
    print(f"    Precision  (정확성 — 환각 방지) : {avg_main['precision']:.4f}")
    print(f"    Recall     (완전성 — 누락 방지) : {avg_main['recall']:.4f}")
    print(f"    F1 Score   (종합 성능)          : {avg_main['f1']:.4f}")
    print(f"    ROUGE-L    (문장 유사도)          : {avg_main['rougel']:.4f}")
    print("-" * 60)
    print("  [참고] RAGAS 지표")
    print(f"    Faithfulness      : {avg_ragas['ragas_faithfulness']:.4f}")
    print(f"    Answer Relevancy  : {avg_ragas['ragas_answer_relevancy']:.4f}")
    print(f"    Context Precision : {avg_ragas['ragas_context_precision']:.4f}")
    print(f"    Answer Similarity : {avg_ragas['ragas_answer_similarity']:.4f}")
    print("=" * 60)
    print(f"\n📁 저장 구조:")
    print(f"   eval/")
    print(f"   ├── eval_summary.xlsx")
    print(f"   └── {os.path.relpath(report_dir, get_eval_root())}/")
    print(f"       └── {report_filename}")

    # 누적 비교표 터미널 출력
    if len(df_summary) > 1:
        print("\n📊 전체 실험 누적 비교표:")
        print(df_summary[[
            "실험명", "평가 DB", "생성 모델",
            "★ Precision", "★ Recall", "★ F1 Score", "★ ROUGE-L"
        ]].to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="RAG 성능 평가 스크립트")
    parser.add_argument(
        "--run-name", type=str, default=None,
        help="실험명 (기본값: DB키__임베딩모델__생성모델 로 자동 생성)"
    )
    args = parser.parse_args()
    main(run_name=args.run_name)
