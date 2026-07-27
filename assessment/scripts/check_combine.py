"""점수 결합 모듈이 실제로 점수와 근거를 내는지 확인하는 스크립트.

LLM API 키 없이 돌아간다. 자질 값은 손으로 만든 더미 값을 넣는다.
확인하려는 것:
  1) 자질을 넣으면 영역별 점수와 종합 점수가 나오는가
  2) 점수마다 '어떤 자질이 몇 점을 보탰는지' 내역이 함께 나오는가
  3) LLM 자질이 없을 때(키 없음 상황) 가중치가 다시 나뉘고 partial 로 표시되는가
  4) 발화 전달력이 채점에서 빠지되 자리는 남는가

실행: .venv\\Scripts\\python.exe scripts\\check_combine.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.scoring.combine import DEFAULT_WEIGHTS, combine  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    AreaStatus,
    ChecklistResult,
    Evidence,
    FeatureSource,
    FeatureStatus,
    FeatureValue,
    Mode,
    ScoreArea,
)


def make_feature(fid: str, name: str, value, source=FeatureSource.KIWI, **kwargs):
    """더미 자질 하나를 만든다. 근거도 한 줄 넣어 실제 형태와 같게 맞춘다."""
    return FeatureValue(
        id=fid,
        name=name,
        source=source,
        value=value,
        components=kwargs.pop("components", {}),
        status=kwargs.pop("status", FeatureStatus.OK),
        evidence=[Evidence(source=source, quote="(더미)", comment=f"{name} 더미 근거")],
        **kwargs,
    )


def build_features(quality: str, with_llm: bool) -> list[FeatureValue]:
    """'좋은 답안'과 '나쁜 답안'의 자질 값을 손으로 만들어 준다."""
    if quality == "good":
        kiwi_values = {
            "lexical_diversity_mattr": 0.88,
            "advanced_vocab_ratio": 0.10,
            "lexical_density": 0.50,
            "response_length": 60.0,
            "words_per_sentence": 12.0,
            "clause_density": 3.8,
            "connective_ending_diversity": 0.70,
            "formality": 1.0,
            "subject_honorific_si": 1.8,
        }
        banmal = 0.0
        llm_values = {
            "error_josa": 0.5,
            "error_conjugation": 0.0,
            "error_word_choice": 0.0,
            "error_honorific": 0.0,
        }
        checklist_met = [1, 1, 1]
    else:
        kiwi_values = {
            "lexical_diversity_mattr": 0.60,
            "advanced_vocab_ratio": 0.0,
            "lexical_density": 0.33,
            "response_length": 18.0,
            "words_per_sentence": 3.0,
            "clause_density": 1.1,
            "connective_ending_diversity": 0.0,
            "formality": 0.5,
            "subject_honorific_si": 0.0,
        }
        banmal = 3.0
        llm_values = {
            "error_josa": 6.0,
            "error_conjugation": 5.0,
            "error_word_choice": 4.0,
            "error_honorific": 3.0,
        }
        checklist_met = [1, 0, 0]

    names = {
        "lexical_diversity_mattr": "어휘 다양도(MATTR)",
        "advanced_vocab_ratio": "고급 어휘 비율",
        "lexical_density": "어휘 밀도",
        "response_length": "응답 길이",
        "words_per_sentence": "문장당 어절 수",
        "clause_density": "절 밀도",
        "connective_ending_diversity": "연결어미 다양성",
        "formality": "격식체 비율·반말 혼입",
        "subject_honorific_si": "주체 높임 '-시-' 빈도",
        "error_josa": "조사 오류",
        "error_conjugation": "어미 활용 오류",
        "error_word_choice": "어휘 오용",
        "error_honorific": "높임법 오류",
    }

    features = []
    for fid, value in kiwi_values.items():
        components = {"banmal_count": banmal} if fid == "formality" else {}
        features.append(make_feature(fid, names[fid], value, components=components))

    for fid, value in llm_values.items():
        if with_llm:
            features.append(make_feature(fid, names[fid], value, source=FeatureSource.LLM))
        else:
            # 키가 없는 상황을 흉내 낸다. 값을 0으로 채우지 않고 '못 구했음'으로 둔다
            features.append(
                make_feature(
                    fid, names[fid], None, source=FeatureSource.LLM,
                    status=FeatureStatus.UNAVAILABLE,
                    note="GEMINI_API_KEY 없음",
                )
            )

    # 말하기 답안이므로 맞춤법·띄어쓰기는 해당 없음으로 둔다
    for fid, name in (("error_spelling", "맞춤법 오류"), ("spacing_error_rate", "띄어쓰기 오류율")):
        features.append(
            make_feature(
                fid, name, None,
                source=FeatureSource.LLM if fid == "error_spelling" else FeatureSource.KIWI,
                status=FeatureStatus.NOT_APPLICABLE,
                note="말하기 답안에서는 채점하지 않음",
            )
        )

    return features, checklist_met


def build_checklist(met_flags: list[int]) -> list[ChecklistResult]:
    """체크리스트 판정 결과 더미."""
    descriptions = ["상황을 설명했는가", "취한 조치를 말했는가", "재발 방지책을 말했는가"]
    return [
        ChecklistResult(
            id=f"c{i+1}",
            description=descriptions[i],
            met=met,
            weight=1.0,
            evidence=[Evidence(source=FeatureSource.LLM, quote="(더미 인용)", comment="더미 근거")],
        )
        for i, met in enumerate(met_flags)
    ]


def report(title: str, features, checklist, mode=Mode.SPEAKING) -> object:
    """결합 결과를 사람이 읽을 수 있게 찍어 준다."""
    result = combine(features, checklist, mode=mode, weights=DEFAULT_WEIGHTS)
    print("=" * 78)
    print(title)
    print("=" * 78)
    print(f"  종합 점수: {result.overall_score}  /  등급: {result.overall_grade}")
    print()
    for s in result.subscores:
        score_text = "채점 안 함" if s.score is None else f"{s.score:6.2f}"
        print(f"  [{s.area.value:13s}] {s.label:12s} 점수 {score_text}  "
              f"비중 {s.weight}  상태 {s.status.value}")
        if s.note:
            print(f"                  비고: {s.note[:100]}")
        # 점수 내역이 실제로 붙는지 확인한다. 이게 없으면 근거 없는 점수다
        for c in s.contributions[:5]:
            print(f"      - {c.feature_name:22s} 원래값 {str(c.raw_value):>8s} "
                  f"-> 정규화 {c.normalized:.3f} x 비중 {c.weight:.3f} = {c.points:5.2f}점")
        if len(s.contributions) > 5:
            print(f"      ... 외 {len(s.contributions) - 5}개 내역")
        print()
    print("  경고:")
    for w in result.warnings:
        print(f"    - {w[:110]}")
    print()
    return result


def main() -> None:
    failed = 0

    good_features, good_flags = build_features("good", with_llm=True)
    good = report("① 잘 쓴 답안 + LLM 자질 있음", good_features, build_checklist(good_flags))

    bad_features, bad_flags = build_features("bad", with_llm=True)
    bad = report("② 못 쓴 답안 + LLM 자질 있음", bad_features, build_checklist(bad_flags))

    nokey_features, nokey_flags = build_features("good", with_llm=False)
    nokey = report("③ 잘 쓴 답안 + LLM 키 없음(재정규화 확인)",
                   nokey_features, build_checklist(nokey_flags))

    print("-" * 78)
    print("확인 항목")
    print("-" * 78)
    checks = [
        ("잘 쓴 답안이 못 쓴 답안보다 종합 점수가 높다",
         good.overall_score > bad.overall_score),
        ("모든 채점 영역에 점수 내역(근거)이 붙는다",
         all(s.contributions for s in good.subscores if s.score is not None)),
        ("발화 전달력은 채점하지 않고 자리만 남는다",
         any(s.area == ScoreArea.DELIVERY and s.status == AreaStatus.NOT_EVALUATED
             and s.weight == 0.0 for s in good.subscores)),
        ("점수가 나온 영역들의 비중 합이 1이다",
         abs(sum(s.weight for s in good.subscores) - 1.0) < 1e-6),
        ("LLM 키가 없으면 언어 사용 영역이 partial 로 표시된다",
         any(s.area == ScoreArea.LANGUAGE_USE and s.status == AreaStatus.PARTIAL
             for s in nokey.subscores)),
        ("LLM 자질이 빠져도 종합 점수는 나온다",
         nokey.overall_score is not None),
        ("LLM 자질이 빠진 언어 사용 영역의 비중 합이 다시 1로 맞춰진다",
         abs(sum(c.weight for s in nokey.subscores
                 if s.area == ScoreArea.LANGUAGE_USE for c in s.contributions) - 1.0) < 1e-6),
        ("임시 가중치 경고가 항상 따라 나온다",
         any("임시" in w for w in good.warnings)),
    ]
    for desc, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {desc}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"확인 실패 {failed}건 — 결합 로직을 손봐야 한다.")
        sys.exit(1)
    print("결합 모듈 확인 전부 통과.")


if __name__ == "__main__":
    main()
