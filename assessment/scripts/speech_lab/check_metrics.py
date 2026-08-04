# -*- coding: utf-8 -*-
"""실험 도구의 계산이 맞는지 **예시를 넣어 눈으로 확인**하는 스크립트.

채점·평가 계산은 코드를 훑어봐서는 맞는지 알 수 없다. 그래서 답을 아는 예시를
넣고 나온 값을 표로 보여 준다. 다섯 스크립트를 고친 뒤에는 이것을 먼저 돌린다.

    python check_metrics.py

틀린 줄에는 'X' 가 붙는다. X 가 하나라도 있으면 종료 코드가 1이다.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import cer, diff_pairs, enable_utf8_output, norm_text, print_table  # noqa: E402
from eval_ab import classify_preservation, is_measurable_error  # noqa: E402
from make_labels import converge_inaudible  # noqa: E402

_fails = 0


def check(label: str, got, want) -> list[str]:
    """하나 확인하고 표에 넣을 한 줄을 만든다."""
    global _fails
    ok = got == want
    if not ok:
        _fails += 1
    return [label, str(want), str(got), "O" if ok else "X"]


def main() -> int:
    enable_utf8_output()

    # ── ① 글자 비교용 정규화 ──
    # 문장부호·공백·전사기호를 떼는 것이 목적이다. 글자는 남아야 한다
    print("① norm_text — 견주기 전에 사소한 차이를 걷어낸다")
    print_table(["입력", "기대", "결과", ""], [
        check("'안 됐습니다.'", norm_text("안 됐습니다."), "안됐습니다"),
        check("'있+ 오는'", norm_text("있+ 오는"), "있오는"),
        # 주의 — '/' 는 일부러 남긴다. 이 자를 바꾸면 8/2 부터 쌓아 온 CER 숫자와
        # 비교할 수 없게 되기 때문이다(그때 규칙에 '/'가 없었다).
        # 대신 학습 라벨을 만들 때 converge_inaudible 이 떼어 낸다(⑥번 확인 참고).
        check("'어/ 우리' — '/'는 남는다(규칙 고정)", norm_text("어/ 우리"), "어/우리"),
    ])

    # ── ② 글자 오류율 ──
    print("\n② cer — 글자를 몇 개나 고쳐야 정답이 되는가 (0=완벽)")
    print_table(["입력", "기대", "결과", ""], [
        # 완전히 같으면 0
        check("같은 문장", cer("집이 좋다", "집이 좋다"), 0.0),
        # 문장부호·공백만 다르면 0 이어야 한다(오류로 세면 안 되는 차이)
        check("문장부호만 다름", cer("집이 좋다", "집이 좋다."), 0.0),
        # '좋다'->'좋았다' 는 글자 하나 추가.
        # 정답은 공백을 뗀 '집이좋다' 4글자이므로 1/4 = 0.25 다
        check("한 글자 추가", round(cer("집이 좋다", "집이 좋았다"), 3), 0.25),
        # 정답이 비었는데 뭔가 받아썼으면 전부 오류
        check("정답이 빔", cer("", "무언가"), 1.0),
    ])

    # ── ③ 낭독에서 오류 자리 뽑기 ──
    print("\n③ diff_pairs — 읽어야 했던 문장과 실제 발화가 갈리는 자리")
    print_table(["입력", "기대", "결과", ""], [
        # 잘못 읽음: (표준형, 발화형)
        check("비싸다->비쌌다",
              diff_pairs("너무 비싸다.", "너무 비쌌다."), [("비싸다.", "비쌌다.")]),
        # 빼먹음: 발화형이 빈 문자열
        check("한 어절 빼먹음",
              diff_pairs("나는 집에 간다", "나는 간다"), [("집에", "")]),
        # 정확히 읽음: 오류 없음
        check("정확히 읽음", diff_pairs("나는 간다", "나는 간다"), []),
    ])

    # ── ④ 구인 경계: 소리로 구별 못 하는 오류는 빼야 한다 ──
    print("\n④ is_measurable_error — '삼번/3번'처럼 소리가 같은 자리는 잰다고 하지 않는다")
    print_table(["입력", "기대", "결과", ""], [
        check("삼번 vs 3번", is_measurable_error("삼번", "3번")[0], False),
        check("비싸다 vs 비쌌다", is_measurable_error("비싸다", "비쌌다")[0], True),
    ])

    # ── ⑤ 오류 보존 판정 — 이 실험의 핵심 지표 ──
    # hyp_norm 자리에는 '모델이 받아쓴 글'을 비교용 형태로 만든 것을 넣는다
    print("\n⑤ classify_preservation — 모델이 오류를 살렸나 고쳤나")
    print_table(["입력", "기대", "결과", ""], [
        # 틀린 형태가 전사에 그대로 있다 -> 보존 (우리가 원하는 것)
        check("틀린 형태가 살아 있음",
              classify_preservation("비싸다", "비쌌다", norm_text("너무 비쌌다")), "보존"),
        # 표준형으로 고쳐 놓았다 -> 세탁 (막으려는 것)
        check("표준형으로 고쳐짐",
              classify_preservation("비싸다", "비쌌다", norm_text("너무 비싸다")), "세탁"),
        # 아예 다르게 알아들었다 -> 기타
        check("엉뚱하게 알아들음",
              classify_preservation("비싸다", "비쌌다", norm_text("너무 비싼다")), "기타"),
        # 학습자가 빼먹었고 전사에도 없다 -> 보존
        check("빼먹은 말이 전사에도 없음",
              classify_preservation("집에", "", norm_text("나는 간다")), "보존"),
        # 학습자가 빼먹었는데 전사가 채워 넣었다 -> 세탁
        check("빼먹은 말을 전사가 채움",
              classify_preservation("집에", "", norm_text("나는 집에 간다")), "세탁"),
        # 한쪽이 다른 쪽을 품은 경우(8/2 파일럿이 놓쳤던 자리).
        # '방청소를'이 전사에 있으므로 보존이다 — '방'도 그 안에 들어 있지만 속으면 안 된다
        check("품은 관계: 긴 쪽이 전사에 있음",
              classify_preservation("방", "방청소를", norm_text("방 청소를 끝내야")), "보존"),
        # 반대로 짧은 표준형만 있으면 고쳐 놓은 것이다
        check("품은 관계: 표준형만 있음",
              classify_preservation("방", "방청소를", norm_text("방 안을 치워야")), "세탁"),
    ])

    # ── ⑥ 학습 라벨 다듬기 ──
    print("\n⑥ converge_inaudible — 학습 정답에서 전사 기호만 떼고 말은 남긴다")
    rows = []
    got, applied = converge_inaudible("한국에서 있+ 오는 이유는")
    rows.append(check("끊긴 말 표시 '+' 제거", got, "한국에서 있 오는 이유는"))
    rows.append(check("  적용 규칙 기록됨", "전사기호제거" in applied, True))

    got2, _ = converge_inaudible("어/ 우리나라가  큰   나라이지만")
    rows.append(check("군말 표시 '/' 제거·공백 정리", got2, "어 우리나라가 큰 나라이지만"))

    # 오류는 손대지 않아야 한다. 여기서 '비쌌다'가 '비싸다'로 바뀌면 실험이 무너진다
    got3, applied3 = converge_inaudible("집들은 참 좋은데 너무 비쌌다.")
    rows.append(check("학습자 오류는 그대로 둔다", got3, "집들은 참 좋은데 너무 비쌌다."))
    rows.append(check("  손댄 것 없음", applied3, []))
    print_table(["입력", "기대", "결과", ""], rows)

    print()
    if _fails:
        print(f"확인 실패 {_fails}개 — X 표시된 줄을 고쳐야 한다.")
        return 1
    print("전부 통과.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
