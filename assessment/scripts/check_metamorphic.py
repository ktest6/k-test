"""채점기가 두 가지 약속을 지키는지 눈으로 확인하는 도구 (메타모픽 검사).

무엇을 하는 것인가:
같은 답안을 조금씩 바꿔 넣어 보고, 점수가 **바뀌어야 할 때만 바뀌는지**를 본다.
정답표(사람이 매긴 점수)가 없어도 채점기의 잘못을 잡아낼 수 있는 방법이다.

검사하는 약속 두 가지:

  INV(불변) — 뜻이 같은 말로 바꿔 써도 점수는 그대로여야 한다.
              동의어로 갈아 끼우거나 어순을 바꾼 답안에서 점수가 출렁이면,
              그 채점기는 '무슨 말을 했는가'가 아니라 '어떤 낱말을 썼는가'를 보고 있는 것이다.

  DIR(방향) — 무언가를 빼면 **그 영역만** 떨어져야 한다.
              내용 요소를 지웠는데 언어 점수까지 떨어지거나,
              문법 오류를 넣었는데 내용 점수까지 떨어지면 영역이 서로 오염된 것이다.
              영역별 점수를 따로 보여 주는 시험에서 이 오염은 곧 설명 불가능한 점수를 뜻한다.

중요한 성질 두 가지:

  1) 변형은 전부 손으로 박아 둔 고정 문장이다(scripts/metamorphic/cases.json).
     LLM에게 변형을 만들게 하면 돌릴 때마다 문장이 달라져서, 점수가 움직인 이유가
     채점기 때문인지 문장이 달라져서인지 구별할 수 없다.

  2) 이것은 회귀 테스트가 아니라 **관찰 도구**다.
     실패가 나와도 프로그램은 정상 종료(0)하고 표로 보여 준다.
     여기서 나오는 실패는 '고장'이 아니라 '지금 채점기가 이렇게 행동한다'는 관찰 결과이며,
     그중 무엇을 고칠지는 사람이 정한다.

쓰는 법:
    python scripts/check_metamorphic.py              # 전체(쓰기 1세트 + 말하기 1세트)
    python scripts/check_metamorphic.py --quick      # 쓰기 1세트만 (시연용, 2~3분)
    python scripts/check_metamorphic.py --set SPK-001
    python scripts/check_metamorphic.py --no-llm     # LLM 없이 규칙 자질만 (공짜·즉시, 감 잡기용)
    python scripts/check_metamorphic.py --json outputs/metamorphic.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from src.llm.client import GeminiClient
from src.scoring.pipeline import score_submission
from src.scoring.schema import (
    ChecklistItem,
    FeatureSource,
    FeatureStatus,
    ItemInfo,
    Mode,
    ScoreArea,
    ScoreOptions,
    ScoreRequest,
    ScoreResponse,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
CASES_PATH = ROOT / "scripts" / "metamorphic" / "cases.json"

#: 판정 기준. cases.json 의 rules 와 같은 값이며, 여기가 실제로 쓰이는 쪽이다.
#: "같다"고 봐 줄 변동 폭(점)과, "떨어졌다"고 인정할 최소 하락 폭(점).
SAME_TOLERANCE = 5.0
DOWN_THRESHOLD = 5.0

W = 112


def _display_width(text: str) -> int:
    """한글은 화면에서 두 칸을 차지하므로, 표를 맞추려면 글자 수가 아니라 칸 수를 세야 한다."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in text)


def clip(text: str, width: int) -> str:
    """칸보다 긴 글은 잘라 낸다. 표가 어긋나면 여러 줄을 눈으로 비교할 수 없기 때문이다."""
    if _display_width(text) <= width:
        return text
    out = ""
    for ch in text:
        if _display_width(out + ch) > width - 1:
            break
        out += ch
    return out + "…"


def pad(text: str, width: int) -> str:
    """표 한 칸을 정해진 폭으로 맞춘다(한글 폭 반영)."""
    text = clip(text, width - 1)
    return text + " " * max(0, width - _display_width(text))


def rule(title: str = "") -> None:
    if title:
        print("\n" + "=" * W)
        print(f"  {title}")
        print("=" * W)
    else:
        print("-" * W)


def short(text: str, n: int = 90) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n] + "…"


# ---------------------------------------------------------------------------
# 문항과 사례 읽기
# ---------------------------------------------------------------------------


def load_item(item_file: str, item_id: str) -> ItemInfo:
    """items/ 에 등록된 **실제 문항**을 그대로 읽어 온다.

    검사용 문항을 따로 만들지 않는 이유:
    응시자가 실제로 받는 문항과 다른 것으로 검사하면, 여기서 통과해도
    실제 채점이 같게 동작한다는 보장이 없다.
    """
    data = json.loads((ROOT / item_file).read_text(encoding="utf-8"))
    for raw in data["items"]:
        if raw["item_id"] != item_id:
            continue
        return ItemInfo(
            item_id=raw["item_id"],
            prompt=raw["prompt"],
            item_type=raw.get("item_type", "free_response"),
            expected_register=raw.get("expected_register", "any"),
            checklist=[
                ChecklistItem(
                    id=c["id"], description=c["description"], weight=c.get("weight", 1.0)
                )
                for c in raw.get("checklist", [])
            ],
            reference_keywords=raw.get("reference_keywords", []),
        )
    raise SystemExit(f"문항 {item_id} 를 {item_file} 에서 찾지 못했다.")


def load_cases(path: pathlib.Path) -> dict:
    """손으로 박아 둔 변형 사례집을 읽는다."""
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# 채점 한 번과 그 결과 요약
# ---------------------------------------------------------------------------


def llm_stage_failure(response: ScoreResponse, use_llm: bool) -> str | None:
    """이번 채점에서 LLM 단계가 실패했는지 확인하고, 실패했으면 그 사유를 돌려준다.

    왜 이걸 따로 보는가:
    LLM이 죽으면 파이프라인은 멈추지 않고 그 자질을 빼고 남은 가중치를 다시 나눈다.
    그래서 **답안이 그대로여도 점수가 10점 가까이 달라진다.**
    그런 결과를 기준 답안과 비교하면 '채점기가 약속을 어겼다'가 아니라
    '이번 호출이 실패했다'를 재게 되므로, 그 사례는 판정에서 빼야 한다.
    """
    if not use_llm:
        return None

    # 오류 자질(조사·어미·어휘·높임)이 '계산 못 함'으로 오면 LLM 오류 추출이 실패한 것이다
    missing = [
        f.name
        for f in response.features
        if f.id.startswith("error_") and f.status == FeatureStatus.UNAVAILABLE
    ]
    if missing:
        return f"LLM 오류 자질 추출 실패({', '.join(missing)})"

    # 체크리스트가 핵심어 일치로 때워졌다면 내용 판정도 LLM 결과가 아니다
    if any(c.source == FeatureSource.KIWI for c in response.checklist_results):
        return "LLM 체크리스트 판정 실패(핵심어 일치로 대체됨)"

    return None


def score_one(
    answer: str,
    item: ItemInfo,
    mode: Mode,
    submission_id: str,
    client: GeminiClient,
    use_llm: bool,
    retries: int = 1,
) -> tuple[ScoreResponse, str | None]:
    """답안 하나를 실제 채점 파이프라인으로 채점한다.

    전사 보정(STT 교정)은 일부러 켜지 않는다.
    사례집의 답안은 사람이 쓴 고정 문장이지 받아쓰기 결과가 아니라서,
    보정을 켜면 채점기의 행동이 아니라 보정 LLM의 변덕까지 함께 재게 된다.

    LLM 서버가 잠깐 응답하지 않는 일이 실제로 있어서, 그때는 정해진 횟수만큼 다시 해 본다.
    끝까지 실패하면 그 사실(사유)을 점수와 함께 돌려주고, 판정은 하지 않는다.
    """
    request = ScoreRequest(
        submission_id=submission_id,
        mode=mode,
        answer_text=answer,
        item=item,
        options=ScoreOptions(use_llm=use_llm),
        transcript=None,
    )

    response = score_submission(request, client=client)
    failure = llm_stage_failure(response, use_llm)

    # 일시적인 실패일 수 있으므로 잠깐 쉬었다가 다시 부른다
    attempt = 0
    while failure and attempt < retries:
        attempt += 1
        print(f"      (LLM 단계 실패 — 다시 시도 {attempt}/{retries}: {failure})")
        time.sleep(3.0)
        response = score_submission(request, client=client)
        failure = llm_stage_failure(response, use_llm)

    return response, failure


def area_scores(response: ScoreResponse) -> dict[str, float | None]:
    """영역별 점수와 종합 점수를 이름표가 붙은 하나의 꾸러미로 정리한다."""
    by_area = {s.area: s.score for s in response.subscores}
    return {
        "overall": response.overall_score,
        "content": by_area.get(ScoreArea.CONTENT_TASK),
        "language": by_area.get(ScoreArea.LANGUAGE_USE),
    }


def checklist_map(response: ScoreResponse) -> dict[str, int]:
    """체크리스트 항목별 충족 여부(1/0)를 항목 번호로 찾아볼 수 있게 만든다."""
    return {c.id: c.met for c in response.checklist_results}


def contribution_map(response: ScoreResponse) -> dict[tuple[str, str], tuple[str, float]]:
    """어떤 자질이 어느 영역에 몇 점을 보탰는지를 (영역, 자질) 열쇠로 정리한다.

    점수가 왜 움직였는지를 설명하려면 결과 숫자만으로는 부족하고,
    '어느 자질이 몇 점을 덜 보탰는가'까지 짚어야 하기 때문에 이 표를 따로 만든다.
    """
    table: dict[tuple[str, str], tuple[str, float]] = {}
    for sub in response.subscores:
        for c in sub.contributions:
            table[(sub.area.value, c.feature_id)] = (c.feature_name, c.points)
    return table


def error_quotes(response: ScoreResponse, feature_prefix: str = "error_") -> list[str]:
    """LLM이 문법 오류라고 지적하면서 원문에서 따온 부분만 뽑는다.

    점수만 보여 주면 '왜 깎였는지'를 알 수 없다. 우리 프로젝트 규칙상
    감점에는 반드시 원문 근거가 붙어야 하므로, 표에도 그 인용을 함께 싣는다.
    """
    quotes: list[str] = []
    for f in response.features:
        if not f.id.startswith(feature_prefix):
            continue
        if not f.components.get("error_count"):
            continue
        for ev in f.evidence:
            if ev.quote:
                quotes.append(f"{f.name}: “{ev.quote}”")
    return quotes


# ---------------------------------------------------------------------------
# 기대와 실제를 맞춰 보는 판정
# ---------------------------------------------------------------------------


def judge(expect: str, delta: float | None) -> tuple[bool, str]:
    """한 영역에 대한 기대와 실제 변화량을 맞춰 보고 통과 여부를 정한다.

    - same : 변동이 ±5점 이내면 통과 (조금 흔들리는 것까지 잡으면 쓸 수 없는 도구가 된다)
    - down : 5점 이상 떨어져야 통과
    - any  : 판정하지 않는다. 영역 가중치 때문에 변화가 임계에 못 미치는 것이
             정상인 자리를 억지 기대로 채우지 않으려고 둔 값이다.
    """
    # 답안 유효성 가드에 걸려 점수 자체가 없으면 비교할 대상이 없다
    if delta is None:
        return (expect == "any", "점수 없음(채점 무효)")

    if expect == "any":
        return (True, "판정 안 함")
    if expect == "same":
        ok = abs(delta) <= SAME_TOLERANCE
        return (ok, f"|{delta:+.1f}| {'≤' if ok else '>'} {SAME_TOLERANCE:g}")
    if expect == "down":
        ok = delta <= -DOWN_THRESHOLD
        return (ok, f"{delta:+.1f} {'≤' if ok else '>'} -{DOWN_THRESHOLD:g}")
    return (False, f"알 수 없는 기대값 '{expect}'")


def delta_of(base: float | None, variant: float | None) -> float | None:
    """기준 답안 대비 변형 답안의 점수 변화량. 어느 한쪽이라도 없으면 계산하지 않는다."""
    if base is None or variant is None:
        return None
    return round(variant - base, 1)


def moved_contributions(
    base: ScoreResponse, variant: ScoreResponse, limit: int = 3
) -> list[str]:
    """점수를 가장 많이 움직인 자질을 크기 순으로 몇 개만 뽑는다.

    표에 '몇 점 떨어졌다'만 적으면 그 숫자를 반박할 수도, 고칠 수도 없다.
    어느 자질이 얼마를 덜 보탰는지까지 나와야 근거가 된다.
    """
    before = contribution_map(base)
    after = contribution_map(variant)

    moves: list[tuple[float, str]] = []
    for key in set(before) | set(after):
        area, _ = key
        name, base_points = before.get(key, ("(없던 자질)", 0.0))
        name_after, variant_points = after.get(key, ("(사라진 자질)", 0.0))
        gap = variant_points - base_points
        # 0.5점 미만의 흔들림은 설명에 도움이 안 되므로 버린다
        if abs(gap) < 0.5:
            continue
        label = name_after if key in after else name
        moves.append((abs(gap), f"{label}({area}) {gap:+.1f}점"))

    moves.sort(key=lambda x: -x[0])
    return [text for _, text in moves[:limit]]


def checklist_flips(base: ScoreResponse, variant: ScoreResponse) -> list[str]:
    """체크리스트 판정이 뒤집힌 항목을 찾는다(내용 점수가 왜 움직였는지의 직접 근거)."""
    before = checklist_map(base)
    after = checklist_map(variant)
    flips: list[str] = []
    for cid, met_before in before.items():
        met_after = after.get(cid)
        if met_after is None or met_after == met_before:
            continue
        mark = lambda m: "O" if m == 1 else "X"  # noqa: E731
        flips.append(f"{cid} {mark(met_before)}→{mark(met_after)}")
    return flips


# ---------------------------------------------------------------------------
# 세트 하나 검사하기
# ---------------------------------------------------------------------------


def run_set(case_set: dict, client: GeminiClient, use_llm: bool, workers: int = 1) -> dict:
    """기준 답안 하나와 그 변형들을 모두 채점하고 결과표를 찍는다.

    workers 를 2 이상으로 두면 변형들을 동시에 채점한다.
    변형끼리는 서로의 결과를 쓰지 않으므로 순서를 지킬 이유가 없고,
    한 번 채점에 40초쯤 걸려서 여섯 개를 차례로 하면 시연에 쓰기엔 너무 길기 때문이다.
    대신 동시에 너무 많이 부르면 LLM 쪽에서 거절당하므로 기본값은 보수적으로 둔다.
    """
    mode = Mode.SPEAKING if case_set["mode"] == "speaking" else Mode.WRITING
    item = load_item(case_set["item_file"], case_set["item_id"])

    rule(f"[{case_set['set_id']}] {case_set['title']} — {mode.value}")
    print(f"  문항  : {short(item.prompt, 120)}")
    print(f"  기준  : {short(case_set['base_answer'], 200)}")
    print(f"  메모  : {case_set['base_note']}")

    # 먼저 기준 답안을 채점한다. 모든 비교의 기준선이 되는 값이다
    started = time.perf_counter()
    base, base_failure = score_one(
        case_set["base_answer"], item, mode, f"{case_set['set_id']}-base", client, use_llm
    )
    base_scores = area_scores(base)
    base_elapsed = time.perf_counter() - started
    if base_failure:
        # 기준선 자체가 반쪽으로 계산됐으면 이 세트의 비교는 전부 성립하지 않는다
        print(f"\n  ! 기준 답안 채점에서 {base_failure} — 이 세트의 판정은 전부 '비교 불가'로 둔다.")

    print(
        f"\n  기준 점수 : 종합 {base_scores['overall']}  "
        f"내용 {base_scores['content']}  언어 {base_scores['language']}  "
        f"(등급 {base.overall_grade}, {base_elapsed:.1f}초)"
    )
    met = ", ".join(
        f"{c.id}{'O' if c.met else 'X'}" for c in base.checklist_results
    )
    print(f"  기준 체크리스트 : {met or '(없음)'}")
    base_errors = error_quotes(base)
    if base_errors:
        print(f"  기준 답안에서 잡힌 오류 : {', '.join(short(q, 40) for q in base_errors[:4])}")

    print(f"\n  변형 {len(case_set['variants'])}개를 채점하는 중… (동시 {workers}개)")

    # 변형들을 먼저 전부 채점해 두고, 표는 그다음에 한 번에 찍는다.
    # (동시에 채점할 때 진행 메시지가 표 사이에 끼어들어 표가 망가지는 것을 막는다)
    def score_variant(variant: dict) -> tuple[dict, ScoreResponse, str | None, float]:
        v_started = time.perf_counter()
        result, v_failure = score_one(
            variant["answer"],
            item,
            mode,
            f"{case_set['set_id']}-{variant['id']}",
            client,
            use_llm,
        )
        return variant, result, v_failure, time.perf_counter() - v_started

    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            scored = list(pool.map(score_variant, case_set["variants"]))
    else:
        scored = [score_variant(v) for v in case_set["variants"]]

    # 표 머리
    print()
    print(
        "  " + pad("변형", 50) + pad("기대(종합/내용/언어)", 24)
        + pad("실제 Δ(종합/내용/언어)", 26) + "판정"
    )
    print("  " + "-" * (W - 4))

    rows = []
    for variant, result, v_failure, v_elapsed in scored:
        v_scores = area_scores(result)

        deltas = {
            key: delta_of(base_scores[key], v_scores[key])
            for key in ("overall", "content", "language")
        }

        # 영역마다 기대와 맞춰 보고, 하나라도 어긋나면 그 변형은 실패다
        checks = {
            key: judge(variant["expect"][key], deltas[key])
            for key in ("overall", "content", "language")
        }

        # 기준선이나 이 변형에서 LLM 단계가 실패했다면 두 점수는 서로 다른 방식으로
        # 계산된 것이라 비교 자체가 성립하지 않는다. 통과도 실패도 아닌 '비교 불가'로 둔다
        blocked = base_failure or v_failure
        if blocked:
            status = "skip"
            mark = "-"
        elif all(ok for ok, _ in checks.values()):
            status = "pass"
            mark = "O"
        else:
            status = "fail"
            mark = "X"

        expect_text = "/".join(variant["expect"][k] for k in ("overall", "content", "language"))
        delta_text = "/".join(
            "—" if deltas[k] is None else f"{deltas[k]:+.1f}"
            for k in ("overall", "content", "language")
        )
        print(
            "  "
            + pad(f"{variant['kind']} {variant['name']}", 50)
            + pad(expect_text, 24)
            + pad(delta_text, 26)
            + mark
            + ("  비교 불가: " + blocked if blocked else "")
        )

        rows.append(
            {
                "set_id": case_set["set_id"],
                "variant_id": variant["id"],
                "kind": variant["kind"],
                "name": variant["name"],
                "expect": variant["expect"],
                "deltas": deltas,
                "scores": v_scores,
                "status": status,
                "blocked_reason": blocked,
                "checks": {k: {"ok": ok, "why": why} for k, (ok, why) in checks.items()},
                "checklist_flips": checklist_flips(base, result),
                "moved": moved_contributions(base, result),
                "error_quotes": error_quotes(result),
                "reliability": result.meta.reliability.value,
                "warnings": result.warnings,
                "elapsed_sec": round(v_elapsed, 1),
                "note": variant["note"],
            }
        )

    # 변형마다 '왜 그렇게 움직였는지'를 근거로 남긴다.
    # 통과한 것도 함께 보여 주는 이유: 통과가 우연이 아니었는지 사람이 확인해야 하기 때문이다
    print("\n  [무엇이 점수를 움직였나]")
    label_of = {"pass": "통과", "fail": "실패", "skip": "비교 불가"}
    for row in rows:
        print(f"    · {row['kind']} {row['name']}  {label_of[row['status']]}")
        if row["blocked_reason"]:
            print(f"        사유       : {row['blocked_reason']} (LLM 실패라 채점기 행동 문제가 아니다)")
        if row["checklist_flips"]:
            print(f"        체크리스트 : {', '.join(row['checklist_flips'])}")
        if row["moved"]:
            print(f"        자질 변화   : {', '.join(row['moved'])}")
        if row["error_quotes"]:
            print(f"        오류 근거   : {', '.join(short(q, 44) for q in row['error_quotes'][:4])}")
        if row["status"] == "fail":
            for key, check in row["checks"].items():
                if not check["ok"]:
                    print(
                        f"        [어긋남] {key}: 기대 {row['expect'][key]} / "
                        f"실제 {check['why']}"
                    )

    return {
        "set_id": case_set["set_id"],
        "base_scores": base_scores,
        "base_grade": base.overall_grade,
        "rows": rows,
    }


# ---------------------------------------------------------------------------
# 실행 입구
# ---------------------------------------------------------------------------


def build_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="채점기가 INV(뜻 보존 변형에 불변)·DIR(요소 제거 시 해당 영역만 하락) "
        "약속을 지키는지 고정 사례로 검사한다.",
    )
    p.add_argument("--quick", action="store_true", help="쓰기 1세트만 돌린다(시연용)")
    p.add_argument("--set", dest="set_id", default=None, help="세트 하나만 지정해서 돌린다")
    p.add_argument(
        "--no-llm", action="store_true",
        help="LLM 없이 규칙 자질만으로 채점한다(공짜·즉시). 내용 판정이 빠지므로 참고용",
    )
    p.add_argument(
        "--workers", type=int, default=None,
        help="변형을 동시에 몇 개씩 채점할지. 기본값은 --quick 이면 3, 아니면 2. "
        "많이 올리면 빨라지지만 LLM 호출이 거절당해 '비교 불가'가 늘어난다",
    )
    p.add_argument("--cases", default=str(CASES_PATH), help="사례집 경로")
    p.add_argument("--json", dest="json_out", default=None, help="결과를 JSON으로 저장할 경로")
    return p.parse_args()


def main() -> int:
    # 윈도우 터미널에서 한글이 깨지지 않게 출력 인코딩을 맞춘다
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # pragma: no cover - 환경에 따라 없을 수 있다
        pass

    args = build_args()
    cases = load_cases(pathlib.Path(args.cases))

    sets = cases["sets"]
    # --quick 은 시연용이라 쓰기 한 세트만 돌려 2~3분 안에 끝나게 한다
    if args.quick:
        sets = [s for s in sets if s["mode"] == "writing"][:1]
    if args.set_id:
        sets = [s for s in sets if s["set_id"] == args.set_id]
    if not sets:
        print("돌릴 세트가 없다. --set 이름을 확인하라.")
        return 0

    client = GeminiClient()
    use_llm = not args.no_llm
    # 시연용(--quick)은 시간이 생명이라 더 겹쳐 부르고, 전체 실행은 안전하게 둘씩 부른다
    workers = args.workers if args.workers else (3 if args.quick else 2)

    rule("메타모픽 채점 검사")
    print(f"  사례집 : {args.cases} (version {cases['version']})")
    print(f"  모델   : {client.model_name} (사용가능 {client.available}, LLM 사용 {use_llm})")
    print(f"  판정   : same = ±{SAME_TOLERANCE:g}점 이내 / down = {DOWN_THRESHOLD:g}점 이상 하락 / any = 판정 안 함")
    print(f"  세트   : {', '.join(s['set_id'] for s in sets)} (동시 채점 {workers}개)")
    if not use_llm:
        print("  ! LLM을 끄고 돌린다. 내용·과제 수행 판정이 대체 경로라 결과는 참고용이다.")

    started = time.perf_counter()
    results = [run_set(case_set, client, use_llm, workers) for case_set in sets]
    elapsed = time.perf_counter() - started

    # 요약: INV 와 DIR 을 따로 센다. 두 약속은 성격이 다르므로 한 숫자로 합치지 않는다
    all_rows = [row for r in results for row in r["rows"]]
    # 비교 불가(LLM 호출 실패)는 분모에서 뺀다. 채점기의 행동을 못 본 사례이기 때문이다
    judged = [row for row in all_rows if row["status"] != "skip"]
    skipped = [row for row in all_rows if row["status"] == "skip"]
    inv = [row for row in judged if row["kind"] == "INV"]
    dir_rows = [row for row in judged if row["kind"].startswith("DIR")]
    inv_ok = sum(1 for row in inv if row["status"] == "pass")
    dir_ok = sum(1 for row in dir_rows if row["status"] == "pass")

    rule("요약")
    print(f"  INV(뜻 보존 변형에 점수 불변)  {inv_ok}/{len(inv)} 통과")
    print(f"  DIR(요소 제거 시 해당 영역만 하락)  {dir_ok}/{len(dir_rows)} 통과")
    print(f"  전체 {inv_ok + dir_ok}/{len(judged)}  ({elapsed:.1f}초)")
    if skipped:
        print(f"  비교 불가 {len(skipped)}건 (LLM 호출 실패로 기준선과 계산 방식이 달라진 사례):")
        for row in skipped:
            print(f"    - [{row['set_id']}] {row['name']} — {row['blocked_reason']}")

    failed = [row for row in all_rows if row["status"] == "fail"]
    if failed:
        print("\n  [실패한 사례 상세]")
        for row in failed:
            print(f"\n    · [{row['set_id']}] {row['kind']} {row['name']}")
            print(f"      기대   : {row['expect']}")
            print(
                f"      실제 Δ : 종합 {row['deltas']['overall']} / "
                f"내용 {row['deltas']['content']} / 언어 {row['deltas']['language']}"
            )
            for key, check in row["checks"].items():
                if not check["ok"]:
                    print(f"      어긋남 : {key} — {check['why']}")
            if row["checklist_flips"]:
                print(f"      체크리스트 변화 : {', '.join(row['checklist_flips'])}")
            if row["moved"]:
                print(f"      자질 변화 : {', '.join(row['moved'])}")
            print(f"      사례 메모 : {short(row['note'], 160)}")
    else:
        print("\n  실패한 사례 없음.")

    if args.json_out:
        out = pathlib.Path(args.json_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(
                {
                    "cases_version": cases["version"],
                    "llm_used": use_llm,
                    "model": client.model_name,
                    "summary": {
                        "inv_passed": inv_ok,
                        "inv_total": len(inv),
                        "dir_passed": dir_ok,
                        "dir_total": len(dir_rows),
                        "skipped": len(skipped),
                    },
                    "sets": results,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"\n  결과를 저장했다: {out}")

    print(
        "\n  ※ 이것은 회귀 테스트가 아니라 관찰 도구다. 실패가 있어도 정상 종료한다.\n"
        "     실패는 '고장'이 아니라 '지금 채점기가 이렇게 행동한다'는 관찰 결과이며,\n"
        "     무엇을 고칠지는 사람이 정한다."
    )
    # 실패가 있어도 0으로 끝낸다(시연 중에 빨간 오류로 멈추지 않게 하려는 것)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
