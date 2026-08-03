# -*- coding: utf-8 -*-
"""② 라벨 신뢰도 감사 킷 — 팀원이 **귀로 직접** 정답지를 검사할 재료를 만든다.

왜 이 단계가 학습보다 먼저인가:
우리 실험 전체가 "AI Hub 의 사람 전사는 학습자의 오류를 그대로 살려 적었다"는
가정 위에 서 있다. 그런데 그 전사를 만든 사람의 습관이 일관된다는 보장이 없다.
실제로 "같지"를 소리 나는 대로 "가치"라고 적은 사례를 찾았다.
정답지가 틀렸는데 그걸로 모델을 가르치면 **틀린 것을 열심히 외운 모델**이 나온다.

그래서 학습 전에 표본 100건을 팀(한국어 원어민)이 직접 듣고 대조해
**라벨 신뢰율을 숫자로 확보한 뒤에** 시작한다. 신뢰율이 낮게 나온 유형은 학습에서 뺀다.

쓰는 법 (두 단계):
  1) 재료 만들기
     python audit_kit.py --manifest ../../../data/manifests/71479_lar.jsonl --n 100
  2) 팀이 csv 를 다 채운 뒤 점수 내기
     python audit_kit.py --score --sheet ../../../data/audit/감사시트.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DATA_ROOT,
    enable_utf8_output,
    load_audio_bytes,
    print_table,
    read_manifest,
)

#: 감사 시트의 열 이름. --score 가 이 이름으로 값을 찾으므로 사람이 바꾸면 안 된다.
COLUMNS = ["번호", "파일명", "사람전사", "들은대로_일치여부", "메모"]

#: 일치했다고 인정하는 표기들. 팀원마다 O·o·ㅇ·예 를 섞어 쓰므로 다 받아 준다.
YES_TOKENS = {"o", "O", "ㅇ", "0", "y", "Y", "예", "네", "일치", "맞음"}
NO_TOKENS = {"x", "X", "ㄴ", "n", "N", "아니오", "불일치", "틀림", "다름"}


def stratified_sample(rows: list[dict], n: int) -> list[dict]:
    """표본을 뽑되 한쪽으로 쏠리지 않게 고루 섞는다.

    그냥 앞에서부터 100건을 자르면 파일 이름 순서 탓에 특정 국적·특정 과제만
    잔뜩 뽑힌다. 그러면 "베트남 학습자 낭독의 신뢰율"을 재 놓고 전체 신뢰율이라
    부르게 된다. 그래서 (과제 유형, 국적) 묶음별로 한 개씩 돌아가며 뽑는다.
    """
    # 같은 (과제, 국적)끼리 바구니에 나눠 담는다
    buckets: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[(r.get("task", "?"), r.get("nationality", "?"))].append(r)

    picked: list[dict] = []
    keys = sorted(buckets.keys())

    # 바구니를 한 바퀴 돌며 하나씩 꺼내기를, 목표 개수를 채울 때까지 반복한다
    round_no = 0
    while len(picked) < n:
        added_this_round = 0
        for key in keys:
            if round_no < len(buckets[key]) and len(picked) < n:
                picked.append(buckets[key][round_no])
                added_this_round += 1
        # 한 바퀴를 돌았는데 아무것도 못 꺼냈으면 남은 것이 없다는 뜻이다
        if added_this_round == 0:
            break
        round_no += 1

    return picked


def build_kit(manifest: Path, n: int, out_dir: Path) -> int:
    """표본을 골라 wav·csv·안내문을 한 폴더에 차려 놓는다."""
    rows = read_manifest(manifest)
    picked = stratified_sample(rows, n)

    wav_dir = out_dir / "wav"
    wav_dir.mkdir(parents=True, exist_ok=True)

    # ① wav 를 한 폴더에 모아 준다. 팀원이 zip 안을 뒤지게 하지 않으려는 것이다
    copied, failed = 0, []
    for r in picked:
        target = wav_dir / f"{r['id']}.wav"
        if target.exists():
            copied += 1
            continue
        try:
            target.write_bytes(load_audio_bytes(r))
            copied += 1
        except Exception as exc:
            failed.append((r["id"], str(exc)[:60]))

    # ② 채워 넣을 표. utf-8-sig 로 저장해야 엑셀에서 한글이 깨지지 않는다
    sheet = out_dir / "감사시트.csv"
    with sheet.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLUMNS)
        for i, r in enumerate(picked, 1):
            # 판정 칸과 메모 칸은 사람이 채울 자리라 비워 둔다
            w.writerow([i, f"{r['id']}.wav", r["ref"], "", ""])

    # ③ 작업 설명서
    (out_dir / "안내문.md").write_text(_guide_text(len(picked), manifest.name), encoding="utf-8")

    print(f"감사 킷 준비 완료 → {out_dir}")
    print(f"  표본 {len(picked)}건 (요청 {n}건) · wav 복사 {copied}건")
    if failed:
        print(f"  음성을 못 가져온 것 {len(failed)}건: {failed[:3]}")

    # 어떻게 섞였는지 눈으로 확인하는 자리
    dist: dict[tuple, int] = defaultdict(int)
    for r in picked:
        dist[(r.get("task", "?"), r.get("nationality", "?"))] += 1
    print("\n표본 구성 (과제 · 국적 · 건수):")
    print_table(
        ["과제", "국적", "건수"],
        [[k[0], k[1], str(v)] for k, v in sorted(dist.items(), key=lambda x: -x[1])[:12]],
    )
    return 0


def _guide_text(n: int, manifest_name: str) -> str:
    """팀원에게 그대로 건네는 작업 설명서. 전문 용어 없이 쓴다."""
    return f"""# 녹음 듣고 정답지 검사하기

## 이걸 왜 하나요

우리는 외국인이 한국어를 말할 때 **틀린 부분을 지우지 않고 그대로 받아쓰는 AI** 를
만들려고 합니다. 그러려면 "이 사람이 이렇게 말했다"고 적힌 정답지가 필요한데,
그 정답지는 우리가 만든 게 아니라 남이 만들어 놓은 것을 받아 온 것입니다.

정답지가 틀려 있으면 AI 도 똑같이 틀리게 배웁니다. 그래서 학습을 시작하기 전에
**정답지가 실제 녹음과 맞는지 사람 귀로 확인**하는 것이 이 작업입니다.

## 무엇을 하면 되나요

1. `감사시트.csv` 를 엑셀로 엽니다. (표본 {n}건 · 원본 목록: {manifest_name})
2. 한 줄씩 내려가면서, `파일명` 에 적힌 파일을 `wav` 폴더에서 찾아 재생합니다.
3. 녹음에서 **들리는 말**과 `사람전사` 칸의 글이 같은지 봅니다.
4. `들은대로_일치여부` 칸에 이렇게 적습니다.

   - 같으면 → **O**
   - 다르면 → **X** 그리고 `메모` 칸에 무엇이 다른지 짧게 적습니다

## 판단이 헷갈릴 때 (중요)

**외국인이 틀리게 말한 것은 정답지에도 틀린 채로 적혀 있어야 정상입니다.**
정답지가 "집들은 참 좋은데 너무 비쌌다" 라고 돼 있는데 실제로도 그렇게 말했다면,
문법이 틀렸어도 **O** 입니다. 우리가 찾는 것은 '문법 오류'가 아니라
'정답지가 녹음과 다른 곳' 입니다.

반대로 이런 경우가 **X** 입니다.

- 녹음에서는 "같지 않아요" 라고 들리는데 정답지에는 "가치 않아요" 라고 적힌 경우
  (적은 사람이 소리 나는 대로 적어 버린 것)
- 정답지에 있는 말을 녹음에서 아예 하지 않은 경우
- 녹음에서 말한 것이 정답지에 빠져 있는 경우
- 옆 사람 목소리가 섞여 있어서 무슨 말인지 알 수 없는 경우 (메모에 "잡음" 이라고 적어 주세요)

## 다 하면

파일을 그대로 저장하고 (형식은 CSV 유지) 담당자에게 알려 주세요.
숫자는 자동으로 계산됩니다.
"""


def score_sheet(sheet: Path) -> int:
    """팀이 채운 시트를 읽어 신뢰율을 계산하고 불일치 사례를 보여 준다."""
    with sheet.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("시트가 비어 있다.")
        return 1

    yes, no, blank, unknown = 0, 0, 0, []
    mismatches = []
    for r in rows:
        v = (r.get("들은대로_일치여부") or "").strip()
        if not v:
            blank += 1
        elif v in YES_TOKENS:
            yes += 1
        elif v in NO_TOKENS:
            no += 1
        else:
            # 약속한 표기가 아닌 값. 조용히 무시하면 숫자가 틀어지므로 따로 보고한다
            unknown.append((r.get("번호"), v))
        if v in NO_TOKENS:
            mismatches.append(r)

    judged = yes + no
    print(f"전체 {len(rows)}건 · 판정됨 {judged}건 · 아직 안 함 {blank}건")
    if unknown:
        print(f"알 수 없는 표기 {len(unknown)}건 (O/X 로 고쳐 주세요): {unknown[:5]}")

    if judged == 0:
        print("아직 판정된 것이 없어 신뢰율을 낼 수 없다.")
        return 1

    rate = yes / judged
    print(f"\n=== 라벨 신뢰율: {rate:.1%}  (일치 {yes} / 불일치 {no}) ===")
    # 판정된 건수가 적으면 이 숫자를 근거로 쓰기 어렵다는 것을 분명히 적는다
    if judged < 30:
        print("  주의: 판정 건수가 30건 미만이라 이 비율은 참고용이다.")

    if mismatches:
        print(f"\n불일치 사례 (최대 10건):")
        print_table(
            ["번호", "파일명", "사람전사", "메모"],
            [
                [
                    str(m.get("번호", "")),
                    str(m.get("파일명", ""))[:34],
                    str(m.get("사람전사", ""))[:34],
                    str(m.get("메모", ""))[:30],
                ]
                for m in mismatches[:10]
            ],
        )
    return 0


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="정답지를 사람 귀로 검사하는 킷")
    ap.add_argument("--manifest", help="검사할 목록 파일(.jsonl)")
    ap.add_argument("--n", type=int, default=100, help="표본 건수 (기본 100)")
    ap.add_argument("--out", default=str(DATA_ROOT / "audit"), help="킷을 놓을 폴더")
    ap.add_argument("--score", action="store_true", help="채워진 시트를 읽어 신뢰율을 낸다")
    ap.add_argument("--sheet", help="--score 에서 읽을 감사시트.csv 경로")
    args = ap.parse_args()

    if args.score:
        sheet = Path(args.sheet or (Path(args.out) / "감사시트.csv"))
        if not sheet.exists():
            print(f"시트가 없다: {sheet}")
            return 1
        return score_sheet(sheet)

    if not args.manifest:
        print("--manifest 가 필요하다 (또는 --score 로 채점 모드).")
        return 1
    return build_kit(Path(args.manifest), args.n, Path(args.out))


if __name__ == "__main__":
    raise SystemExit(main())
