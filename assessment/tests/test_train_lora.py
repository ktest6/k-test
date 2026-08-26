# -*- coding: utf-8 -*-
"""④ LoRA 학습 스크립트 회귀 테스트 — 2단 '고품질 마무리' 학습 옵션이 목적이다.

2단 마무리란: 대량 데이터로 이미 배운 판(v2 어댑터)을 얹고, 그 위에 사람이 검수한
소량 고품질 데이터를 낮은 학습률로 조금만 더 배우게 하는 것.

여기서 못 박는 것 셋:
  ① `--init-adapter` 를 주면 그 값이 읽히고, 안 주면 None 이다(= 지금까지 하던 대로)
  ② 라벨 파일의 정답 칸 이름이 `text` 든 `ref` 든 읽히고,
     `grade`·`auditor` 같은 학습에 안 쓰는 칸은 조용히 버려진다
  ③ `--init-adapter` 없이 부르면 예전처럼 **빈 LoRA 판을 새로 덧대고**,
     주면 이미 배운 판을 `is_trainable=True`(계속 배울 수 있게) 로 얹는다

무거운 모델은 절대 부르지 않는다. ③ 은 Whisper·peft 자리에 가짜를 끼워 넣어
'어느 길로 갔는지'만 본다 — 진짜 모델을 부르면 테스트 한 번에 몇 분이 든다.

실행: .venv\\Scripts\\python.exe -m pytest tests/test_train_lora.py -q
"""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "speech_lab"))

import train_lora  # noqa: E402
from train_lora import LORA_TARGETS, build_parser, load_rows  # noqa: E402


# ── ① 옵션 파싱 ────────────────────────────────────────────────────────────────

def test_init_adapter_기본값은_없음():
    """옵션을 안 주면 None 이어야 한다. 이래야 지금까지의 학습이 그대로 돈다."""
    args = build_parser().parse_args(["--data", "labels.jsonl"])
    assert args.init_adapter is None
    assert args.lora_r == 16  # 기존 기본값도 그대로


def test_init_adapter_를_주면_그_폴더가_읽힌다():
    """2단 마무리 학습에서 실제로 쓰는 조합(낮은 학습률·1바퀴)까지 함께 확인한다."""
    args = build_parser().parse_args([
        "--data", "extra/team2000_train_stage2.jsonl",
        "--init-adapter", "adapters/v2",
        "--lr", "3e-6", "--epochs", "1", "--out", "adapters/v3-stage2",
    ])
    assert args.init_adapter == "adapters/v2"
    assert args.lr == pytest.approx(3e-6)
    assert args.epochs == pytest.approx(1)


# ── ② 라벨 읽기 ────────────────────────────────────────────────────────────────

def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    """줄마다 JSON 하나인 라벨 파일을 만든다."""
    path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                    encoding="utf-8")
    return path


def test_ref_칸과_여분_칸이_섞여_있어도_읽힌다(tmp_path, capsys):
    """감사 회수본에서 만든 목록(ref·grade·auditor)이 그대로 학습에 들어가야 한다."""
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"fake")  # 소리 내용은 안 보고 '있는지'만 본다
    data = _write_jsonl(tmp_path / "stage2.jsonl", [
        # 감사 회수본 형식: 정답은 ref, grade·auditor 는 학습에 쓰지 않는 여분 칸
        {"id": "x1", "audio": str(wav), "ref": "저는 삼년에 한국어를 배웠어요.",
         "grade": "금", "auditor": "김도영"},
        # 예전 형식(text)도 계속 읽혀야 한다
        {"audio": str(wav), "text": "집들은 참 좋은데 너무 비쌌다.", "task": "LAR"},
        # 소리 파일이 없는 줄은 학습 전에 빠진다
        {"audio": str(tmp_path / "없는소리.wav"), "ref": "빠져야 한다"},
        # 정답이 비어 있는 줄도 뺀다 (빈 문장을 정답으로 배우면 안 된다)
        {"audio": str(wav), "ref": "   "},
    ])

    rows = load_rows(data)

    # 남는 것은 두 줄, 그리고 칸은 audio·text 두 개로 통일된다
    assert [r["text"] for r in rows] == ["저는 삼년에 한국어를 배웠어요.",
                                         "집들은 참 좋은데 너무 비쌌다."]
    assert all(set(r) == {"audio", "text"} for r in rows)

    # 뺀 줄은 조용히 사라지지 않고 이유와 함께 보고된다
    out = capsys.readouterr().out
    assert "소리 파일이 없어 뺀 줄 1개" in out
    assert "정답 전사" in out and "뺀 줄 1개" in out


def test_dry_n_만큼만_읽는다(tmp_path):
    """--dry-n 은 앞에서 몇 줄만 보고 끊는 값이다(헛돌리기를 빨리 끝내려는 것)."""
    wav = tmp_path / "a.wav"
    wav.write_bytes(b"fake")
    data = _write_jsonl(tmp_path / "many.jsonl",
                        [{"audio": str(wav), "ref": f"문장 {i}"} for i in range(5)])

    assert len(load_rows(data, max_n=2)) == 2


# ── ③ 새 판이냐, 이어서 배우느냐 ───────────────────────────────────────────────

class _가짜모델:
    """Whisper 대신 세워 두는 허수아비. 설정을 붙였다 뗐다 할 수만 있으면 된다."""

    def __init__(self):
        self.generation_config = types.SimpleNamespace()

    def print_trainable_parameters(self):
        pass


@pytest.fixture()
def 가짜기계(monkeypatch, tmp_path):
    """transformers·peft 자리에 가짜를 끼워 넣고, 무엇이 불렸는지 적어 둔다.

    build_model 은 함수 안에서 import 하므로 sys.modules 만 바꿔 두면
    진짜 Whisper 를 내려받지 않고도 '어느 길로 갔는지'를 볼 수 있다.
    """
    호출기록: dict = {}

    base = _가짜모델()
    fake_tf = types.ModuleType("transformers")
    fake_tf.WhisperForConditionalGeneration = types.SimpleNamespace(
        from_pretrained=lambda name: base)
    fake_tf.WhisperProcessor = types.SimpleNamespace(
        from_pretrained=lambda name, **kw: "processor")

    def 새판(model, config):
        호출기록["new_lora"] = config
        return _가짜모델()

    def 얹기(model, path, **kw):
        호출기록["loaded"] = (path, kw)
        return _가짜모델()

    fake_peft = types.ModuleType("peft")
    fake_peft.LoraConfig = lambda **kw: kw            # 설정을 그대로 받아 적는다
    fake_peft.get_peft_model = 새판
    fake_peft.PeftModel = types.SimpleNamespace(from_pretrained=얹기)

    monkeypatch.setitem(sys.modules, "transformers", fake_tf)
    monkeypatch.setitem(sys.modules, "peft", fake_peft)
    return 호출기록


def test_init_adapter_가_없으면_예전처럼_새_판을_덧댄다(가짜기계):
    """기존 동작 불변 확인 — 빈 LoRA 판을 새로 만들고, 어댑터는 얹지 않는다."""
    train_lora.build_model("openai/whisper-small", lora_r=16, init_adapter=None)

    assert "loaded" not in 가짜기계              # 어댑터를 얹지 않았다
    config = 가짜기계["new_lora"]
    assert config["r"] == 16
    assert config["lora_alpha"] == 32            # 관행대로 r 의 2배
    assert config["target_modules"] == LORA_TARGETS


def test_init_adapter_를_주면_그_판을_계속_배울_수_있게_얹는다(가짜기계, tmp_path, capsys):
    """2단 마무리의 핵심 — is_trainable=True 가 빠지면 학습이 헛돈다."""
    adapter = tmp_path / "v2"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(
        json.dumps({"r": 16, "target_modules": ["q_proj", "v_proj"]}), encoding="utf-8")

    train_lora.build_model("openai/whisper-small", lora_r=16, init_adapter=str(adapter))

    assert "new_lora" not in 가짜기계             # 새 판을 만들지 않았다
    경로, 옵션 = 가짜기계["loaded"]
    assert Path(경로) == adapter
    assert 옵션["is_trainable"] is True
    # 설정이 같으면 경고는 뜨지 않는다
    assert "경고" not in capsys.readouterr().out


def test_어댑터_설정이_다르면_어댑터를_따르고_경고한다(가짜기계, tmp_path, capsys):
    """--lora-r 을 잘못 줘도 어댑터에 박힌 값이 이긴다. 대신 한 줄 알린다."""
    adapter = tmp_path / "v2"
    adapter.mkdir()
    (adapter / "adapter_config.json").write_text(
        json.dumps({"r": 16, "target_modules": ["q_proj", "k_proj"]}), encoding="utf-8")

    train_lora.build_model("openai/whisper-small", lora_r=8, init_adapter=str(adapter))

    out = capsys.readouterr().out
    assert "r=16" in out and "--lora-r 8" in out   # 판 크기가 다르다는 경고
    assert "덧댄 자리" in out                       # 덧댄 자리가 다르다는 경고


def test_없는_어댑터_폴더는_새_판으로_넘어가지_않고_멈춘다(가짜기계, tmp_path):
    """v2 위에 얹은 줄 알았는데 맨바닥부터 배운 결과가 나오는 사고를 막는다."""
    with pytest.raises(SystemExit):
        train_lora.build_model("openai/whisper-small", lora_r=16,
                               init_adapter=str(tmp_path / "없는판"))
