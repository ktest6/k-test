# -*- coding: utf-8 -*-
"""③ 학습 라벨 제작기 — 목록의 '사람 전사'를 모델이 배울 정답 문장으로 다듬는다.

두 갈래가 있다. 어느 쪽을 쓰느냐가 곧 "모델에게 무엇을 시킬 것인가"다.

  --variant flagship  (우리 본진)
      **표준 철자로 적되, 소리로 구별되는 오류만 살린다.**
      예: "집들은 참 좋은데 너무 비쌌다" — '비싸다'를 '비쌌다'로 잘못 읽은 것은
          귀로 구별되므로 그대로 둔다.
      예: "여덟 시" 를 [여덜씨]로 발음한 것은 **표준 발음이 원래 그렇다.**
          소리대로 '여덜'이라고 적어 버리면 옳게 말한 사람에게 가짜 오류가 생긴다.

  --variant mdd  (팀원 안 / 비교용)
      **소리 나는 대로 적는다.** 한국어 발음 변환기(g2pk)로 전사를 발음 표기로 바꾼다.
      발음 오류 진단(MDD) 연구가 쓰는 방식이고, 위의 '가짜 오류' 문제를 안고 간다.
      비교 상대로 두려는 것이지 본진이 아니다.

이 구분이 이 실험의 급소다. 자세한 근거는 assessment/RESEARCH.md 의 '⑨의 구인 경계'.

쓰는 법:
    python make_labels.py --manifest ../../../data/manifests/71479_lar.jsonl \\
        --variant flagship --out ../../../data/labels/flagship.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DATA_ROOT,
    enable_utf8_output,
    load_audio_bytes,
    read_manifest,
    write_manifest,
)

# ── 전사에만 쓰이는 기호들 ───────────────────────────────────────────────────
# AI Hub 전사자가 쓰는 약속 기호다. 응시자가 낸 소리가 아니라 '적는 사람의 표시'라
# 학습 정답에 남겨 두면 모델이 이 기호까지 받아쓰려고 한다.
#   '+'  말이 중간에 끊겼다는 표시   (예: "한국에서 있+")
#   '/'  간투사·군말이라는 표시      (예: "어/ 우리나라가")
# 끊긴 조각('있')과 군말('어')은 실제로 낸 소리이므로 **글자는 남기고 기호만 뗀다.**
_TRANSCRIPT_MARKS = re.compile(r"[+/]")

#: 따옴표·말줄임표의 모양이 자료마다 달라서 한 가지로 맞춘다.
#: (모양만 다를 뿐 소리가 같으므로 오류로 셀 이유가 없다)
_PUNCT_MAP = {
    "‘": "'", "’": "'",      # ' '  홑따옴표
    "“": '"', "”": '"',      # " "  겹따옴표
    "…": "...",                   # …    말줄임표
    "·": " ",                     # ·    가운뎃점
    "，": ",", "．": ".",      # ，．  전각 문장부호
}


def converge_inaudible(text: str, prompt: str = "") -> tuple[str, list[str]]:
    """**구인 경계 훅** — 소리로 구별되지 않는 표기 차이를 표준형으로 되돌린다.

    왜 필요한가:
    '삼번'과 '3번', '안 돼습니다'와 '안 됐습니다'는 **소리가 같다.** 어느 쪽 철자로
    쓰려 했는지 소리만 듣고 알아낼 방법은 원리상 없다. 그런데도 이런 차이를
    '보존해야 할 오류'로 세면, 맞힐 수 없는 문제를 모델에게 내는 셈이고
    오류 보존율이라는 지표도 부풀려진다.
    그래서 이 부류는 **말하기에서 측정 불가한 오류 클래스로 선언**하고
    학습 정답에서도 지표 계산에서도 표준형 하나로 수렴시킨다.

    v0 현재 상태(정직하게 적어 둔다):
      들어 있는 것 — 자모 결합 정리(NFC), 문장부호 통일, 전사 기호 제거, 공백 정리
      **아직 없는 것(TODO)** — 동음이표기 사전(여덟/여덜, 돼/됐, 삼/3 …)을 이용한
      실제 수렴. 어느 쪽이 표준형인지 판정하려면 한국어 발음 변환기가 필요한데
      (같은 소리로 읽히는지 확인해야 한다) 지금 윈도우에 설치가 안 된다.
      GPU 서버(리눅스)에서 g2pk 를 붙인 뒤 이 함수 안에서 채운다.

    돌려주는 값은 (다듬은 글, 적용한 규칙 이름 목록)이다.
    무엇이 왜 바뀌었는지 남기지 않으면 나중에 라벨을 의심할 때 되짚을 수가 없다.
    """
    applied: list[str] = []

    # ① 자모 결합 정리 — 눈에 같아 보여도 속으로 '한'과 'ㅎ+ㅏ+ㄴ'은 다른 글자다.
    #    이걸 안 맞추면 같은 말인데 글자 오류율이 100%로 나온다
    nfc = unicodedata.normalize("NFC", text)
    if nfc != text:
        applied.append("자모결합정리")
    out = nfc

    # ② 전사자가 붙인 표시 기호를 뗀다 (소리가 아니라 표기 약속이므로)
    stripped = _TRANSCRIPT_MARKS.sub("", out)
    if stripped != out:
        applied.append("전사기호제거")
    out = stripped

    # ③ 문장부호 모양 통일
    before = out
    for src, dst in _PUNCT_MAP.items():
        out = out.replace(src, dst)
    if out != before:
        applied.append("문장부호통일")

    # ④ 기호를 떼면서 생긴 이중 공백과 떠 버린 문장부호를 정리한다
    before = out
    out = re.sub(r"\s+", " ", out)          # 공백 여러 칸 -> 한 칸
    out = re.sub(r"\s+([,.?!])", r"\1", out)  # 문장부호 앞의 공백 제거
    out = re.sub(r"([,.?!])\1+", r"\1", out)  # ".."  ",," 같은 중복 제거
    out = out.strip()
    if out != before:
        applied.append("공백정리")

    # ⑤ TODO: 동음이표기 수렴. prompt(낭독의 표준 문장)를 받아 두는 이유가 여기다 —
    #    낭독 과제는 표준형이 무엇인지 알고 있으므로, 발음 변환기가 붙는 순간
    #    "두 어절이 같은 소리로 읽히는가"를 물어 표준형으로 되돌릴 수 있다.
    #    지금은 아무것도 하지 않는다. 하는 척하지 않으려고 비워 둔다.
    _ = prompt

    return out, applied


def make_flagship_label(row: dict) -> tuple[str, list[str]]:
    """본진 라벨: 사람 전사를 그대로 쓰되 구인 경계만 적용한다."""
    return converge_inaudible(row.get("ref", ""), row.get("prompt", ""))


class G2pUnavailable(RuntimeError):
    """발음 변환기를 못 구했을 때 나는 오류. 어떻게 하면 되는지까지 담는다."""


def load_g2p():
    """한국어 발음 변환기를 구해 온다. 없으면 설치법을 알려 주며 멈춘다.

    두 가지를 차례로 시도한다.
      1) g2pk   — 원조. 형태소 분석기(mecab)를 C 로 빌드해야 해서 윈도우에서 자주 막힌다
      2) g2pkk  — 순수 파이썬 포크. 다만 이쪽도 eunjeon(윈도우용 mecab)을 요구한다

    둘 다 안 되면 이 갈래(mdd)만 포기하고, 본진(flagship)은 그대로 돌아간다.
    실제 학습은 리눅스 GPU 서버에서 하므로 거기서는 g2pk 가 설치된다.
    """
    try:
        from g2pk import G2p  # 원조

        return G2p(), "g2pk"
    except Exception as first:
        try:
            from g2pkk import G2p  # 순수 파이썬 포크

            return G2p(), "g2pkk"
        except Exception as second:
            raise G2pUnavailable(
                "발음 변환기를 쓸 수 없어 --variant mdd 는 이 컴퓨터에서 만들 수 없다.\n"
                f"  g2pk 실패: {type(first).__name__}: {str(first)[:90]}\n"
                f"  g2pkk 실패: {type(second).__name__}: {str(second)[:90]}\n"
                "  까닭: 둘 다 형태소 분석기(mecab)를 C 로 빌드해야 하는데 윈도우에는\n"
                "        빌드 도구가 없다. 리눅스(Colab·RunPod)에서는 `pip install g2pk`\n"
                "        한 줄로 설치된다.\n"
                "  지금 할 일: 학습 라벨은 --variant flagship 으로 만들고,\n"
                "             mdd 갈래는 GPU 서버에 올라간 뒤 같은 명령으로 만든다."
            ) from second


def make_mdd_label(row: dict, g2p) -> tuple[str, list[str]]:
    """비교용 라벨: 사람 전사를 소리 나는 대로 바꾼다.

    주의 — 이 갈래는 '여덟 시'를 '여덜 씨'로 만든다. 옳게 말한 사람에게
    가짜 오류가 생기는 자리이며, 그것을 알고도 비교하려고 만드는 것이다.
    """
    # 표기 기호는 본진과 똑같이 먼저 떼어 낸다. 그래야 두 갈래의 차이가
    # '발음 변환을 했느냐'만 남는다 (다른 조건을 섞으면 비교가 안 된다)
    base, applied = converge_inaudible(row.get("ref", ""), row.get("prompt", ""))
    return g2p(base), applied + ["발음변환"]


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="사람 전사를 학습 정답 문장으로 다듬는다")
    ap.add_argument("--manifest", required=True, help="extract_pairs 가 만든 목록(.jsonl)")
    ap.add_argument("--variant", required=True, choices=["flagship", "mdd"])
    ap.add_argument("--out", required=True, help="만들 라벨 파일(.jsonl)")
    ap.add_argument("--max-n", type=int, default=0, help="최대 몇 건 (0=전부)")
    ap.add_argument("--no-audio", action="store_true",
                    help="wav 를 실제로 꺼내지 않는다 (라벨 문장만 눈으로 볼 때)")
    args = ap.parse_args()

    rows = read_manifest(Path(args.manifest))
    if args.max_n:
        rows = rows[: args.max_n]
    print(f"목록 {len(rows)}건 · 갈래 {args.variant}")

    # mdd 갈래는 발음 변환기가 있어야 시작할 수 있다. 없으면 여기서 분명히 알리고 멈춘다
    g2p, g2p_name = None, None
    if args.variant == "mdd":
        try:
            g2p, g2p_name = load_g2p()
            print(f"발음 변환기: {g2p_name}")
        except G2pUnavailable as exc:
            print(f"\n{exc}")
            return 2

    out_rows, changed, missing_audio = [], 0, 0
    for r in rows:
        if args.variant == "flagship":
            text, applied = make_flagship_label(r)
        else:
            text, applied = make_mdd_label(r, g2p)

        # 정답 문장이 비면 학습에 쓸 수 없다(모델이 '아무 말도 안 함'을 배운다)
        if not text.strip():
            continue

        # 학습 코드가 파일을 바로 열 수 있게 wav 를 실제 자리에 놓아 준다
        audio_path = DATA_ROOT / r["audio"]
        if not args.no_audio and not audio_path.exists():
            try:
                audio_path.parent.mkdir(parents=True, exist_ok=True)
                audio_path.write_bytes(load_audio_bytes(r))
            except Exception:
                missing_audio += 1
                continue

        if applied:
            changed += 1

        out_rows.append(
            {
                # 아래 두 개가 HuggingFace 학습이 실제로 읽는 값이다
                "audio": str(audio_path).replace("\\", "/"),
                "text": text,
                # 나머지는 나중에 국적별·급수별로 갈라 볼 때 쓰는 꼬리표다
                "id": r.get("id"),
                "task": r.get("task"),
                "source": r.get("source"),
                "speaker_id": r.get("speaker_id"),
                "nationality": r.get("nationality"),
                "topik_level": r.get("topik_level"),
                "prompt": r.get("prompt"),
                # 다듬기 전 원본과 무엇을 손댔는지를 함께 남긴다.
                # 나중에 라벨을 의심할 때 이 두 칸만 보면 되짚을 수 있다
                "ref_raw": r.get("ref"),
                "normalized_by": applied,
                "variant": args.variant,
            }
        )

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    write_manifest(out_rows, out_path)

    print(f"\n라벨 {len(out_rows)}건 → {out_path}")
    print(f"  다듬어진 것 {changed}건 · 음성을 못 구해 제외 {missing_audio}건")

    # ── 눈으로 확인하는 자리 ──
    # 정규화가 무엇을 바꿨는지 직접 보여 준다. 안 보여 주면 조용히 망가져도 모른다
    samples = [r for r in out_rows if r["normalized_by"]][:3] or out_rows[:2]
    print("\n다듬기 전/후 예시:")
    for s in samples:
        print(f"  [{s['id']}] 적용: {', '.join(s['normalized_by']) or '없음'}")
        print(f"    전: {s['ref_raw'][:70]}")
        print(f"    후: {s['text'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
