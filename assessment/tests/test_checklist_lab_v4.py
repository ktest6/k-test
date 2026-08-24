"""체크리스트 v4 실험(scripts/checklist_lab/*_v4.py)의 계산 규칙 회귀 테스트.

v4 가 앞의 세 실험과 다른 점은 둘이다.
  · 체크리스트 항목을 **10개**로 늘리고 어려운 항목을 섞으라고 시킨다
  · 판정을 O/X 가 아니라 **logprobs 정규화 확률**로 받는다

그래서 이번 테스트에서 가장 중요한 것은 두 가지다.
  ① **확률을 만드는 계산이 맞는가** — "아니오"가 첫 토큰 '아' 로 잘려 오는 것을
     제대로 접어서 세는가. 여기가 틀리면 이번 실험의 모든 숫자가 뒤집힌다.
  ② **누출 방지** — 시험 겹 답안이 체크리스트 생성이나 가중치 학습에 새어
     들어가지 않는가. 새면 나온 숫자는 실력이 아니라 답을 보고 푼 점수다.

여기서 확인하는 것 아홉:
  ① 첫 토큰 접기      — '아' 를 아니오로, ' 예'·'Yes' 를 예로 세는가
  ② 정규화 확률       — 흩어진 표기를 합치고, 양쪽이 없으면 **임의값을 채우지 않는가**
  ③ 확률과 O/X 의 관계 — 같은 판정에서 나오는가(p>0.5)
  ④ 예시 답안 고르기  — 12건, 점수대가 퍼지는가, 늘 같은 표본이 나오는가
  ⑤ **누출 방지**     — 시험 겹 답안이 생성용 예시에 들어가지 않는가 + 감사기가 잡는가
  ⑥ 항목 다듬기       — 난이도·상한·부정형·요구 미달 경고
  ⑦ 할 일 목록·이어서 하기 — 항목 한 칸이 한 건인가, 끝난 칸만 건너뛰는가
  ⑧ 비용 감시         — 실제 청구액을 더해 상한에서 멈추는가
  ⑨ **Q 학습의 누출 방지** — 시험 겹 답안이 학습에 들어가지 않는가

**네트워크를 쓰지 않는다.** LLM 자리에는 답을 정해 둔 가짜 응답을 넣는다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_checklist_lab_v4.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


# 이 실험 테스트는 scripts/checklist_lab 의 학습 코드(sklearn/xgboost)를 임포트한다.
# 운영 requirements 에는 그 라이브러리가 없으므로, 없으면 이 파일 전체를 건너뛴다.
pytest.importorskip("sklearn", reason="checklist_lab 실험 전용 자질/학습 라이브러리 — 운영 CI에는 미설치, 여기서 통째로 건너뛴다")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "checklist_lab"))

from _lab_common import N_FOLDS, assign_folds, human_score, prompt_key  # noqa: E402
from analyze_v4 import (  # noqa: E402
    binary_vector_v4,
    learn_per_prompt_v4,
    prob_distribution,
    prob_vector,
    v4_cells,
)
from gen_checklists_v4 import (  # noqa: E402
    MAX_ITEMS_V4,
    MIN_HARD_ITEMS,
    N_EXEMPLARS_V4,
    TARGET_ITEMS_V4,
    audit_leakage,
    build_checklist_v4_prompt,
    format_exemplars,
    items_for_v4,
    normalize_items_v4,
    select_exemplars_v4,
)
from run_experiment_v4 import (  # noqa: E402
    CostGuard,
    build_judge_prompt_v4,
    build_tasks_v4,
    fold_token,
    normalized_yes_prob,
    record_key_v4,
)


# ── 도우미 ───────────────────────────────────────────────────────────────────
def make_rows(n_per_prompt: int = 30, n_prompts: int = 2) -> list[dict]:
    """가짜 답안 목록을 만든다. 사람 점수는 0~5 를 골고루 돌려 준다."""
    rows = []
    for p in range(n_prompts):
        for i in range(n_per_prompt):
            rows.append({
                "id": f"S{p}{i:03d}-M-3-VI-B-ATQ00{p}-000{i:03d}",
                "speaker_id": f"S{p}{i:03d}",
                "prompt": f"문항{p} 지시문입니다.",
                "ref": "저는 어제 시장에 가서 사과를 샀습니다. " * (i % 4 + 1),
                "evals": {"content": i % 6},
            })
    return rows


def cand(token: str, prob: float) -> dict:
    """top_logprobs 후보 하나를 만든다(확률을 로그로 바꿔 넣는다)."""
    return {"token": token, "logprob": math.log(prob)}


# ── ① 첫 토큰 접기 ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("token,expected", [
    ("예", "yes"), (" 예", "yes"), ("예.", "yes"), ("네", "yes"),
    ("Yes", "yes"), ("yes", "yes"), ("y", "yes"), ("응", "yes"),
    # ★ 실측: "아니오"는 첫 토큰이 '아' 한 글자로 잘려 온다. 여기가 이 실험의 급소다
    ("아", "no"), ("아니", "no"), ("아니오", "no"), (" 아니", "no"),
    ("No", "no"), ("no", "no"), ("n", "no"),
    ("은", ""), ("그", ""), ("", ""), ("   ", ""), ("\n", ""),
])
def test_fold_token(token, expected):
    """첫 토큰 후보를 '예 쪽'·'아니오 쪽'·'어느 쪽도 아님'으로 정확히 가른다."""
    assert fold_token(token) == expected


# ── ② 정규화 확률 ────────────────────────────────────────────────────────────
def test_normalized_prob_basic():
    """p = 예쪽 / (예쪽 + 아니오쪽). 나머지 확률은 계산에서 뺀다."""
    p, detail = normalized_yes_prob([cand("예", 0.6), cand("아", 0.2), cand("은", 0.2)])
    assert p == pytest.approx(0.75)
    assert detail["other_mass"] == pytest.approx(0.2)


def test_normalized_prob_folds_scattered_spellings():
    """'예'·' 예'·'네' 로 흩어진 확률을 하나로 합친다.

    합치지 않으면 0.3/(0.3+0.4)=0.43 이 되어 '아니오'로 뒤집힌다.
    """
    p, _ = normalized_yes_prob([cand("예", 0.3), cand(" 예", 0.2), cand("네", 0.1),
                                cand("아", 0.4)])
    assert p == pytest.approx(0.6)


def test_normalized_prob_matches_measured_shapes():
    """실측 응답과 같은 모양에서 1 과 0 에 가까운 값이 나온다."""
    yes, _ = normalized_yes_prob([cand("예", 0.999), cand("네", 0.001)])
    no, _ = normalized_yes_prob([cand("아", 0.9999), cand("예", 0.0001)])
    assert yes > 0.99
    assert no < 0.01


def test_normalized_prob_returns_none_when_no_label():
    """양쪽 어디에도 안 걸리면 None 이다. **임의로 0.5 를 채우지 않는다.**

    모르는 것을 '반반'이라고 적으면 그것이 데이터가 되어 버린다.
    """
    p, _ = normalized_yes_prob([cand("은", 0.5), cand("그", 0.5)])
    assert p is None
    assert normalized_yes_prob([])[0] is None


def test_normalized_prob_ignores_broken_candidates():
    """logprob 을 숫자로 못 읽는 후보는 조용히 건너뛴다(계산이 터지지 않는다)."""
    p, _ = normalized_yes_prob([cand("예", 0.8), {"token": "아", "logprob": None},
                                cand("아", 0.2)])
    assert p == pytest.approx(0.8)


# ── ③ 확률과 O/X 는 같은 판정에서 나온다 ─────────────────────────────────────
@pytest.mark.parametrize("p,met", [(0.999, 1), (0.51, 1), (0.5, 0), (0.49, 0), (0.001, 0)])
def test_met_is_derived_from_same_probability(p, met):
    """O/X 는 같은 호출의 확률을 0.5 로 자른 것이다 — 판정이 아니라 읽는 법만 다르다."""
    assert int(p > 0.5) == met


# ── ④ 예시 답안 고르기 ───────────────────────────────────────────────────────
def test_select_exemplars_v4_is_12_and_spread():
    """12건을 뽑고, 가장 높은 점수와 가장 낮은 점수가 모두 들어간다."""
    rows = make_rows(n_per_prompt=30, n_prompts=1)
    picked = select_exemplars_v4(rows, "씨앗", N_EXEMPLARS_V4)
    scores = [human_score(r) for r in picked]
    assert len(picked) == N_EXEMPLARS_V4
    assert min(scores) == 0 and max(scores) == 5
    # 점수대가 한쪽으로 쏠리지 않는다(적어도 네 가지 점수가 들어간다)
    assert len(set(scores)) >= 4


def test_select_exemplars_v4_is_deterministic():
    """같은 입력·같은 씨앗이면 늘 같은 12건이 나온다(표본이 흔들리면 비교가 깨진다)."""
    rows = make_rows(n_per_prompt=30, n_prompts=1)
    a = [r["id"] for r in select_exemplars_v4(rows, "씨앗", N_EXEMPLARS_V4)]
    b = [r["id"] for r in select_exemplars_v4(rows, "씨앗", N_EXEMPLARS_V4)]
    assert a == b


def test_select_exemplars_v4_returns_all_when_fewer():
    """학습 답안이 12건보다 적으면 있는 대로 다 쓴다(터지지 않는다)."""
    rows = make_rows(n_per_prompt=5, n_prompts=1)
    assert len(select_exemplars_v4(rows, "씨앗", N_EXEMPLARS_V4)) == 5


# ── ⑤ 누출 방지 (이 실험의 생명줄) ───────────────────────────────────────────
def test_exemplars_never_include_test_fold_answers():
    """겹 k 의 체크리스트를 만들 때 겹 k 답안은 **한 건도** 들어가지 않는다."""
    rows = make_rows(n_per_prompt=30, n_prompts=2)
    fold_of, _ = assign_folds(rows, N_FOLDS)
    by_prompt: dict[str, list[dict]] = {}
    for r in rows:
        by_prompt.setdefault(prompt_key(r["prompt"]), []).append(r)

    for pkey, items in by_prompt.items():
        for fold in range(N_FOLDS):
            train = [r for r in items if fold_of[str(r["id"])] != fold]
            picked = select_exemplars_v4(train, f"{pkey}|{fold}", N_EXEMPLARS_V4)
            assert all(fold_of[str(r["id"])] != fold for r in picked), \
                f"{pkey} 겹{fold} 에 시험 겹 답안이 섞였다"


def test_audit_leakage_flags_dirty_and_passes_clean():
    """감사기가 시험 겹 답안 혼입과 '모르는 id' 를 둘 다 잡아낸다."""
    fold_of = {"a": 1, "b": 2, "c": 0}
    clean = {"P1": {"folds": {"0": {"status": "ok", "exemplar_ids": ["a", "b"], "items": []}}}}
    assert audit_leakage(clean, fold_of)["n_leaked"] == 0
    assert audit_leakage(clean, fold_of)["clean"] is True

    dirty = {"P1": {"folds": {"0": {"status": "ok", "exemplar_ids": ["a", "c"], "items": []}}}}
    result = audit_leakage(dirty, fold_of)
    assert result["n_leaked"] == 1
    assert result["clean"] is False
    assert result["leaked_examples"][0]["id"] == "c"

    unknown = {"P1": {"folds": {"0": {"status": "ok", "exemplar_ids": ["zzz"], "items": []}}}}
    assert audit_leakage(unknown, fold_of)["n_leaked"] == 1


def test_audit_skips_failed_checklists():
    """만들다 실패한 벌은 감사 대상에서 뺀다(항목이 없어 판정에 쓰이지 않는다)."""
    data = {"P1": {"folds": {"0": {"status": "failed", "exemplar_ids": ["c"], "items": []}}}}
    result = audit_leakage(data, {"c": 0})
    assert result["n_checklists_checked"] == 0
    assert result["n_leaked"] == 0


# ── ⑥ 항목 다듬기 ────────────────────────────────────────────────────────────
def _payload(n_items: int, n_hard: int = MIN_HARD_ITEMS) -> dict:
    return {"score_differences": ["5점과 2점의 차이"], "checklist": [
        {"id": i, "question": f"항목 {i} 를 말했는가?", "category": "정보전달",
         "difficulty": "어려움" if i <= n_hard else "보통",
         "required": False, "importance": 100 - i, "discriminates": [1, 2]}
        for i in range(1, n_items + 1)]}


def test_normalize_keeps_ten_items():
    """목표대로 10개가 오면 10개가 그대로 남는다(v3 는 상한 8이라 잘렸다)."""
    items, warns, diffs = normalize_items_v4(_payload(TARGET_ITEMS_V4), N_EXEMPLARS_V4)
    assert len(items) == TARGET_ITEMS_V4
    assert diffs == ["5점과 2점의 차이"]
    assert not any("목표" in w for w in warns)
    assert not any("어려움 항목이" in w for w in warns)


def test_normalize_caps_at_max():
    """상한(12)을 넘으면 중요도가 높은 것부터 남기고 경고를 적는다."""
    items, warns, _ = normalize_items_v4(_payload(20), N_EXEMPLARS_V4)
    assert len(items) == MAX_ITEMS_V4
    assert items[0]["importance"] == 99
    assert any("상한" in w for w in warns)


def test_normalize_warns_when_requirements_unmet():
    """개수나 어려움 항목이 모자라면 **고치지 않고 경고만** 남긴다.

    시킨 대로 안 나온 사실 자체가 이번 실험의 결과이기 때문이다.
    """
    items, warns, _ = normalize_items_v4(_payload(4, n_hard=0), N_EXEMPLARS_V4)
    assert len(items) == 4                       # 억지로 채우지 않는다
    assert any("목표" in w for w in warns)
    assert any("어려움 항목이" in w for w in warns)


@pytest.mark.parametrize("raw,expected", [
    ("어려움", "어려움"), ("쉬움", "쉬움"), ("보통", "보통"),
    ("상", "어려움"), ("하", "쉬움"), ("중", "보통"),
    ("hard", "어려움"), ("easy", "쉬움"), ("", "보통"), ("알수없음", "보통"),
])
def test_difficulty_is_normalized(raw, expected):
    """난이도를 여러 말로 적어 보내도 세 갈래로 맞춘다(못 읽으면 '보통')."""
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "말했는가?", "category": "정보전달", "difficulty": raw,
         "required": True, "importance": 50, "discriminates": [1]}]}
    items, _, _ = normalize_items_v4(payload, N_EXEMPLARS_V4)
    assert items[0]["difficulty"] == expected


def test_negative_items_are_flagged_not_dropped():
    """부정형 항목은 표시만 하고 버리지 않는다(버리면 체크리스트가 통째로 빌 수 있다)."""
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "불필요한 정보를 배제했는가?", "category": "상황판단",
         "difficulty": "보통", "required": True, "importance": 50, "discriminates": [1]}]}
    items, warns, _ = normalize_items_v4(payload, N_EXEMPLARS_V4)
    assert len(items) == 1
    assert items[0]["negative"] is True
    assert any("부정형" in w for w in warns)


def test_duplicate_item_ids_are_renamed():
    """항목 id 가 겹치면 이름을 바꾼다(안 그러면 판정을 항목에 짝지을 수 없다)."""
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "가?", "category": "정보전달", "difficulty": "보통",
         "required": False, "importance": 50, "discriminates": [1]},
        {"id": 1, "question": "나?", "category": "정보전달", "difficulty": "보통",
         "required": False, "importance": 40, "discriminates": [2]}]}
    items, warns, _ = normalize_items_v4(payload, N_EXEMPLARS_V4)
    assert [it["id"] for it in items] == ["1", "1b"]
    assert any("겹쳐" in w for w in warns)


def test_prompt_carries_scores_and_requirements():
    """생성 지시문에 답안·사람 점수·개수 요구·난이도 요구가 실제로 들어간다."""
    rows = make_rows(n_per_prompt=12, n_prompts=1)
    text = build_checklist_v4_prompt("문항 지시문입니다.", rows)
    assert "문항 지시문입니다." in text
    assert "사람 채점 점수" in format_exemplars(rows)
    assert str(TARGET_ITEMS_V4) in text
    assert str(MIN_HARD_ITEMS) in text
    assert "어려움" in text
    # 출력 예시의 중괄호가 살아 있어야 한다(.format 을 쓰면 여기가 깨진다)
    assert '"checklist"' in text


# ── ⑦ 할 일 목록·이어서 하기 ─────────────────────────────────────────────────
def _fake_checklists(n_items: int = 3) -> dict:
    return {prompt_key("문항0 지시문입니다."): {"folds": {
        str(k): {"status": "ok", "items": [
            {"id": str(i), "question": f"항목{i}?", "difficulty": "보통", "importance": 50}
            for i in range(1, n_items + 1)]}
        for k in range(N_FOLDS)}}}


def test_tasks_are_one_per_item_per_fold():
    """답안 하나가 (겹 5개 × 항목 수)만큼의 할 일이 된다 — 항목마다 호출 1회다."""
    rows = make_rows(n_per_prompt=1, n_prompts=1)
    rows[0]["prompt"] = "문항0 지시문입니다."
    fold_of = {str(rows[0]["id"]): 2}
    tasks = build_tasks_v4(rows, fold_of, _fake_checklists(3), "main", {}, False)
    assert len(tasks) == N_FOLDS * 3


def test_repro_tasks_use_own_fold_only():
    """재현성 실행은 자기 겹 체크리스트 한 벌만 쓴다(실제 채점 배치만 되풀이한다)."""
    rows = make_rows(n_per_prompt=1, n_prompts=1)
    rows[0]["prompt"] = "문항0 지시문입니다."
    fold_of = {str(rows[0]["id"]): 2}
    tasks = build_tasks_v4(rows, fold_of, _fake_checklists(3), "rep1", {}, True)
    assert len(tasks) == 3
    assert all(t["checklist_fold"] == 2 for t in tasks)


def test_resume_skips_only_successful_cells():
    """이미 성공한 칸만 건너뛴다. 실패로 적힌 칸은 다시 한다."""
    rows = make_rows(n_per_prompt=1, n_prompts=1)
    rows[0]["prompt"] = "문항0 지시문입니다."
    rid = str(rows[0]["id"])
    fold_of = {rid: 2}
    checklists = _fake_checklists(3)

    done_ok = {(rid, "0", "1", "main"): {"status": "ok"}}
    done_bad = {(rid, "0", "1", "main"): {"status": "failed"}}
    assert len(build_tasks_v4(rows, fold_of, checklists, "main", done_ok, False)) == N_FOLDS * 3 - 1
    assert len(build_tasks_v4(rows, fold_of, checklists, "main", done_bad, False)) == N_FOLDS * 3


def test_record_key_separates_items_and_folds():
    """결과 줄의 열쇠에 항목과 겹이 모두 들어간다(한 칸씩 이어서 하기 위해서다)."""
    key = record_key_v4({"id": "A-1", "checklist_fold": 3, "item_id": "2", "pass": "main"})
    assert key == ("A-1", "3", "2", "main")
    other = record_key_v4({"id": "A-1", "checklist_fold": 3, "item_id": "5", "pass": "main"})
    assert key != other


def test_judge_prompt_asks_one_item():
    """판정 지시문은 항목을 **하나만** 묻는다(여러 개를 물으면 확률이 더러워진다)."""
    text = build_judge_prompt_v4("문항 지시문", "저는 시장에 갔습니다", "장소를 말했는가?")
    assert text.count("[확인할 항목]") == 1
    assert "저는 시장에 갔습니다" in text
    assert "장소를 말했는가?" in text
    assert "'예' 또는 '아니오'" in text


# ── ⑧ 비용 감시 ──────────────────────────────────────────────────────────────
def test_cost_guard_stops_at_limit():
    """실제 청구액을 더해 상한에 닿으면 멈춤 표시가 선다."""
    guard = CostGuard(0.01)
    guard.add({"cost": 0.004, "prompt_tokens": 100, "completion_tokens": 1})
    assert guard.stopped is False
    guard.add({"cost": 0.007, "prompt_tokens": 100, "completion_tokens": 1})
    assert guard.stopped is True
    snap = guard.snapshot()
    assert snap["cost_usd"] == pytest.approx(0.011)
    assert snap["prompt_tokens"] == 200
    assert snap["n_calls"] == 2


def test_cost_guard_survives_missing_usage():
    """비용 정보가 없는 응답이 와도 터지지 않는다(0원으로 센다)."""
    guard = CostGuard(1.0)
    guard.add({})
    guard.add(None)
    assert guard.snapshot()["cost_usd"] == 0.0
    assert guard.snapshot()["n_calls"] == 2


# ── ⑨ 벡터 만들기와 Q 학습 ───────────────────────────────────────────────────
def test_vectors_follow_checklist_order():
    """벡터는 항목 순서를 체크리스트 파일 기준으로 고정한다."""
    items = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    cell = {"2": {"p_yes": 0.2, "met": 0}, "1": {"p_yes": 0.9, "met": 1},
            "3": {"p_yes": 0.6, "met": 1}}
    assert prob_vector(cell, items) == [0.9, 0.2, 0.6]
    assert binary_vector_v4(cell, items) == [1.0, 0.0, 1.0]


def test_vector_is_none_when_any_item_missing():
    """항목이 하나라도 비면 None 이다 — 빈 칸을 임의값으로 메우지 않는다."""
    items = [{"id": "1"}, {"id": "2"}]
    assert prob_vector({"1": {"p_yes": 0.9, "met": 1}}, items) is None
    assert binary_vector_v4({"1": {"p_yes": 0.9, "met": 1}}, items) is None
    assert prob_vector({"1": {"p_yes": None}, "2": {"p_yes": 0.2}}, items) is None


def test_v4_cells_groups_by_answer_and_fold():
    """판정 줄을 (답안, 겹) 으로 다시 모으고, 실패한 줄과 다른 실행은 뺀다."""
    judgments = {
        ("A-1", "0", "1", "main"): {"status": "ok", "p_yes": 0.9, "met": 1},
        ("A-1", "0", "2", "main"): {"status": "ok", "p_yes": 0.1, "met": 0},
        ("A-1", "3", "1", "main"): {"status": "ok", "p_yes": 0.5, "met": 0},
        ("A-1", "0", "3", "main"): {"status": "failed"},
        ("A-1", "0", "1", "rep1"): {"status": "ok", "p_yes": 0.8, "met": 1},
    }
    cells = v4_cells(judgments, "main")
    assert sorted(cells) == [("A-1", 0), ("A-1", 3)]
    assert sorted(cells[("A-1", 0)]) == ["1", "2"]


def _learning_fixture():
    """항목 1 만 점수와 맞물리고 항목 2 는 잡음인 가짜 데이터."""
    ids = [f"R{i:03d}" for i in range(40)]
    rows_by_id = {rid: {"id": rid, "prompt": "문항A", "ref": "가나다",
                        "speaker_id": f"S{i}", "evals": {"content": i % 6}}
                  for i, rid in enumerate(ids)}
    fold_of = {rid: i % N_FOLDS for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    checklists = {"P": {"folds": {str(k): {"status": "ok", "items": [
        {"id": "1", "question": "핵심을 말했는가?", "importance": 90, "difficulty": "어려움"},
        {"id": "2", "question": "덧붙였는가?", "importance": 10, "difficulty": "쉬움"},
    ]} for k in range(N_FOLDS)}}}
    vec_by_fold = {k: {rid: [0.95 if (i % 6) >= 3 else 0.05, float(i % 2)]
                       for i, rid in enumerate(ids)} for k in range(N_FOLDS)}
    return ids, rows_by_id, fold_of, prompt_of, checklists, vec_by_fold


def test_q_learning_finds_the_signal_item():
    """점수와 맞물린 항목에 더 큰 비중을 준다(잡음 항목보다 크다)."""
    ids, rows_by_id, fold_of, prompt_of, checklists, vec = _learning_fixture()
    preds, learned = learn_per_prompt_v4(vec, rows_by_id, fold_of, prompt_of,
                                         checklists, ids, "Q")
    assert len(preds) == 40
    assert all(0 <= v <= 5 for v in preds.values())
    coefs = learned["P"]["folds"][0]["coefficients"]
    assert coefs["1"] > coefs["2"]


def test_q_learning_never_trains_on_test_fold():
    """★ 시험 겹 답안은 학습에 들어가지 않는다(학습 표본 = 전체 − 그 겹)."""
    ids, rows_by_id, fold_of, prompt_of, checklists, vec = _learning_fixture()
    _, learned = learn_per_prompt_v4(vec, rows_by_id, fold_of, prompt_of,
                                     checklists, ids, "Q")
    for info in learned["P"]["folds"]:
        n_test = sum(1 for r in ids if fold_of[r] == info["fold"])
        assert info["n_train"] == len(ids) - n_test


def test_q_learning_records_evidence():
    """배운 비중과 함께 **어느 항목의 것인지**가 남는다(근거 없는 점수는 만들지 않는다)."""
    ids, rows_by_id, fold_of, prompt_of, checklists, vec = _learning_fixture()
    _, learned = learn_per_prompt_v4(vec, rows_by_id, fold_of, prompt_of,
                                     checklists, ids, "Q")
    info = learned["P"]["folds"][0]
    assert info["questions"]["1"] == "핵심을 말했는가?"
    assert info["difficulty"]["1"] == "어려움"
    assert set(info["coefficients"]) == {"1", "2"}


def test_q_learning_falls_back_when_too_few_training_rows():
    """배울 것이 모자라면 학습 겹 평균으로 답하고 그 사실을 적어 둔다."""
    ids = [f"R{i}" for i in range(6)]
    rows_by_id = {rid: {"id": rid, "prompt": "문항A", "ref": "가",
                        "speaker_id": rid, "evals": {"content": 3}} for rid in ids}
    fold_of = {rid: i % N_FOLDS for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    checklists = {"P": {"folds": {str(k): {"status": "ok", "items": [
        {"id": "1", "question": "가?", "importance": 50}]} for k in range(N_FOLDS)}}}
    vec = {k: {rid: [0.5] for rid in ids} for k in range(N_FOLDS)}
    preds, learned = learn_per_prompt_v4(vec, rows_by_id, fold_of, prompt_of,
                                         checklists, ids, "Q")
    assert len(preds) == len(ids)
    assert any("모자라" in (info.get("note") or "") for info in learned["P"]["folds"])


# ── 확률 분포 진단 ───────────────────────────────────────────────────────────
def test_prob_distribution_detects_saturation():
    """확률이 0/1 로만 몰려 있으면 '정보 없음'으로 잡아낸다.

    이것이 0 이면 Q 가 Q_bin 을 이길 이유가 애초에 없다는 뜻이라, 결과를 읽는
    첫 번째 숫자가 된다.
    """
    spiky = prob_distribution([0.001] * 50 + [0.999] * 50)
    assert spiky["n_informative"] == 0
    assert spiky["mean_distance_from_extreme"] < 0.01

    spread = prob_distribution([i / 100 for i in range(101)])
    assert spread["rate_informative"] > 0.8
    assert spread["n_middle"] > 0


def test_prob_distribution_bins_sum_to_total():
    """칸막이가 값을 하나도 빠뜨리거나 두 번 세지 않는다."""
    values = [0.0, 0.005, 0.03, 0.1, 0.5, 0.8, 0.97, 0.999, 1.0]
    dist = prob_distribution(values)
    assert sum(b["n"] for b in dist["bins"].values()) == len(values)


# ── 체크리스트 읽기 ──────────────────────────────────────────────────────────
def test_items_for_v4_returns_empty_for_failed_or_missing():
    """실패했거나 없는 (문항, 겹)은 빈 목록이다(빈 채로 판정하지 않게 막는다)."""
    data = {"P1": {"folds": {"0": {"status": "ok", "items": [{"id": "1"}]},
                             "1": {"status": "failed", "items": []}}}}
    assert items_for_v4(data, "P1", 0) == [{"id": "1"}]
    assert items_for_v4(data, "P1", 1) == []
    assert items_for_v4(data, "P1", 4) == []
    assert items_for_v4(data, "없는문항", 0) == []
