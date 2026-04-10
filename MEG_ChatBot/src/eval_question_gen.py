"""
eval_question_gen.py — 평가용 질문셋 자동 생성기
================================================
ChromaDB 문서를 샘플링하여 LLM이 질문 + 정답 항목을 자동 생성합니다.
정답은 항목별로 분리(정답_1, 정답_2 ...)되어 저장됩니다.
이를 통해 eval_ragas.py 에서 Precision / Recall / F1 계산이 가능합니다.

실행:
    python src/eval_question_gen.py

출력 폴더 구조:
    MEG_ChatBot/
    └── eval/
        └── questions/
            └── <db_key>/
                ├── eval_questions_draft.xlsx   ← LLM 자동 생성 초안
                └── eval_questions.xlsx         ← 검토 완료 후 저장 (eval_ragas.py 가 읽음)

[검토 절차]
  1. eval_questions_draft.xlsx 를 엑셀로 열기
  2. 어색한 질문 → '사용여부' 를 X 로 변경
  3. 틀린 수치 → 해당 셀 직접 수정
  4. 빠진 정답 항목 → 다음 빈 '정답_N' 컬럼에 추가
  5. 파일명을 eval_questions.xlsx 로 변경하여 같은 폴더에 저장

[엑셀 컬럼 구조]
  사용여부 | 질문 | 정답_1 | 정답_2 | ... | 정답_8 | 출처문서
"""

import os
import sys
import json
import random
import pandas as pd
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vector_store import load_vector_db

# ============ 설정 ============
GEN_MODEL        = "qwen3:8b"  # 질문 생성 LLM (table_parser.py 의 TABLE_PARSER_MODEL 과 동일)
SAMPLE_COUNT     = 25          # ChromaDB 샘플링 수 (목표 20개 + 실패 여유분)
MAX_ANSWER_ITEMS = 8           # 정답 항목 최대 개수 (정답_1 ~ 정답_8)
RANDOM_SEED      = 42
# ==============================

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser


QUESTION_GEN_TEMPLATE = """/no_think
너는 기구 설계 RAG 시스템 평가 전문가야.
아래 [설계 가이드 문서]를 읽고, 실제 설계 담당자가 챗봇에 물어볼 법한 질문 1개와
그 질문에 대한 정답 사실들을 항목별로 분리하여 작성하라.

[설계 가이드 문서]
{document}

[작성 규칙]
1. 질문은 설계 담당자가 자연어로 입력할 법한 형태로 작성하라.
2. 정답은 문서에서 찾을 수 있는 구체적 사실을 항목 하나에 하나씩 분리하라.
3. 수치(mm, T, N, °C 등)와 단위는 반드시 포함하라.
4. 문서에 없는 내용은 절대 지어내지 마라.
5. 정답 항목은 최소 1개, 최대 {max_items}개까지 작성하라.
6. 아래 형식을 정확히 지켜라. 다른 말은 절대 추가하지 마라.

[출력 형식]
질문: (질문 내용)
정답_1: (첫 번째 정답 사실)
정답_2: (두 번째 정답 사실, 없으면 생략)
정답_3: (세 번째 정답 사실, 없으면 생략)
"""


def load_registry() -> dict:
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    for path in [
        os.path.join(current_dir,  "db_registry.json"),
        os.path.join(project_root, "db_registry.json"),
    ]:
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
    return {}


def get_eval_questions_dir(project_root: str, db_key: str) -> str:
    """질문셋 저장 경로: MEG_ChatBot/eval/questions/<db_key>/"""
    return os.path.join(project_root, "eval", "questions", db_key)


def parse_output(text: str, max_items: int) -> tuple[str, list[str]]:
    """LLM 출력에서 질문과 정답 항목 목록 파싱"""
    question = ""
    answers  = []
    for line in text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("질문:"):
            question = line.replace("질문:", "").strip()
        else:
            for i in range(1, max_items + 1):
                prefix = f"정답_{i}:"
                if line.startswith(prefix):
                    val = line.replace(prefix, "").strip()
                    if val:
                        answers.append(val)
                    break
    return question.strip(), answers


def main():
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)

    # registry 로드
    registry = load_registry()
    if not registry:
        print("❌ db_registry.json 을 찾을 수 없습니다.")
        sys.exit(1)

    print("등록된 DB 목록:")
    for key, info in registry.items():
        print(f"  [{key}] {info['display_name']}  —  {info.get('description', '')}")

    db_key = input("\n질문을 생성할 DB 키를 입력하세요: ").strip()
    if db_key not in registry:
        print(f"❌ '{db_key}' 는 registry 에 없는 키입니다.")
        sys.exit(1)

    # 출력 경로: MEG_ChatBot/eval/questions/<db_key>/
    questions_dir = get_eval_questions_dir(project_root, db_key)
    os.makedirs(questions_dir, exist_ok=True)
    output_path = os.path.join(questions_dir, "eval_questions_draft.xlsx")

    # ChromaDB 로드
    print(f"\nChromaDB 로드 중 [{db_key}]...")
    try:
        vector_db = load_vector_db(db_key)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # 문서 샘플링
    collection  = vector_db._collection
    total_count = collection.count()
    sample_size = min(SAMPLE_COUNT, total_count)
    print(f"전체 문서 수: {total_count}개 → {sample_size}개 샘플링")

    random.seed(RANDOM_SEED)
    all_texts     = collection.get(include=["documents"])["documents"]
    sampled_texts = random.sample(all_texts, sample_size)

    # LLM 세팅
    print(f"\n질문+정답 항목 생성 시작 (모델: {GEN_MODEL})\n")
    llm    = OllamaLLM(model=GEN_MODEL, temperature=0.3)
    prompt = ChatPromptTemplate.from_template(QUESTION_GEN_TEMPLATE)
    chain  = prompt | llm | StrOutputParser()

    results    = []
    fail_count = 0

    for i, doc_text in enumerate(tqdm(sampled_texts, desc="생성 진행 중")):
        try:
            response = chain.invoke({
                "document":  doc_text[:1500],
                "max_items": MAX_ANSWER_ITEMS,
            })
            question, answers = parse_output(response, MAX_ANSWER_ITEMS)

            if not question or not answers:
                fail_count += 1
                continue

            row = {
                "사용여부": "O",
                "질문":     question,
            }
            for idx in range(1, MAX_ANSWER_ITEMS + 1):
                row[f"정답_{idx}"] = answers[idx - 1] if idx <= len(answers) else ""

            row["출처문서"] = doc_text[:300] + "..." if len(doc_text) > 300 else doc_text
            results.append(row)

        except Exception as e:
            print(f"\n  생성 실패 (index={i}): {e}")
            fail_count += 1

    # 엑셀 저장
    cols = ["사용여부", "질문"] + [f"정답_{i}" for i in range(1, MAX_ANSWER_ITEMS + 1)] + ["출처문서"]
    df   = pd.DataFrame(results).reindex(columns=cols)
    df.to_excel(output_path, index=False, engine="openpyxl")

    print(f"\n✅ 생성 완료!  성공: {len(results)}개 / 실패: {fail_count}개")
    print(f"   저장 위치: {output_path}")
    print()
    print("=" * 65)
    print("📋 검토 방법 (엑셀을 열어 아래 순서로 진행하세요):")
    print()
    print("  [1] '사용여부' 컬럼")
    print("      → 질문이 어색하거나 DB와 무관하면 X 로 변경")
    print()
    print("  [2] '정답_N' 컬럼  ← 핵심 작업")
    print("      → LLM이 틀린 수치를 썼으면 직접 수정")
    print("      → 빠진 정답 항목이 있으면 다음 빈 정답_N 컬럼에 추가")
    print("      → 관련 없는 항목이 있으면 해당 셀만 삭제")
    print()
    print("  [3] 저장")
    print(f"      → 파일명을 eval_questions.xlsx 로 변경하여 저장")
    print(f"      → 저장 위치: eval/questions/{db_key}/eval_questions.xlsx")
    print()
    print("  [4] 평가 실행")
    print("      → python src/eval_ragas.py")
    print("=" * 65)


if __name__ == "__main__":
    main()
