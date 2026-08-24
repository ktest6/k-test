"""체크리스트 v3 실험(scripts/checklist_lab/*_v3.py)의 계산 규칙 회귀 테스트.

v3 가 앞의 두 실험과 다른 점은 하나다 — **실제 응시자 답안을 보고** 체크리스트를 만든다.
그래서 이번 테스트에서 가장 중요한 것은 성능 숫자가 아니라 **누출 방지**다.
시험 볼 답안이 체크리스트 생성이나 가중치 학습에 한 번이라도 새어 들어가면,
나온 숫자는 실력이 아니라 답을 보고 푼 점수가 된다.

여기서 확인하는 것 여덟:
  ① 예시 답안 고르기 — 점수대가 퍼지는가, 늘 같은 8건이 나오는가
  ② **누출 방지**    — 시험 겹 답안이 생성용 예시에 들어가지 않는가
  ③ 부정형 항목      — 인용으로 근거를 댈 수 없는 항목을 잡아내는가
  ④ 겹 간 닮음       — 다섯 벌이 얼마나 겹치는지 재는 계산이 맞는가
  ⑤ 항목 다듬기      — 상한·중요도·id 충돌 처리
  ⑥ 확률 예비조사    — 갈린 칸을 정확히 세고, **미리 정한 기준**대로 가부를 내는가
  ⑦ 할 일 목록       — 답안 하나가 다섯 벌로 판정되는가, 재현성은 자기 겹 한 벌인가
  ⑧ **J 학습의 누출 방지** — 시험 겹 답안이 학습에 들어가지 않는가

**네트워크를 쓰지 않는다.** LLM 자리에는 답을 정해 둔 가짜 응답을 넣는다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_checklist_lab_v3.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


# 이 실험 테스트는 scripts/checklist_lab 의 학습 코드(sklearn/xgboost)를 임포트한다.
# 운영 requirements 에는 그 라이브러리가 없으므로, 없으면 이 파일 전체를 건너뛴다.
pytest.importorskip("sklearn", reason="checklist_lab 실험 전용 자질/학습 라이브러리 — 운영 CI에는 미설치, 여기서 통째로 건너뛴다")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "checklist_lab"))

from _lab_common import N_FOLDS, assign_folds, human_score, prompt_key  # noqa: E402
from analyze_v3 import learn_per_prompt_v3, v3_records  # noqa: E402
from gen_checklists_v3 import (  # noqa: E402
    MAX_ITEMS_V3,
    NEGATIVE_PATTERNS,
    build_checklist_v3_prompt,
    checklist_similarity,
    fold_agreement,
    format_exemplars,
    items_for,
    looks_negative,
    normalize_items_v3,
    question_similarity,
    select_exemplars,
)
from run_experiment_v3 import (  # noqa: E402
    PROBE_N_SEEDS,
    PROBE_SPLIT_THRESHOLD,
    build_binary_tasks,
    build_soft_tasks,
    judge_binary,
    select_probe_rows,
    summarize_probe,
)


# ── 가짜 데이터 만들기 ───────────────────────────────────────────────────────
def make_row(rid: str, prompt: str, speaker: str, score: int, ref: str = "예시 답안입니다."):
    """목록 파일 한 줄과 같은 모양의 가짜 답안."""
    return {"id": rid, "ref": ref, "prompt": prompt, "task": "ATQ",
            "speaker_id": speaker, "evals": {"content": score}}


def make_checklists(pkey: str, items_per_fold: dict[int, list[dict]]) -> dict:
    """(문항, 겹)마다 항목이 다른 v3 체크리스트 파일 모양."""
    return {pkey: {"prompt_key": pkey, "prompt": "문항", "folds": {
        str(k): {"status": "ok", "items": items, "n_items": len(items)}
        for k, items in items_per_fold.items()}}}


def simple_items(ids: list[str]) -> list[dict]:
    return [{"id": i, "question": f"{i}번을 말했는가?", "category": "정보전달",
             "required": True, "importance": 50} for i in ids]


class FakeClient:
    """정해진 JSON 을 돌려주는 가짜 LLM. 네트워크를 쓰지 않는다."""

    def __init__(self, payload: dict):
        self.payload = payload
        self.calls = 0
        self.model_name = "가짜모델"
        self.available = True

    def generate_json(self, prompt, system_instruction="", response_schema=None, **kwargs):
        self.calls += 1
        self.last_prompt = prompt
        self.last_kwargs = kwargs
        return self.payload


# ── ① 예시 답안 고르기 ───────────────────────────────────────────────────────
def test_예시답안은_점수대가_퍼지게_뽑는다():
    rows = [make_row(f"R{i:03d}", "문항", f"S{i}", i % 6) for i in range(30)]
    picked = select_exemplars(rows, "씨앗", 8)
    scores = sorted(human_score(r) for r in picked)
    assert len(picked) == 8
    # 가장 높은 점수와 가장 낮은 점수가 반드시 들어가야 "무엇이 달랐나"를 볼 수 있다
    assert min(scores) == 0 and max(scores) == 5
    assert len(set(scores)) >= 4


def test_예시답안은_몇_번을_뽑아도_같다():
    rows = [make_row(f"R{i:03d}", "문항", f"S{i}", i % 6) for i in range(30)]
    first = [r["id"] for r in select_exemplars(rows, "씨앗", 8)]
    second = [r["id"] for r in select_exemplars(rows, "씨앗", 8)]
    assert first == second


def test_예시답안_씨앗이_다르면_표본도_달라질_수_있다():
    """겹마다 다른 씨앗을 주므로, 씨앗이 표본에 실제로 반영되는지 확인한다."""
    rows = [make_row(f"R{i:03d}", "문항", f"S{i}", i % 6) for i in range(30)]
    a = [r["id"] for r in select_exemplars(rows, "겹0", 8)]
    b = [r["id"] for r in select_exemplars(rows, "겹1", 8)]
    # 층화로 고정되는 6건은 같고, 무작위 2건 자리에서 갈릴 수 있다
    assert len(set(a) & set(b)) >= 6


def test_답안이_모자라면_있는_것을_다_쓴다():
    rows = [make_row(f"R{i}", "문항", f"S{i}", i % 6) for i in range(5)]
    assert len(select_exemplars(rows, "씨앗", 8)) == 5


def test_예시답안을_보여줄_때_사람_점수를_함께_붙인다():
    rows = [make_row("R1", "문항", "S1", 5, ref="아주 잘 말했습니다.")]
    text = format_exemplars(rows)
    assert "5점" in text and "아주 잘 말했습니다." in text


# ── ② 누출 방지 — 이 실험에서 가장 중요한 검사 ───────────────────────────────
def test_생성용_예시에는_시험_겹_답안이_한_건도_들어가지_않는다():
    """겹 k 의 체크리스트는 겹 k 답안을 보지 않고 만들어져야 한다.

    이것이 깨지면 '답을 보고 시험지를 만든' 것이 되어 성적 자체가 무의미해진다.
    그래서 실제 생성 코드가 쓰는 것과 같은 방식(학습 겹만 걸러 넘기기)을 재현해 확인한다.
    """
    rows = [make_row(f"R{i:03d}", "문항", f"S{i}", i % 6) for i in range(40)]
    fold_of, _ = assign_folds(rows, N_FOLDS)
    for fold in range(N_FOLDS):
        train_rows = [r for r in rows if fold_of[str(r["id"])] != fold]
        picked = select_exemplars(train_rows, f"문항|{fold}")
        assert picked, "학습 겹 답안이 있는데 아무것도 못 골랐다"
        assert all(fold_of[str(r["id"])] != fold for r in picked)


def test_생성_프롬프트에_규칙들이_실제로_들어간다():
    """1·2차에서 얻은 교훈이 프롬프트에서 빠지면 같은 실수를 되풀이한다."""
    rows = [make_row("R1", "문항", "S1", 3)]
    text = build_checklist_v3_prompt("오늘 무엇을 입었어요?", rows)
    assert "오늘 무엇을 입었어요?" in text
    # 부정형 금지 (2차에서 인용 폐기가 무더기로 났던 원인)
    assert "부정형" in text and "긍정형" in text
    # 발음·문법 항목 금지 (다른 자질이 담당하므로 중복 평가)
    assert "발음" in text and "문법" in text
    # 억지 항목 금지와 항목 수 상한
    assert "억지 항목" in text and str(MAX_ITEMS_V3) in text
    # 점수를 가르는 항목 우선
    assert "점수대를 가르는" in text


# ── ③ 부정형 항목 ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("question", [
    "불필요한 정보를 배제했는가?",
    "주제를 벗어나지 않았는가?",
    "군더더기 없이 답했는가?",
])
def test_부정형_항목을_잡아낸다(question):
    assert looks_negative(question) is True


@pytest.mark.parametrize("question", [
    "쇼핑 장소를 구체적으로 말했는가?",
    "그 이유를 근거와 함께 설명했는가?",
])
def test_긍정형_항목은_잡지_않는다(question):
    assert looks_negative(question) is False


def test_부정형_항목은_버리지_않고_표시만_한다():
    """조용히 버리면 체크리스트가 통째로 비는 문항이 생기고, 규칙 위반 기록도 사라진다."""
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "핵심을 말했는가?", "category": "정보전달",
         "required": True, "importance": 80, "discriminates": [1, 2]},
        {"id": 2, "question": "군더더기를 배제했는가?", "category": "상황판단",
         "required": False, "importance": 40, "discriminates": [1]},
    ]}
    items, warnings, _ = normalize_items_v3(payload, 8)
    assert len(items) == 2
    assert items[0]["negative"] is False and items[1]["negative"] is True
    assert any("부정형" in w for w in warnings)


def test_금지_말버릇_목록이_비어_있지_않다():
    assert len(NEGATIVE_PATTERNS) >= 5


# ── ④ 겹 간 닮음 ─────────────────────────────────────────────────────────────
def test_같은_문구는_닮음_1_다른_문구는_낮다():
    assert question_similarity("장소를 말했는가?", "장소를 말했는가?") == pytest.approx(1.0)
    assert question_similarity("장소를 말했는가?", "옷 색깔을 묘사했는가?") < 0.3


def test_꼬리말만_같은_두_항목은_닮았다고_보지_않는다():
    """'~했는가' 는 모든 항목에 붙는 말이라, 이것 때문에 닮아 보이면 안 된다."""
    assert question_similarity("장소를 말했는가?", "이유를 설명했는가?") < 0.35


def test_체크리스트_닮음은_한_항목을_두_번_짝지어_주지_않는다():
    """짝짓기를 안 막으면 한쪽 항목 하나가 여러 항목의 짝이 되어 닮음이 부풀려진다."""
    a = [{"question": "장소를 말했는가?"}]
    b = [{"question": "장소를 말했는가?"}, {"question": "장소를 말했는가?"}]
    result = checklist_similarity(a, b)
    # 짝은 하나만 성립하고, 남은 항목은 닮음 0 으로 센다 → 짝지어진 비율 0.5
    assert result["matched"] == pytest.approx(0.5)


def test_다섯_벌이_모두_같으면_겹_간_닮음이_1이다():
    items = simple_items(["1", "2", "3"])
    folds = {str(k): {"status": "ok", "items": items} for k in range(N_FOLDS)}
    agree = fold_agreement(folds)
    assert agree["n_pairs"] == 10          # 5벌에서 나오는 쌍의 수
    assert agree["mean_similarity"] == pytest.approx(1.0)
    assert agree["matched_rate"] == pytest.approx(1.0)


# ── ⑤ 항목 다듬기 ────────────────────────────────────────────────────────────
def test_항목이_상한을_넘으면_중요도가_높은_것부터_남긴다():
    payload = {"score_differences": [], "checklist": [
        {"id": i, "question": f"{i}번을 말했는가?", "category": "정보전달",
         "required": False, "importance": i, "discriminates": [1]}
        for i in range(1, MAX_ITEMS_V3 + 4)
    ]}
    items, warnings, _ = normalize_items_v3(payload, 8)
    assert len(items) == MAX_ITEMS_V3
    assert items[0]["importance"] == MAX_ITEMS_V3 + 3
    assert any("상한" in w for w in warnings)


def test_id가_겹치면_판정을_짝지을_수_있게_바꾼다():
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "가를 말했는가?", "category": "정보전달",
         "required": True, "importance": 80, "discriminates": [1]},
        {"id": 1, "question": "나를 말했는가?", "category": "정보전달",
         "required": True, "importance": 70, "discriminates": [2]},
    ]}
    items, warnings, _ = normalize_items_v3(payload, 8)
    assert len({it["id"] for it in items}) == 2
    assert any("겹쳐" in w for w in warnings)


def test_모든_예시를_통과한_항목은_변별하지_못한다고_표시한다():
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "가를 말했는가?", "category": "정보전달", "required": True,
         "importance": 80, "discriminates": list(range(1, 9))},
        {"id": 2, "question": "나를 말했는가?", "category": "정보전달", "required": True,
         "importance": 80, "discriminates": [1, 2, 3]},
    ]}
    items, _, _ = normalize_items_v3(payload, 8)
    assert items[0]["discriminating"] is False
    assert items[1]["discriminating"] is True


def test_범위_밖_예시_번호는_버린다():
    payload = {"score_differences": [], "checklist": [
        {"id": 1, "question": "가를 말했는가?", "category": "정보전달", "required": True,
         "importance": 80, "discriminates": [0, 3, 99, "가"]},
    ]}
    items, _, _ = normalize_items_v3(payload, 8)
    assert items[0]["exemplar_hits"] == [3]


def test_체크리스트_읽기는_실패한_벌을_돌려주지_않는다():
    data = {"P1": {"folds": {
        "0": {"status": "ok", "items": simple_items(["1"])},
        "1": {"status": "failed", "items": []},
    }}}
    assert len(items_for(data, "P1", 0)) == 1
    assert items_for(data, "P1", 1) == []
    assert items_for(data, "P1", 4) == []


# ── ⑥ 확률 예비조사 ──────────────────────────────────────────────────────────
def probe_record(rid: str, temp: float, seed_i: int, mets: dict[str, int]) -> dict:
    return {"id": rid, "method": f"PROBE_t{temp}", "pass": f"s{seed_i}", "status": "ok",
            "temperature": temp,
            "items": [{"cid": cid, "met": met} for cid, met in mets.items()]}


def test_만장일치면_확률_대체재를_쓸_수_없다고_판정한다():
    """이번 실험의 갈림길. 안 갈리면 확률은 O/X 와 같은 값이라 얻는 것이 없다."""
    records = [probe_record("R1", 1.0, i, {"1": 1, "2": 0}) for i in range(PROBE_N_SEEDS)]
    summary = summarize_probe(records)
    assert summary["n_cells_total"] == 2
    assert summary["n_split_cells_total"] == 0
    assert summary["split_rate_overall"] == 0.0
    assert summary["soft_pass_enabled"] is False


def test_충분히_갈리면_소프트_패스를_켠다():
    records = [probe_record("R1", 1.0, i, {"1": 1, "2": i % 2}) for i in range(PROBE_N_SEEDS)]
    summary = summarize_probe(records)
    assert summary["n_split_cells_total"] == 1
    assert summary["split_rate_overall"] == pytest.approx(0.5)
    assert summary["split_rate_overall"] >= PROBE_SPLIT_THRESHOLD
    assert summary["soft_pass_enabled"] is True
    assert summary["by_temperature"]["1.0"]["split_prob_mean"] == pytest.approx(0.5)


def test_판정_횟수가_모자란_칸은_세지_않는다():
    """표본 수가 다른 칸을 섞으면 '갈린 비율'이 표본 수 차이 때문에 흔들린다."""
    records = [probe_record("R1", 1.0, i, {"1": i % 2}) for i in range(PROBE_N_SEEDS - 1)]
    assert summarize_probe(records)["n_cells_total"] == 0


def test_온도별로_따로_센다():
    records = ([probe_record("R1", 1.0, i, {"1": 1}) for i in range(PROBE_N_SEEDS)]
               + [probe_record("R1", 1.3, i, {"1": i % 2}) for i in range(PROBE_N_SEEDS)])
    summary = summarize_probe(records)
    assert summary["by_temperature"]["1.0"]["split_rate"] == 0.0
    assert summary["by_temperature"]["1.3"]["split_rate"] == 1.0
    assert summary["split_rate_overall"] == pytest.approx(0.5)


def test_예비조사_표본은_중간_점수대만_문항이_섞이게_뽑는다():
    rows = [make_row(f"{p}-{i:02d}", p, f"S{p}{i}", i % 6)
            for p in ("문항A", "문항B", "문항C") for i in range(12)]
    picked = select_probe_rows(rows, 9)
    assert len(picked) == 9
    assert all(1 <= human_score(r) <= 4 for r in picked)
    assert len({r["prompt"] for r in picked}) == 3
    assert [r["id"] for r in select_probe_rows(rows, 9)] == [r["id"] for r in picked]


# ── ⑦ 할 일 목록 ─────────────────────────────────────────────────────────────
def test_답안_하나는_다섯_벌_모두로_판정된다():
    """가중치를 배우려면 같은 체크리스트로 채점된 학습 답안이 있어야 한다."""
    rows = [make_row("A-1", "문항A", "S1", 3)]
    fold_of = {"A-1": 2}
    checklists = make_checklists(prompt_key("문항A"),
                                 {k: simple_items(["1"]) for k in range(N_FOLDS)})
    tasks = build_binary_tasks(rows, fold_of, checklists, "main", {}, own_fold_only=False)
    assert len(tasks) == N_FOLDS
    assert sorted(t["checklist_fold"] for t in tasks) == list(range(N_FOLDS))
    assert {t["fold"] for t in tasks} == {2}


def test_재현성_실행은_자기_겹_한_벌만_돌린다():
    rows = [make_row("A-1", "문항A", "S1", 3)]
    fold_of = {"A-1": 2}
    checklists = make_checklists(prompt_key("문항A"),
                                 {k: simple_items(["1"]) for k in range(N_FOLDS)})
    tasks = build_binary_tasks(rows, fold_of, checklists, "rep1", {}, own_fold_only=True)
    assert len(tasks) == 1 and tasks[0]["checklist_fold"] == 2


def test_이미_성공한_판정은_다시_하지_않는다():
    rows = [make_row("A-1", "문항A", "S1", 3)]
    fold_of = {"A-1": 0}
    checklists = make_checklists(prompt_key("문항A"),
                                 {k: simple_items(["1"]) for k in range(N_FOLDS)})
    done = {("A-1", "B3f0", "main"): {"status": "ok"},
            ("A-1", "B3f1", "main"): {"status": "failed"}}
    tasks = build_binary_tasks(rows, fold_of, checklists, "main", done, own_fold_only=False)
    # 성공한 겹0 은 빠지고, 실패한 겹1 은 다시 한다(그때 운이 나빴을 뿐일 수 있으므로)
    assert sorted(t["checklist_fold"] for t in tasks) == [1, 2, 3, 4]


def test_소프트_패스는_자기_겹으로_씨앗만_바꿔_돈다():
    rows = [make_row("A-1", "문항A", "S1", 3)]
    fold_of = {"A-1": 3}
    checklists = make_checklists(prompt_key("문항A"),
                                 {k: simple_items(["1"]) for k in range(N_FOLDS)})
    tasks = build_soft_tasks(rows, fold_of, checklists, {})
    assert {t["checklist_fold"] for t in tasks} == {3}
    assert len({t["seed"] for t in tasks}) == len(tasks)
    assert all(t["temperature"] > 0 for t in tasks)


# ── 판정 규약 — 근거 인용이 가짜면 충족을 폐기한다 ───────────────────────────
def test_원문에_없는_인용은_폐기되어_미충족이_된다():
    """v1·v2 와 **같은 규약**이어야 세 실험을 나란히 놓을 수 있다."""
    row = make_row("A-1", "문항A", "S1", 3, ref="저는 시장에서 쇼핑을 해요.")
    items = simple_items(["1", "2"])
    fake = FakeClient({"results": [
        {"id": "1", "met": 1, "quote": "시장에서 쇼핑을", "reason": "원문에 있다"},
        {"id": "2", "met": 1, "quote": "백화점에 자주 갑니다", "reason": "원문에 없는 인용"},
    ]})
    out = judge_binary(fake, row, items, throttle=None)
    assert out["status"] == "ok"
    assert out["n_met"] == 1                     # 가짜 인용 하나가 폐기됐다
    assert out["dropped_citations"] == 1
    assert out["items"][0]["met"] == 1 and out["items"][1]["met"] == 0
    # 근거 위치를 반드시 남긴다 — 근거 없는 점수는 이 프로젝트에서 결함이다
    assert out["items"][0]["start"] is not None


def test_체크리스트가_없으면_판정하지_않는다():
    row = make_row("A-1", "문항A", "S1", 3)
    out = judge_binary(FakeClient({"results": []}), row, [], throttle=None)
    assert out["status"] == "no_checklist"


def test_온도를_주면_그대로_전달된다():
    """예비조사는 일부러 온도를 올려야 한다. 그 값이 실제로 넘어가는지 확인한다."""
    row = make_row("A-1", "문항A", "S1", 3, ref="저는 시장에서 쇼핑을 해요.")
    fake = FakeClient({"results": [{"id": "1", "met": 0, "quote": "", "reason": ""}]})
    judge_binary(fake, row, simple_items(["1"]), throttle=None, temperature=1.3, seed=7)
    assert fake.last_kwargs["temperature"] == 1.3
    assert fake.last_kwargs["seed"] == 7


# ── ⑧ J 학습의 누출 방지 ─────────────────────────────────────────────────────
def build_j_fixture():
    """문항 1종·답안 40건. 항목 1 이 점수와 맞물리고 항목 2 는 잡음이다."""
    ids = [f"R{i:03d}" for i in range(40)]
    rows_by_id = {rid: {"id": rid, "prompt": "문항A", "ref": "가나다",
                        "speaker_id": f"S{i}", "evals": {"content": i % 6}}
                  for i, rid in enumerate(ids)}
    fold_of = {rid: i % N_FOLDS for i, rid in enumerate(ids)}
    prompt_of = {rid: "P" for rid in ids}
    checklists = make_checklists("P", {k: simple_items(["1", "2"]) for k in range(N_FOLDS)})
    recs = {}
    for i, rid in enumerate(ids):
        for k in range(N_FOLDS):
            recs[(rid, k)] = {"items": [{"cid": "1", "met": 1 if i % 6 >= 3 else 0},
                                        {"cid": "2", "met": i % 2}]}
    return ids, rows_by_id, fold_of, prompt_of, checklists, recs


def test_J는_모든_답안에_0에서_5_사이의_점수를_낸다():
    ids, rows_by_id, fold_of, prompt_of, checklists, recs = build_j_fixture()
    preds, _ = learn_per_prompt_v3(recs, rows_by_id, fold_of, prompt_of, checklists)
    assert len(preds) == len(ids)
    assert all(0 <= v <= 5 for v in preds.values())


def test_J는_시험_겹_답안을_학습에_쓰지_않는다():
    """겹 k 를 예측할 때 학습 표본은 정확히 '겹 k 가 아닌 답안'이어야 한다."""
    ids, rows_by_id, fold_of, prompt_of, checklists, recs = build_j_fixture()
    _, learned = learn_per_prompt_v3(recs, rows_by_id, fold_of, prompt_of, checklists)
    for info in learned["P"]["folds"]:
        expected = sum(1 for r in ids if fold_of[r] != info["fold"])
        assert info["n_train"] == expected
        assert info["n_test"] == len(ids) - expected


def test_J는_점수와_맞물린_항목에_더_큰_비중을_준다():
    ids, rows_by_id, fold_of, prompt_of, checklists, recs = build_j_fixture()
    _, learned = learn_per_prompt_v3(recs, rows_by_id, fold_of, prompt_of, checklists)
    for info in learned["P"]["folds"]:
        assert info["coefficients"]["1"] > info["coefficients"]["2"]


def test_J는_배운_비중을_근거로_남긴다():
    """점수만 있고 근거가 없으면 이 프로젝트에서는 결함이다."""
    ids, rows_by_id, fold_of, prompt_of, checklists, recs = build_j_fixture()
    _, learned = learn_per_prompt_v3(recs, rows_by_id, fold_of, prompt_of, checklists)
    info = learned["P"]["folds"][0]
    assert set(info["coefficients"]) == {"1", "2"}
    assert set(info["questions"]) == {"1", "2"}
    assert info["alpha"] is not None


def test_J는_겹마다_다른_체크리스트를_쓴다():
    """겹마다 항목 수가 다르면 배운 비중의 개수도 그만큼 달라야 한다."""
    ids, rows_by_id, fold_of, prompt_of, _, _ = build_j_fixture()
    checklists = make_checklists("P", {0: simple_items(["1"]),
                                       1: simple_items(["1", "2"]),
                                       2: simple_items(["1", "2", "3"]),
                                       3: simple_items(["1", "2"]),
                                       4: simple_items(["1"])})
    recs = {}
    for i, rid in enumerate(ids):
        for k in range(N_FOLDS):
            recs[(rid, k)] = {"items": [{"cid": c, "met": 1 if i % 6 >= 3 else 0}
                                        for c in ("1", "2", "3")]}
    _, learned = learn_per_prompt_v3(recs, rows_by_id, fold_of, prompt_of, checklists)
    sizes = {info["fold"]: len(info["coefficients"]) for info in learned["P"]["folds"]}
    assert sizes == {0: 1, 1: 2, 2: 3, 3: 2, 4: 1}


def test_판정_읽기는_성공한_main_판정만_겹_번호와_함께_돌려준다():
    judgments = {
        ("A-1", "B3f0", "main"): {"status": "ok", "items": []},
        ("A-1", "B3f3", "main"): {"status": "ok", "items": []},
        ("A-1", "B3f1", "main"): {"status": "failed", "items": []},
        ("A-1", "B3f2", "rep1"): {"status": "ok", "items": []},
        ("A-1", "PROBE_t1.0", "s0"): {"status": "ok", "items": []},
    }
    assert sorted(v3_records(judgments, "main")) == [("A-1", 0), ("A-1", 3)]
    assert sorted(v3_records(judgments, "rep1")) == [("A-1", 2)]
