import os
import sys
import json
import shutil
import pandas as pd

# ============ 모델 설정 ============
# TABLE_PARSER_MODEL = "gemma2"
# TABLE_PARSER_MODEL = "qwen3:14b"
TABLE_PARSER_MODEL = "qwen3:8b"    # 속도/품질 균형 (권장)
# ==================================

from langchain_ollama import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from preprocess_meg import convert_all_excel_to_csv, process_and_save_checklists, run_2nd_preprocessing


def transform_to_natural_text(domain_data_root: str, db_key: str, use_think: bool = False):
    """
    LLM으로 자연어 변환 후 final_text_data_*.xlsx 저장.
    domain_data_root: data/<DOMAIN_KEY>/
    """
    input_path    = os.path.join(domain_data_root, 'result', db_key, 'preprocessed_data_final.xlsx')
    output_folder = os.path.join(domain_data_root, 'result', db_key)
    os.makedirs(output_folder, exist_ok=True)

    if not os.path.exists(input_path):
        print(f"원본 파일을 찾을 수 없습니다: {input_path}")
        return

    df         = pd.read_excel(input_path, engine='openpyxl')
    total_rows = len(df)
    mode_label = "Thinking 모드" if use_think else "빠른 응답 모드 (no_think)"
    print(f"[{db_key}] 총 {total_rows}개 데이터를 자연어 변환 중입니다. [{mode_label}]")

    llm = OllamaLLM(model=TABLE_PARSER_MODEL, temperature=0.0, num_ctx=4096)

    no_think_prefix = "" if use_think else "/no_think\n"
    template = no_think_prefix + \
"""너는 기구 설계 체크리스트 데이터를 자연어로 변환하는 기술 편집자야.
반드시 아래 규칙을 지켜라.

[입력 데이터]
분류: {title}
항목: {item}
설계 가이드: {guide}

[절대 금지 사항]
- 입력에 없는 수치, 단위, 부품명, 조건, 사례를 추가하는 것은 절대 금지
- 입력 내용을 축소하거나 생략하는 것 금지
- 마크다운 기호(#, ##, ---, *, 백틱 등) 사용 금지
- 설명, 인사말, 메타 발언 없이 본문만 출력

[변환 규칙]
1. 분류와 항목을 첫 문장에 자연스럽게 녹여라.
2. 설계 가이드의 내용을 완전한 한국어 문장으로 풀어써라.
3. 기호와 약어만 아래 기준으로 풀어써라. 그 외 단어는 원문 그대로 유지하라.
   T(두께 단위)는 두께, φ 또는 Ø는 직경, 위쪽 화살표는 이상, 아래쪽 화살표는 이하, 오른쪽 화살표는 문맥에 맞는 표현으로 바꿔라.
4. 수치와 단위(mm, T, 도씨 등)는 원문과 동일하게 유지하라.
5. 출력은 2~4문장의 하나의 문단으로 작성하라.

변환 결과:"""

    prompt = ChatPromptTemplate.from_template(template)
    chain  = prompt | llm

    chunk_size          = 500
    current_chunk_texts = []
    chunk_count         = 1

    for index, row in tqdm(df.iterrows(), total=total_rows, desc=f"[{db_key}] 변환 중"):
        raw_title = str(row['Title']).strip()
        raw_item  = str(row['Item']).strip()
        raw_guide = str(row['Guide']).strip()

        try:
            response = chain.invoke({"title": raw_title, "item": raw_item, "guide": raw_guide})
            text = response.strip()
        except Exception as e:
            print(f"\nLLM 호출 실패 (index={index}): {e} → 원본 텍스트로 폴백")
            text = f"{raw_title} 분류의 {raw_item} 항목에 대한 설계 기준이다. {raw_guide}"

        text_with_category = f"[{raw_title}] {text} (분류: {raw_title})"
        current_chunk_texts.append(text_with_category)

        if (index + 1) % chunk_size == 0 or (index + 1) == total_rows:
            output_path = os.path.join(output_folder, f'final_text_data_{chunk_count}.xlsx')
            pd.DataFrame({"Text": current_chunk_texts}).to_excel(output_path, index=False, engine='openpyxl')
            print(f"\n[저장 완료] {output_path} (누적 {index + 1}행)")
            current_chunk_texts = []
            chunk_count += 1

    print(f"[{db_key}] 자연어 변환 완료.")


def run_single_db(domain_data_root, domain_key, db_key, use_think, rebuild_chroma):
    """단일 DB 전처리 → LLM 변환 → ChromaDB 구축 순차 실행"""
    from vector_store import prepare_knowledge_base, _get_persist_dir

    final_path  = os.path.join(domain_data_root, 'result', db_key, 'preprocessed_data_final.xlsx')
    persist_dir = _get_persist_dir(domain_key, db_key)

    print(f"\n{'='*50}")
    print(f"  처리 시작: [{domain_key}/{db_key}]")
    print(f"{'='*50}")

    # [1단계] 전처리
    if not os.path.exists(final_path):
        print(f"\n=== [1단계] [{db_key}] 전처리 시작 ===")
        csv_folder = convert_all_excel_to_csv(domain_data_root, db_key)
        semi_file  = process_and_save_checklists(domain_data_root, db_key, csv_folder)
        if semi_file:
            run_2nd_preprocessing(domain_data_root, db_key, semi_file)
        else:
            print(f"❌ [{db_key}] 전처리 실패 → 건너뜁니다.")
            return False
    else:
        print(f"\n=== [1단계 스킵] [{db_key}] 기존 전처리 파일을 사용합니다. ===")

    # [2단계] LLM 자연어 변환
    print(f"\n=== [2단계] [{db_key}] LLM 자연어 변환 시작 ===")
    transform_to_natural_text(domain_data_root, db_key, use_think=use_think)

    # [3단계] ChromaDB 구축
    if rebuild_chroma:
        print(f"\n=== [3단계] [{db_key}] ChromaDB 구축 시작 ===")
        if os.path.exists(persist_dir):
            shutil.rmtree(persist_dir)
            print(f"기존 ChromaDB 삭제 완료: {persist_dir}")
        prepare_knowledge_base(domain_key, db_key)
        print(f"✅ [{domain_key}/{db_key}] ChromaDB 구축 완료.")
    else:
        print(f"\n=== [3단계 스킵] [{db_key}] ChromaDB 를 유지합니다. ===")

    return True


if __name__ == "__main__":
    current_dir  = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(current_dir)
    data_root    = os.path.join(project_root, 'data')

    # domain_registry 로드
    for reg_path in [
        os.path.join(current_dir, 'domain_registry.json'),
        os.path.join(project_root, 'domain_registry.json'),
    ]:
        if os.path.exists(reg_path):
            with open(reg_path, encoding='utf-8') as f:
                domain_registry = json.load(f)
            break
    else:
        print("❌ domain_registry.json 을 찾을 수 없습니다.")
        sys.exit(1)

    print("=" * 50)
    print("등록된 도메인 목록:")
    for dk, dv in domain_registry.items():
        print(f"  [{dk}] {dv['display_name']} — DB: {dv['db_keys']}")
    print("=" * 50)

    # ── 도메인 선택 ───────────────────────────────────────────────
    domain_key = input("\n처리할 도메인 키를 입력하세요: ").strip()
    if domain_key not in domain_registry:
        print(f"❌ '{domain_key}' 는 등록된 도메인이 아닙니다.")
        sys.exit(1)

    domain_config    = domain_registry[domain_key]
    domain_data_root = os.path.join(data_root, domain_key)
    available_dbs    = domain_config.get("db_keys", [])

    print(f"\n[{domain_key}] 사용 가능한 DB: {available_dbs}")

    # ── DB 선택 ───────────────────────────────────────────────────
    keys_input = input(
        "\n처리할 DB 키를 입력하세요."
        "\n  단일: mobile"
        "\n  복수: mobile,folderable"
        "\n  전체: all"
        "\n입력 > "
    ).strip()

    if keys_input.lower() == 'all':
        target_keys = available_dbs
    else:
        target_keys = [k.strip() for k in keys_input.split(',') if k.strip() in available_dbs]
        invalid     = [k.strip() for k in keys_input.split(',') if k.strip() not in available_dbs]
        if invalid:
            print(f"⚠️  [{domain_key}] 에 없는 DB 키는 제외됩니다: {invalid}")

    if not target_keys:
        print("❌ 유효한 DB 키가 없습니다. 종료합니다.")
        sys.exit(1)

    print(f"\n처리 대상 ({len(target_keys)}개): {target_keys}")

    # ── 공통 설정 ─────────────────────────────────────────────────
    answer    = input(f"\n[공통] Thinking 모드를 사용할까요? (y/n, 기본값 n): ").strip().lower()
    use_think = (answer == 'y')
    print(f"      → {'Thinking 모드' if use_think else '빠른 응답 모드 (no_think)'} 선택됨")

    answer         = input(f"\n[공통] ChromaDB 를 새로 구축할까요? (y/n): ").strip().lower()
    rebuild_chroma = (answer == 'y')
    if not rebuild_chroma:
        print("⚠️  ChromaDB 를 유지합니다. 새 데이터가 반영되지 않을 수 있습니다.")

    print("\n설정 완료. 이후 자동으로 실행됩니다. 자리를 비워도 됩니다.")
    print("=" * 50)

    # ── 순차 실행 ─────────────────────────────────────────────────
    success_list, fail_list = [], []
    for db_key in target_keys:
        ok = run_single_db(domain_data_root, domain_key, db_key, use_think, rebuild_chroma)
        (success_list if ok else fail_list).append(db_key)

    print(f"\n{'='*50}")
    print("전체 처리 완료 요약")
    print(f"{'='*50}")
    print(f"✅ 성공 ({len(success_list)}개): {success_list}")
    if fail_list:
        print(f"❌ 실패 ({len(fail_list)}개): {fail_list}")
    print(f"\n앱을 실행하세요: streamlit run src/chatbot_meg.py")
