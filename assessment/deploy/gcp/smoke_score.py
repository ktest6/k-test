"""GCP VM 위에서 말하기 채점 한 건을 끝까지 태워 보는 스모크 스크립트.

무엇을 확인하나:
  음성 파일 주소 → 채점 서버가 내려받음 → LoRA 받아쓰기(8100) → Gemini 채점 → 점수
  이 한 줄이 VM 안에서 실제로 도는지. (healthcheck 는 "살아 있나"만 보고, 이건 "일을 하나"를 본다)

어떻게:
  wav 파일을 잠깐 뜨는 로컬 웹서버(127.0.0.1:9000)로 내보내고, 그 주소를 /score 에 준다.
  파일 경로를 직접 주는 지름길을 안 쓰는 이유는 내려받기 코드까지 한 번은 돌아야 하기 때문.

wav 말고 브라우저 녹음(webm)·아이폰 녹음(m4a)도 그대로 넣을 수 있다.
파일 확장자를 보고 Content-Type 과 audio.format 을 맞춰 보내므로, **실제 응시 답안과
같은 형식으로** 한 번 태워 볼 수 있다(채점 서버가 입구에서 wav 로 바꾼다).
webm 을 넣었는데 503 이 나면 서버에 ffmpeg 이 없는 것이다 — /health 의
ffmpeg_available 을 보라.

실행 (VM 에서, 표준 라이브러리만 씀 — venv 필요 없음):
    python3 smoke_score.py 음성.wav
    python3 smoke_score.py 답안.webm            (브라우저 녹음 그대로)
    python3 smoke_score.py 음성.wav --api http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import http.server
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

#: 파일 확장자 -> (내보낼 때 붙일 Content-Type, 채점 요청에 적을 audio.format).
#: 채점 서버는 요청의 format 을 가장 먼저 믿으므로, 여기가 틀리면 형식을 속인 셈이 된다.
#: (서버는 알맹이 앞머리도 따로 확인하지만, 스모크에서까지 거짓을 보낼 이유는 없다)
EXT_TO_TYPE = {
    ".wav": ("audio/wav", "wav"),
    ".webm": ("audio/webm", "webm"),
    ".m4a": ("audio/mp4", "m4a"),
    ".mp4": ("audio/mp4", "m4a"),
    ".mp3": ("audio/mpeg", "mp3"),
    ".ogg": ("audio/ogg", "ogg"),
}

REQUEST = {
    "submission_id": "gcp-smoke-0001",
    "mode": "speaking",
    "answer_text": "",  # 비워 둔다 — 우리가 받아쓴 글이 여기 들어간다
    "item": {
        "item_id": "spk-smoke",
        "prompt": "자기소개를 하거나 최근 있었던 일을 자유롭게 말하십시오.",
        "item_type": "free_response",
        "expected_register": "formal",
        "checklist": [
            {"id": "c1", "description": "자기 이야기를 문장으로 말했는가", "weight": 1.0},
            {"id": "c2", "description": "두 문장 이상 이어서 말했는가", "weight": 1.0},
        ],
        "reference_keywords": [],
    },
    "options": {"use_llm": True, "weights_profile": "provisional_v0"},
}


def serve(wav: Path, port: int, content_type: str = "audio/wav") -> http.server.HTTPServer:
    """음성 파일 하나를 잠깐 인터넷 주소로 내보내는 작은 웹서버.

    content_type 을 파일 형식에 맞춰 붙인다. 채점 서버는 요청에 format 이 없을 때
    이 값으로 형식을 정하므로, wav 라고 고정해 두면 webm 을 넣었을 때 거짓말이 된다.
    """
    data = wav.read_bytes()

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # 조용히
            pass

    srv = http.server.HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav", help="음성 파일 (wav·webm·m4a·mp3·ogg)")
    ap.add_argument("--api", default="http://127.0.0.1:8001")
    ap.add_argument("--port", type=int, default=9000)
    ap.add_argument("--api-key", default="", help="KTEST_API_KEY 를 켰다면 같은 값")
    a = ap.parse_args()

    wav = Path(a.wav)
    if not wav.is_file():
        sys.exit(f"파일 없음: {wav}")

    # 확장자로 형식을 정한다. 모르는 확장자면 wav 로 보되 그렇게 했다고 알려 준다
    ext = wav.suffix.lower()
    content_type, fmt = EXT_TO_TYPE.get(ext, ("audio/wav", "wav"))
    if ext not in EXT_TO_TYPE:
        print(f"[주의] 모르는 확장자 '{ext}' — wav 로 보고 보낸다.")
    print(f"보내는 형식: {fmt} ({content_type})")

    srv = serve(wav, a.port, content_type)

    body = dict(REQUEST)
    # 주소 끝의 확장자도 실제 형식과 맞춰 준다(서버가 format 다음으로 보는 값이다)
    body["audio"] = {"url": f"http://127.0.0.1:{a.port}/answer{ext or '.wav'}", "format": fmt}
    req = urllib.request.Request(
        f"{a.api}/score",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", **({"X-API-Key": a.api_key} if a.api_key else {})},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            out = json.loads(r.read())
            code = r.status
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}\n{e.read().decode(errors='replace')}")
        srv.shutdown()
        sys.exit(1)
    dt = time.time() - t0
    srv.shutdown()

    meta = out.get("meta") or {}
    print(f"HTTP {code}  ({dt:.1f}초)")
    print("받아쓰기  :", meta.get("stt_provider"), "/", meta.get("stt_model"))
    print("받아쓴 글 :", meta.get("stt_transcript") or "(응답에 없음)")
    print("종합 점수 :", out.get("overall_score"), "/ 등급:", out.get("overall_grade"))
    for s in out.get("subscores") or []:
        print(f"  - {s.get('area')}: {s.get('score')}  ({s.get('status')})")
    print("신뢰도    :", meta.get("reliability"), "-", meta.get("reliability_reason"))
    warns = out.get("warnings") or []
    if warns:
        print("경고:", *warns, sep="\n  ")
    print("\n(전체 응답은 smoke_result.json 에 저장)")
    Path("smoke_result.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
