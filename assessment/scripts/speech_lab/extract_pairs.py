# -*- coding: utf-8 -*-
"""① 데이터 추출·정제기 — 원본 뭉치에서 (음성, 사람 전사) 쌍을 골라 목록으로 만든다.

이 실험(기함: 오류 보존 받아쓰기 LoRA)의 재료는 딱 하나다.
**"외국인이 실제로 말한 소리"와 "그 사람이 틀린 것까지 그대로 살려 적은 사람 전사"의 짝.**
상용 받아쓰기는 이 틀린 자리를 조용히 고쳐 버리는데(실측: 세탁율 27.5%),
그러면 채점기가 볼 오류가 사라진다. 그래서 이 짝을 모아 모델을 다시 가르치려는 것이다.

이 스크립트가 하는 일은 세 가지다.
  1) 6GB짜리 zip 을 풀지 않고 안에서 라벨(정답지)만 훑어본다
  2) 학습에 쓰면 안 되는 것을 걸러낸다 (아래 '정제 기준')
  3) 남은 것을 한 줄에 하나씩 적은 목록 파일(JSONL)로 저장한다

쓰는 법:
    python extract_pairs.py --source 71479 --task LAR --max-n 200 \
        --out ../../../data/manifests/71479_lar.jsonl
    (wav 파일까지 꺼내려면 --extract-audio 를 덧붙인다)
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import (  # noqa: E402
    DATA_ROOT,
    SOURCES,
    Pair,
    enable_utf8_output,
    measure_rms,
    write_manifest,
)

# ── 정제 기준 ────────────────────────────────────────────────────────────────
# 출처: HUFS 한국어 L2 MDD 논문(Appl. Sci. 2026, 16, 2426)의 전처리 레시피를
# 그대로 물려받았다. 그 논문이 같은 AI Hub 세트를 쓰면서 겪은 함정을 적어 뒀는데,
# 우리가 다시 밟을 이유가 없어서 출발선으로 받는다.
#   - 옆 사람 목소리가 섞인 녹음이 있다  -> 소리 크기(RMS)로 거른다
#   - 낭독인데 40초씩 늘어지는 녹음이 있다 -> 길이 상한을 둔다
#   - 같은 문장이 수천 번 겹친다(사과 5,727회) -> 화자당 건수를 막는다

#: 낭독(LAR) 길이 범위(초). 짧은 문장 하나를 읽는 과제라 20초를 넘으면
#: 더듬거나 다시 읽은 녹음일 가능성이 높다.
LAR_DURATION_RANGE = (2.0, 20.0)

#: 자유발화(ATQ) 길이 범위(초). 8초 아래는 대답을 하다 만 것이고,
#: 45초를 넘으면 학습 때 메모리를 크게 먹는다(Whisper 는 30초 단위로 자른다).
ATQ_DURATION_RANGE = (8.0, 45.0)

#: 한 사람에게서 가져올 최대 건수. 목소리 몇 명이 데이터를 차지해 버리면
#: 모델이 '그 사람 말투'를 외우게 된다. 라벨 다양성을 위한 상한이다.
MAX_PER_SPEAKER = 4

#: 소리가 이보다 작으면 버린다. HUFS 논문의 RMS 0.01 기준을 우리 눈금
#: (0~32767)으로 환산한 값이다: 0.01 x 32767 = 327.67
MIN_RMS = 327.67


def _duration_ok(task: str, seconds: float | None) -> bool:
    """녹음 길이가 과제 유형에 맞는 범위 안인지 본다."""
    if seconds is None:
        return False
    low, high = LAR_DURATION_RANGE if task == "LAR" else ATQ_DURATION_RANGE
    return low <= seconds <= high


def _task_of(stem: str) -> str | None:
    """파일 이름에서 과제 유형을 읽는다.

    AI Hub 파일명은 `00067-F-91-VI-A-LAR010-0004411` 처럼 생겼고
    가운데 토막이 과제 종류다. LAR=낭독(정해진 문장 읽기), ATQ=자유발화(질문에 답하기).
    """
    if "LAR" in stem:
        return "LAR"
    if "ATQ" in stem:
        return "ATQ"
    return None


def collect_from_zip(source: str, task_filter: str, max_n: int) -> list[Pair]:
    """zip 을 열어 조건에 맞는 짝을 모은다(아직 wav 는 꺼내지 않는다).

    zip 을 풀지 않는 이유: 둘이 합쳐 6GB 인데 우리가 실제로 쓸 것은 몇백 건이다.
    라벨(json)만 읽어 후보를 정하고, wav 는 필요한 것만 나중에 꺼낸다.
    """
    zip_path = SOURCES[source]["path"]
    if not zip_path.exists():
        raise FileNotFoundError(f"원본 zip 이 없다: {zip_path}")

    z = zipfile.ZipFile(zip_path)
    names = z.namelist()

    # 어떤 wav 가 들어 있는지 먼저 이름표만 만들어 둔다(라벨은 있는데 소리가 없는
    # 경우가 실제로 있다 — 그건 학습에 못 쓰므로 여기서 걸러진다)
    sounds = {Path(n).stem: n for n in names if n.endswith(".wav")}

    # 라벨 파일 목록. 정렬해 두면 몇 번을 돌려도 같은 순서로 뽑혀 결과가 재현된다
    labels = sorted(
        n for n in names if n.endswith(".json") and "라벨링데이터/Speech" in n
    )

    pairs: list[Pair] = []
    per_speaker: dict[str, int] = {}
    dropped = {"과제불일치": 0, "wav없음": 0, "전사비어있음": 0, "길이벗어남": 0, "화자상한": 0}

    for member in labels:
        stem = Path(member).stem
        task = _task_of(stem)

        # 요청한 과제 유형만 남긴다
        if task is None or (task_filter != "all" and task != task_filter):
            dropped["과제불일치"] += 1
            continue

        # 라벨은 있는데 소리 파일이 없는 짝은 학습에 쓸 수 없다
        if stem not in sounds:
            dropped["wav없음"] += 1
            continue

        try:
            d = json.loads(z.read(member).decode("utf-8-sig"))
        except Exception:
            dropped["전사비어있음"] += 1
            continue

        rec = d.get("RecordingMetadata", {})
        spk = d.get("SpeakerMetadata", {})
        prompt = (rec.get("prompt") or "").strip()
        ref = (rec.get("orthographic") or "").strip()

        # 사람 전사가 비어 있으면 정답지가 없는 것이라 쓸모가 없다
        if not ref:
            dropped["전사비어있음"] += 1
            continue

        seconds = rec.get("RecordedTime")
        if not _duration_ok(task, seconds):
            dropped["길이벗어남"] += 1
            continue

        # 한 사람이 데이터를 독차지하지 않게 막는다
        user_id = str(d.get("UserID", "?"))
        if per_speaker.get(user_id, 0) >= MAX_PER_SPEAKER:
            dropped["화자상한"] += 1
            continue
        per_speaker[user_id] = per_speaker.get(user_id, 0) + 1

        pairs.append(
            Pair(
                id=stem,
                audio=f"pairs/{source}/{stem}.wav",
                ref=ref,
                prompt=prompt,
                task=task,
                source=source,
                speaker_id=user_id,
                nationality=str(spk.get("nationality", "?")),
                topik_level=str(spk.get("topik_level", "?")),
                duration_sec=float(seconds),
                # 사람이 매긴 점수(0~5). 자유발화에만 뜻이 있고 낭독은 참고용이다.
                # 나중에 '전사가 좋아지면 채점 일치율이 오르는가'를 잴 때 정답으로 쓴다
                evals={
                    "delivery": d.get("EvaluationMetadata", {}).get("DeliveryEval"),
                    "language_use": d.get("EvaluationMetadata", {}).get("LanguageUseEval"),
                    "content": d.get("EvaluationMetadata", {}).get("ContentEval"),
                },
                zip_path=str(zip_path),
                zip_member=sounds[stem],
            )
        )

        if max_n and len(pairs) >= max_n:
            break

    print(f"  걸러낸 내역: {dropped}")
    return pairs


def collect_from_505(task_filter: str, max_n: int) -> list[Pair]:
    """505 세트(이미 압축이 풀려 있음)에서 짝을 모은다.

    이쪽은 앞의 둘과 라벨 모양이 다르다.
      - `AnswerLabelText` 가 사람 전사이고, 말이 끊긴 자리에 '+' 를 붙여 놓았다
      - 질문에 답하는 형식이라 대부분 자유발화(ATQ)로 본다
      - 읽기 과제(`ReadingLabelText`)가 채워져 있으면 낭독(LAR)으로 본다
    """
    root = SOURCES["505"]["path"]
    label_paths = sorted(glob.glob(str(root / "라벨링데이터" / "1.한국일반" / "*.json")))
    if not label_paths:
        raise FileNotFoundError(f"505 라벨을 찾지 못했다: {root}")

    pairs: list[Pair] = []
    per_speaker: dict[str, int] = {}
    dropped = {"과제불일치": 0, "wav없음": 0, "전사비어있음": 0, "길이벗어남": 0, "화자상한": 0}

    for lp in label_paths:
        try:
            d = json.load(open(lp, encoding="utf-8"))
        except Exception:
            dropped["전사비어있음"] += 1
            continue

        tr = d.get("transcription") or {}
        reading = (tr.get("ReadingLabelText") or "").strip()

        # 읽기 전사가 있으면 낭독, 없으면 질문-답변(자유발화)
        if reading:
            task, ref, prompt = "LAR", reading, (tr.get("Reading") or "").strip()
        else:
            task = "ATQ"
            ref = (tr.get("AnswerLabelText") or "").strip()
            prompt = (tr.get("Question") or "").strip()

        if task_filter != "all" and task != task_filter:
            dropped["과제불일치"] += 1
            continue
        if not ref:
            dropped["전사비어있음"] += 1
            continue

        wav = root / "원천데이터" / "1.한국일반" / d.get("fileName", "")
        if not wav.exists():
            dropped["wav없음"] += 1
            continue

        # 길이가 문자열("12.835")로 적혀 있어 숫자로 바꿔 준다
        try:
            seconds = float((d.get("file_info") or {}).get("recordTime", "0"))
        except (TypeError, ValueError):
            seconds = None
        if not _duration_ok(task, seconds):
            dropped["길이벗어남"] += 1
            continue

        spk_id = str(d.get("SpeakerID", "?"))
        if per_speaker.get(spk_id, 0) >= MAX_PER_SPEAKER:
            dropped["화자상한"] += 1
            continue
        per_speaker[spk_id] = per_speaker.get(spk_id, 0) + 1

        skill = d.get("skill_info") or {}
        pairs.append(
            Pair(
                id=Path(d["fileName"]).stem,
                # 이미 풀려 있는 파일이므로 data 폴더 기준 상대 경로를 그대로 적는다
                audio=str(wav.relative_to(DATA_ROOT)).replace("\\", "/"),
                ref=ref,
                prompt=prompt,
                task=task,
                source="505",
                speaker_id=spk_id,
                nationality=str(skill.get("motherTongue", "?")),
                topik_level=str(skill.get("topikGrade", "?")),
                duration_sec=seconds,
                # 505 에는 0~5 점수가 없고 '상/중/하' 등급만 있다. 있는 그대로 담는다
                evals={"speech_level": tr.get("SentenceSpeechLV")},
            )
        )
        if max_n and len(pairs) >= max_n:
            break

    print(f"  걸러낸 내역: {dropped}")
    return pairs


def extract_audio_files(pairs: list[Pair], source: str) -> tuple[int, int]:
    """골라 둔 짝의 wav 를 실제 파일로 꺼내고, 너무 조용한 것은 목록에서 뺀다.

    소리 크기 검사를 여기서 하는 이유: 파일을 읽어야만 잴 수 있는 값이라
    목록만 만드는 단계에서는 알 수 없다. 그래서 wav 를 꺼내는 이 자리에서 함께 본다.

    돌려주는 값은 (꺼낸 개수, 조용해서 버린 개수)다.
    """
    out_dir = DATA_ROOT / "pairs" / source
    out_dir.mkdir(parents=True, exist_ok=True)

    kept, too_quiet = [], 0
    for p in pairs:
        target = DATA_ROOT / p.audio

        # 이미 꺼내 둔 파일이면 다시 쓰지 않는다(두 번째 실행이 빨라진다)
        if target.exists():
            data = target.read_bytes()
        else:
            data = (
                zipfile.ZipFile(p.zip_path).read(p.zip_member)
                if p.zip_path
                else target.read_bytes()
            )

        rms = measure_rms(data)
        # 소리가 거의 없는 녹음은 학습에 넣으면 '무음 = 이 문장' 을 외우게 된다
        if rms is not None and rms < MIN_RMS:
            too_quiet += 1
            continue

        if not target.exists():
            target.write_bytes(data)
        kept.append(p)

    # 걸러진 것을 원래 목록에서도 빼야 목록과 파일이 어긋나지 않는다
    pairs[:] = kept
    return len(kept), too_quiet


def main() -> int:
    enable_utf8_output()
    ap = argparse.ArgumentParser(description="AI Hub 원본에서 (음성, 사람 전사) 쌍을 뽑는다")
    ap.add_argument("--source", required=True, choices=["71469", "71479", "505"],
                    help="원본 데이터셋 번호")
    ap.add_argument("--task", default="all", choices=["LAR", "ATQ", "all"],
                    help="LAR=낭독, ATQ=자유발화")
    ap.add_argument("--out", required=True, help="만들 목록 파일 경로(.jsonl)")
    ap.add_argument("--max-n", type=int, default=0, help="최대 몇 건까지 (0=제한 없음)")
    ap.add_argument("--extract-audio", action="store_true",
                    help="wav 를 data/pairs/<source>/ 로 실제로 꺼낸다 (+소리 크기 검사)")
    args = ap.parse_args()

    info = SOURCES[args.source]
    print(f"원본: {args.source} ({info['label']}) · 과제 {args.task}")

    if info["kind"] == "aihub_zip":
        pairs = collect_from_zip(args.source, args.task, args.max_n)
    else:
        pairs = collect_from_505(args.task, args.max_n)

    if not pairs:
        print("조건에 맞는 짝이 없다. --task 나 길이 기준을 확인하라.")
        return 1

    if args.extract_audio:
        kept, quiet = extract_audio_files(pairs, args.source)
        print(f"  wav 꺼냄: {kept}건 · 너무 조용해서 버림: {quiet}건 → {DATA_ROOT / 'pairs' / args.source}")
    else:
        print("  (목록만 만든다 — 소리 크기 검사는 --extract-audio 를 걸어야 돌아간다)")

    out_path = Path(args.out)
    if not out_path.is_absolute():
        out_path = Path.cwd() / out_path
    write_manifest([p.to_dict() for p in pairs], out_path)

    # ── 눈으로 확인하는 자리 ──
    # 값이 맞는지 코드를 읽어 알기 어려우므로, 뽑힌 결과를 직접 보여 준다
    print(f"\n총 {len(pairs)}건 → {out_path}")
    lengths = [p.duration_sec for p in pairs if p.duration_sec]
    if lengths:
        print(f"길이: 평균 {sum(lengths)/len(lengths):.1f}초 · 최소 {min(lengths):.1f} · 최대 {max(lengths):.1f}")
    nats = {}
    for p in pairs:
        nats[p.nationality] = nats.get(p.nationality, 0) + 1
    print("국적 분포: " + ", ".join(f"{k} {v}" for k, v in sorted(nats.items(), key=lambda x: -x[1])[:8]))

    print("\n첫 두 줄 미리보기:")
    for p in pairs[:2]:
        print(f"  [{p.id}] 과제 {p.task} · {p.duration_sec}초 · {p.nationality} · TOPIK {p.topik_level}")
        print(f"    제시문: {p.prompt[:60]}")
        print(f"    사람전사: {p.ref[:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
