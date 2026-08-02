"""음성 답안이 실제로 채점까지 가는지 눈으로 확인하는 스크립트.

**이 스크립트는 진짜 Gemini 를 부른다.** (.env 의 GEMINI_API_KEY 가 필요하다)

확인하려는 것 다섯 가지:
  1. 음성 파일 주소를 주면 우리가 내려받아 받아쓰는가
  2. 받아쓴 글이 응시자가 말한 것과 얼마나 같은가 (글자 일치율)
  3. **학습자 오류를 고치지 않고 그대로 옮기는가** — 여기가 채점 정확도의 전제다
  4. 같은 음성을 두 번 받아쓰면 같은 글이 나오는가 (재현성)
  5. 받아쓴 글이 기존 말하기 채점을 끝까지 통과하는가

시험용 음성은 Gemini TTS 로 만든다(사람 녹음이 없어도 돌아가게).
만든 파일은 잠깐 뜨는 로컬 웹서버로 내보내서 **실제 다운로드 경로까지** 태운다.
로컬 파일을 바로 읽는 지름길을 쓰지 않는 이유는, 그러면 크기·형식 관문과
내려받기 코드가 한 번도 안 돌아서 "확인했다"고 말할 수 없기 때문이다.

실행:
    .venv\\Scripts\\python.exe scripts\\check_speech.py
    .venv\\Scripts\\python.exe scripts\\check_speech.py --file 녹음.wav
    .venv\\Scripts\\python.exe scripts\\check_speech.py --no-score   (받아쓰기만)
"""

from __future__ import annotations

import argparse
import difflib
import http.server
import socket
import sys
import threading
import time
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.llm.client import GeminiClient, LLMUnavailable  # noqa: E402
from src.scoring.pipeline import score_submission  # noqa: E402
from src.scoring.schema import (  # noqa: E402
    AudioInput,
    ChecklistItem,
    ItemInfo,
    Mode,
    ScoreRequest,
    TranscriptInput,
)
from src.speech.audio import AudioRequestError, load_local_audio  # noqa: E402
from src.speech.gemini_stt import DEFAULT_STT_MODEL, GeminiStt  # noqa: E402
from src.speech.port import SttUnavailable  # noqa: E402

# 시험용 답안. 학습자 오류('안 돼습니다')와 한글 숫자('삼번')를 일부러 넣었다.
# 받아쓰기가 이 둘을 표준형으로 고쳐 버리는지가 이 스크립트의 핵심 관찰 대상이다.
SPOKEN_TEXT = (
    "반장님, 지금 삼번 라인 포장기가 갑자기 멈췄습니다. "
    "제가 전원 버튼을 다시 눌러 봤는데 안 돼습니다. "
    "전원을 차단하고 정비팀에 연락할까요?"
)

# 받아쓰기가 지우면 안 되는 것들. (원문에 있는 말, 고쳐진 형태)
PRESERVATION_CHECKS = [
    ("안 돼습니다", "안 됐습니다", "학습자 문법 오류"),
    ("삼번", "3번", "한글 숫자 표기"),
]

ITEM = ItemInfo(
    item_id="SPK-CHECK",
    prompt="작업 중 기계가 멈췄습니다. 반장님에게 보고하고 어떻게 할지 물어보세요.",
    expected_register="formal",
    checklist=[
        ChecklistItem(id="c1", description="어떤 문제가 생겼는지 말했는가", weight=1.5),
        ChecklistItem(id="c2", description="자신이 시도한 조치를 말했는가", weight=1.0),
        ChecklistItem(id="c3", description="다음 지시를 요청했는가", weight=1.5),
    ],
    reference_keywords=["기계", "멈추", "정비"],
)

TTS_MODEL = "gemini-3.1-flash-tts-preview"
TTS_VOICE = "Kore"
TTS_SAMPLE_RATE = 24000


# ---------------------------------------------------------------------------
# 시험용 음성 만들기
# ---------------------------------------------------------------------------


def synthesize_wav(text: str, out_path: Path) -> Path:
    """글을 음성으로 만들어 wav 파일로 저장한다.

    사람 녹음이 없어도 이 스크립트가 돌아가게 하려는 것이다.
    TTS 는 발음이 또렷해서 **실제 외국인 응시자보다 받아쓰기가 쉽다.**
    여기서 나온 일치율은 현장 성능의 위쪽 한계로 봐야 한다.
    """
    raw = GeminiClient()._ensure_client()
    from google.genai import types

    response = raw.models.generate_content(
        model=TTS_MODEL,
        contents=text,
        config=types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=TTS_VOICE)
                )
            ),
        ),
    )
    # 돌아오는 것은 wav 파일이 아니라 소리 알갱이(PCM)라서 wav 껍데기를 씌워 준다
    pcm = response.candidates[0].content.parts[0].inline_data.data
    with wave.open(str(out_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(TTS_SAMPLE_RATE)
        handle.writeframes(pcm)
    return out_path


# ---------------------------------------------------------------------------
# 잠깐 뜨는 웹서버 — 실제 다운로드 경로를 태우기 위한 것
# ---------------------------------------------------------------------------


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
    """음성 파일을 잠깐 웹에 올리고 그 주소를 돌려준다.

    이렇게 하는 이유:
    로컬 파일을 바로 읽으면 편하지만, 그러면 실제 채점이 지나는 길
    (주소 확인 → 내려받기 → 크기·형식 관문)이 한 번도 안 돌아 본 셈이 된다.
    """
    # 비어 있는 포트를 운영체제에게 골라 달라고 한다
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    handler = type("Handler", (_AudioHandler,), {"audio_bytes": data})
    server = http.server.HTTPServer(("127.0.0.1", port), handler)
    # 채점이 도는 동안 뒤에서 계속 응답할 수 있게 딴 갈래로 돌린다
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}/answer.wav", server


# ---------------------------------------------------------------------------
# 결과 보여 주기
# ---------------------------------------------------------------------------


def compare(spoken: str, heard: str) -> float:
    """말한 글과 받아쓴 글이 얼마나 같은지 잰다(공백은 빼고 글자만 본다)."""
    return difflib.SequenceMatcher(
        None, spoken.replace(" ", ""), heard.replace(" ", "")
    ).ratio()


def report_preservation(heard: str) -> None:
    """받아쓰기가 응시자의 오류를 지우지 않았는지 확인한다.

    이것이 이 스크립트에서 가장 중요한 항목이다.
    받아쓰기가 문법을 고쳐 주면 조사를 틀린 응시자와 안 틀린 응시자가
    같은 글이 되고, 언어 사용 점수는 실력이 아니라 기계의 교정 실력을 잰 값이 된다.
    """
    print("\n  원문 보존 확인 (받아쓰기가 응시자의 말을 고쳤는가)")
    for original, corrected, label in PRESERVATION_CHECKS:
        if original in heard:
            print(f"    O 보존됨   '{original}' 그대로 ({label})")
        elif corrected in heard:
            print(f"    X 고쳐짐   '{original}' -> '{corrected}' ({label}) "
                  f"** 이 오류는 채점에서 감점되지 않는다 **")
        else:
            print(f"    ? 확인불가 '{original}' 도 '{corrected}' 도 없음 ({label})")


def main() -> None:
    parser = argparse.ArgumentParser(description="음성 답안이 채점까지 가는지 확인한다")
    parser.add_argument("--file", default="", help="쓸 음성 파일(없으면 TTS 로 만든다)")
    parser.add_argument("--text", default=SPOKEN_TEXT, help="TTS 로 만들 답안 글")
    parser.add_argument("--nationality", default="베트남", help="전사 보정에 쓸 응시자 국적")
    parser.add_argument("--no-score", action="store_true", help="받아쓰기만 하고 채점은 안 한다")
    parser.add_argument("--runs", type=int, default=2, help="같은 음성을 몇 번 받아쓸지 (기본 2)")
    args = parser.parse_args()

    print(f"받아쓰기 모델: {DEFAULT_STT_MODEL} (제공자: {GeminiStt.provider_name})")
    print("※ Azure 계정이 없어 Gemini 로 대신하고 있다. 발음 채점은 아직 없다(delivery 비중 0).")

    # ---- 1. 시험용 음성 준비 ----
    work_dir = Path(__file__).resolve().parent.parent / ".check_speech"
    work_dir.mkdir(exist_ok=True)

    if args.file:
        wav_path = Path(args.file)
        if not wav_path.exists():
            raise SystemExit(f"파일을 찾을 수 없습니다: {wav_path}")
        spoken = ""  # 사람 녹음은 정답 글이 없으니 일치율을 재지 않는다
        print(f"\n1) 음성 파일: {wav_path}")
    else:
        print("\n1) 시험용 음성을 만드는 중...")
        try:
            wav_path = synthesize_wav(args.text, work_dir / "check_speech.wav")
        except LLMUnavailable as exc:
            raise SystemExit(f"음성을 만들지 못했습니다: {exc}")
        spoken = args.text
        print(f"   만듦: {wav_path.name}")

    try:
        local = load_local_audio(wav_path)
    except AudioRequestError as exc:
        raise SystemExit(f"음성 파일을 읽지 못했습니다: {exc}")

    seconds = (local.duration_ms or 0) / 1000
    print(f"   {local.audio_format} / {seconds:.1f}초 / {local.size_bytes / 1024:.0f}KB")

    # ---- 2. 잠깐 웹에 올린다 (실제 다운로드 경로를 태우려는 것) ----
    url, server = serve_audio(local.data)
    print(f"\n2) 음성을 잠깐 웹에 올림: {url}")
    print("   (백엔드가 Object Storage 주소를 주는 상황을 흉내 낸 것이다)")

    audio = AudioInput(url=url)

    try:
        # ---- 3. 받아쓰기 (여러 번 해서 재현성까지 본다) ----
        print(f"\n3) 받아쓰는 중... ({args.runs}회)")
        stt = GeminiStt()
        transcripts: list[str] = []
        for number in range(1, args.runs + 1):
            started = time.perf_counter()
            try:
                result = stt.transcribe(audio, item_prompt=ITEM.prompt)
            except (AudioRequestError, SttUnavailable) as exc:
                raise SystemExit(f"받아쓰기에 실패했습니다: {exc}\n(받아쓰기에는 대체 경로가 없습니다)")
            elapsed = (time.perf_counter() - started) * 1000
            transcripts.append(result.text)

            print(f"\n   [{number}회] {elapsed:,.0f}ms "
                  f"| 입력 {result.input_tokens} 토큰 / 출력 {result.output_tokens} 토큰")
            print(f"   받아쓴 글: {result.text}")
            if spoken:
                print(f"   글자 일치율: {compare(spoken, result.text):.1%}")

        if spoken:
            print(f"\n   말한 글  : {spoken}")
            report_preservation(transcripts[0])

        # 재현성: 채점이 재현되려면 받아쓰기부터 재현돼야 한다
        if len(transcripts) >= 2:
            same = len(set(transcripts)) == 1
            print(f"\n  같은 음성을 {len(transcripts)}번 받아쓴 결과가 같은가: "
                  f"{'같다' if same else '다르다'}")
            if not same:
                print("    ※ 받아쓰기가 흔들리면 같은 답안의 점수도 흔들린다. "
                      "채점 재현성의 전제가 깨지는 항목이다.")
                for number, text in enumerate(transcripts, start=1):
                    print(f"      {number}회: {text}")

        if args.no_score:
            return

        # ---- 4. 채점 관통 (요청에 음성만 넣고 진짜 /score 길을 탄다) ----
        print("\n4) 음성 그대로 채점 파이프라인에 넣는 중...")
        print("   (answer_text 는 비워서 보낸다. 받아쓴 글이 그 자리에 들어간다)")
        started = time.perf_counter()
        response = score_submission(
            ScoreRequest(
                submission_id="check-speech-001",
                mode=Mode.SPEAKING,
                answer_text="",                # 비워 둔다 — 이것이 음성 채점의 조건이다
                item=ITEM,
                audio=audio,
                transcript=TranscriptInput(correct=True, nationality=args.nationality),
            )
        )
        total_ms = (time.perf_counter() - started) * 1000

        meta = response.meta
        print(f"\n   종합 {response.overall_score}점 ({response.overall_grade}) "
              f"| 신뢰도 {meta.reliability.value} "
              f"| 표시 가능 {meta.safe_to_show_candidate}")
        print(f"   전체 걸린 시간: {total_ms:,.0f}ms "
              f"(그중 받아쓰기 {meta.timings_ms.get('stt_ms', 0):,.0f}ms)")

        print("\n   결과에 남은 받아쓰기 내력 (백엔드가 저장해야 하는 값)")
        print(f"     stt_provider      : {meta.stt_provider}")
        print(f"     stt_model         : {meta.stt_model}")
        print(f"     audio_duration_ms : {meta.audio_duration_ms}")
        print(f"     stt_transcript    : {meta.stt_transcript}")

        print("\n   영역별 점수")
        for sub in response.subscores:
            score = "미채점" if sub.score is None else f"{sub.score:.1f}점"
            print(f"     {sub.label}: {score} ({sub.status.value}, 비중 {sub.weight:.2f})")

        print("\n   체크리스트 판정")
        for check in response.checklist_results:
            mark = "O" if check.met else "X"
            quote = check.evidence[0].quote if check.evidence else "(근거 없음)"
            print(f"     {mark} {check.description}")
            print(f"        근거: \"{quote}\"")

        print(f"\n   STT 보정: {meta.transcript_correction_applied} "
              f"({meta.transcript_change_count}군데, "
              f"신뢰도 낮음 오류 {meta.transcript_low_confidence_errors}건)")
        for evidence in meta.transcript_diff[:5]:
            print(f"     '{evidence.quote}' -> {evidence.comment}")

        for warning in response.warnings:
            print(f"\n   경고: {warning}")

        print("\n=== 음성 → 받아쓰기 → 채점 완주 ===")

    finally:
        # 웹서버는 반드시 내린다. 안 내리면 스크립트가 안 끝난다
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
