"""Azure 발음 평가가 실제로 도는지 눈으로 확인하는 스크립트.

**이 스크립트는 진짜 Azure 를 부른다.** (.env 의 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION 필요)

확인하려는 것 네 가지:
  1. 실제 응시자 녹음을 Azure 가 받아쓰는가
  2. 발음 점수 네 가지(정확도·유창성·완전성·종합)가 숫자로 나오는가
  3. **어느 낱말이 몇 점이었는지가 근거로 남는가** — 여기가 이 기능의 핵심이다.
     점수만 나오고 근거가 없으면 이 프로젝트에서는 결함이다
  4. 그 점수가 채점까지 흘러가 발화 전달력(delivery) 영역 점수가 되는가

로컬 파일을 바로 읽지 않고 잠깐 뜨는 웹서버로 내보내는 이유:
그래야 실제 채점이 지나는 길(주소 확인 → 내려받기 → 크기·형식 관문)이 다 돈다.
지름길로 확인하면 "확인했다"고 말할 수 없다.

실행:
    .venv\\Scripts\\python.exe scripts\\check_azure_pronunciation.py --file 녹음.wav
    .venv\\Scripts\\python.exe scripts\\check_azure_pronunciation.py --file 낭독.wav --reference "나는 집 내부 공사를 끝냈다."
    .venv\\Scripts\\python.exe scripts\\check_azure_pronunciation.py --file 답안.wav --no-score
"""

from __future__ import annotations

import argparse
import http.server
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.features.pronunciation import extract_pronunciation_features  # noqa: E402
from src.scoring.pipeline import score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    AudioInput,
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreOptions,
    ScoreRequest,
)
from src.speech.azure_stt import AzureStt  # noqa: E402
from src.speech.port import SttUnavailable  # noqa: E402

#: 낭독형이 아닐 때 쓰는 시험용 문항. 자유 발화라 정답지를 주지 않는다.
FREE_ITEM = ItemInfo(
    item_id="SPK-AZURE-CHECK",
    prompt="작업 중 기계가 멈췄습니다. 반장님에게 보고하고 어떻게 할지 물어보세요.",
    item_type="incident_report",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가", weight=1.5),
        ChecklistItem(id="c2", description="다음 지시를 요청했는가", weight=1.5),
    ],
    reference_keywords=["기계", "멈추", "정비"],
)


class _AudioHandler(http.server.BaseHTTPRequestHandler):
    """메모리에 든 음성 파일 하나만 내주는 아주 작은 웹서버."""

    audio_bytes = b""

    def do_GET(self):  # noqa: N802 (표준 라이브러리가 정한 이름이다)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(self.audio_bytes)))
        self.end_headers()
        self.wfile.write(self.audio_bytes)

    def log_message(self, *args):
        """웹서버가 화면에 로그를 뿌리지 않게 막는다(확인할 내용이 묻힌다)."""


def serve_audio(data: bytes) -> tuple[str, http.server.HTTPServer]:
    """음성 파일을 잠깐 웹에 올리고 그 주소를 돌려준다."""
    # 비어 있는 포트를 운영체제에게 골라 달라고 한다
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    handler = type("Handler", (_AudioHandler,), {"audio_bytes": data})
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/answer.wav", server


def print_assessment(assessment) -> None:
    """발음 점수와 낱말별 결과를 사람이 읽게 찍는다."""
    print("\n  발음 점수 (0~100)")
    for label, value in (
        ("정확도(Accuracy)", assessment.accuracy),
        ("유창성(Fluency)", assessment.fluency),
        ("완전성(Completeness)", assessment.completeness),
        ("종합(PronScore)", assessment.overall),
        ("억양(Prosody)", assessment.prosody),
    ):
        # 값을 못 받은 항목은 '없음'이라고 적는다. 0으로 때우면 '아주 나빴다'로 읽힌다
        print(f"    {label:<22} {value if value is not None else '없음(제공자가 주지 않음)'}")

    print(f"\n  평가 방식: {'낭독형(제시문을 정답지로 줌)' if assessment.scripted else '자유 발화(정답지 없음)'}")
    print(f"  낱말 수: {len(assessment.words)}")
    print("\n  낱말별 결과 (점수 낮은 것부터 10개)")
    ranked = sorted(
        assessment.words, key=lambda w: w.accuracy if w.accuracy is not None else 999.0
    )
    for word in ranked[:10]:
        score = f"{word.accuracy:5.1f}" if word.accuracy is not None else "  없음"
        print(f"    {score}  {word.word:<12} {word.error_type}")
    for warning in assessment.warnings:
        print(f"    · {warning}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Azure 발음 평가가 실제로 도는지 확인한다")
    parser.add_argument("--file", required=True, help="확인할 wav 파일 경로")
    parser.add_argument(
        "--reference",
        default="",
        help="낭독형으로 확인할 때 읽어야 할 제시문(주면 낭독형으로 부른다)",
    )
    parser.add_argument("--no-score", action="store_true", help="받아쓰기·발음만 보고 채점은 안 한다")
    args = parser.parse_args()

    stt = AzureStt()
    print(f"받아쓰기·발음 평가: {stt.provider_name} / {stt.model_name}")
    if not stt.available:
        print("X 열쇠가 없다. .env 에 AZURE_SPEECH_KEY / AZURE_SPEECH_REGION 이 필요하다.")
        return

    data = Path(args.file).read_bytes()
    url, server = serve_audio(data)
    print(f"음성 파일: {args.file} ({len(data) / 1024:.0f}KB)")

    # 제시문을 주면 낭독형으로 부른다. 그때만 '얼마나 읽었는가'를 잴 수 있다
    scripted = bool(args.reference.strip())
    item = FREE_ITEM.model_copy(
        update={"item_type": "read_aloud", "prompt": args.reference} if scripted else {}
    )

    try:
        result = stt.transcribe(
            AudioInput(url=url, format="wav"),
            item_prompt=item.prompt,
            item_type=item.item_type,
        )
    except SttUnavailable as exc:
        print(f"X 받아쓰기 실패: {exc}")
        server.shutdown()
        return

    print(f"\n  받아쓴 글: {result.text}")
    print(f"  걸린 시간: {result.elapsed_ms:.0f}ms / 녹음 길이: {result.audio_duration_ms}ms")

    if result.pronunciation is None:
        print("X 발음 점수가 오지 않았다.")
        server.shutdown()
        return
    print_assessment(result.pronunciation)

    # 자질로 옮겨진 모습을 확인한다. 근거가 붙어 있는지가 관건이다
    features = extract_pronunciation_features(result.pronunciation, result.text)
    print("\n  자질로 옮긴 결과")
    for feature in features:
        print(f"    {feature.id:<20} {feature.status.value:<16} {feature.value} "
              f"(근거 {len(feature.evidence)}개)")

    if args.no_score:
        server.shutdown()
        return

    # 채점까지 태운다. 발화 전달력 영역이 실제로 점수를 받는지 보는 자리다
    request = ScoreRequest(
        submission_id="AZURE-CHECK-1",
        mode=Mode.SPEAKING,
        item=item,
        audio=AudioInput(url=url, format="wav"),
        options=ScoreOptions(use_llm=True),
    )
    response = score_submission(request, stt=stt)
    server.shutdown()

    print(f"\n  종합 점수 {response.overall_score} ({response.overall_grade})")
    print("  영역별")
    for sub in response.subscores:
        print(f"    {sub.label:<14} {str(sub.score):<8} 비중 {sub.weight:<8} {sub.status.value}")
        for ev in sub.evidence[:3]:
            if ev.source.value == "azure":
                print(f"        근거: {ev.comment}")


if __name__ == "__main__":
    main()
