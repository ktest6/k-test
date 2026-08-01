"""API 키 인증 회귀 테스트.

확인하려는 것은 '키를 심는 순간부터 잠긴다'는 한 가지다.

    키가 없으면  -> 지금까지처럼 POST 가 전부 열린다 (개발 모드)
    키가 있으면  -> 헤더가 없거나 틀리면 401

이 두 가지가 함께 지켜져야 한다. 잠기기만 하면 백엔드 연동 테스트가 막히고,
열리기만 하면 인증을 넣은 뜻이 없다.

`GET /health` 와 `/docs` 는 어느 쪽에서도 열려 있어야 한다.
서버가 살아 있는지 확인하는 일까지 막으면 장애가 났을 때 원인을 볼 방법이 사라진다.

실행: .venv\\Scripts\\python.exe -m pytest tests -q
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.auth import API_KEY_ENV, API_KEY_HEADER, auth_enabled

client = TestClient(app)

# 채점 요청 하나. 인증만 보는 테스트라 답안 내용은 중요하지 않다.
SCORE_BODY = {
    "submission_id": "sub-auth-1",
    "mode": "writing",
    "answer_text": "오늘 삼번 라인에서 포장 작업을 하였습니다.",
    "item": {"item_id": "WRT-001", "prompt": "작업일지를 작성하세요."},
    "options": {"use_llm": False},
}


#: 시험용 키. **한글을 쓰지 않는다** — HTTP 헤더 값은 영문·숫자만 담을 수 있어서
#: 한글 키를 넣으면 헤더에 실리지도 못한다(실제로 확인했다).
TEST_KEY = "ktest-secret-key-123"


@pytest.fixture
def locked(monkeypatch):
    """인증이 켜진 서버를 흉내 낸다."""
    monkeypatch.setenv(API_KEY_ENV, TEST_KEY)
    return TEST_KEY


@pytest.fixture
def unlocked(monkeypatch):
    """개발 모드(키 없음)를 흉내 낸다."""
    monkeypatch.delenv(API_KEY_ENV, raising=False)


# ---------------------------------------------------------------------------
# 개발 모드 — 키를 정하지 않았을 때
# ---------------------------------------------------------------------------


def test_키가_없으면_인증이_꺼져_있다(unlocked):
    assert auth_enabled() is False
    body = client.get("/health").json()
    assert body["auth_enabled"] is False


def test_키가_없으면_헤더_없이도_채점이_된다(unlocked):
    """백엔드 연동 테스트가 인증 때문에 막히지 않게 하려는 것이다."""
    response = client.post("/score", json=SCORE_BODY)
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# 잠긴 상태 — 키를 정했을 때
# ---------------------------------------------------------------------------


def test_키를_넣으면_인증이_켜진다(locked):
    assert auth_enabled() is True
    body = client.get("/health").json()
    assert body["auth_enabled"] is True
    # 어떤 헤더를 붙여야 하는지도 함께 알려 준다
    assert body["auth_header"] == API_KEY_HEADER


def test_헤더가_없으면_401_이고_한국어로_이유를_알려준다(locked):
    response = client.post("/score", json=SCORE_BODY)
    assert response.status_code == 401
    assert "헤더가 없습니다" in response.json()["detail"]


def test_키가_틀리면_401(locked):
    response = client.post("/score", json=SCORE_BODY, headers={API_KEY_HEADER: "wrong-key"})
    assert response.status_code == 401
    assert "올바르지 않습니다" in response.json()["detail"]


def test_키가_맞으면_통과한다(locked):
    response = client.post("/score", json=SCORE_BODY, headers={API_KEY_HEADER: locked})
    assert response.status_code == 200


def test_잠겨_있어도_상태_확인과_문서는_열려_있다(locked):
    """장애가 났을 때 서버가 살아 있는지 확인할 방법을 남겨 둔다."""
    assert client.get("/health").status_code == 200
    assert client.get("/features").status_code == 200
    assert client.get("/docs").status_code == 200


def test_모든_POST_엔드포인트가_잠긴다(locked):
    """새 엔드포인트를 만들면서 문지기를 빠뜨리는 일을 막는다."""
    for path in ("/score", "/finalize", "/generate-items", "/verify-items"):
        response = client.post(path, json={})
        assert response.status_code == 401, f"{path} 가 인증 없이 열려 있다"


def test_헤더_이름은_대소문자를_가리지_않는다(locked):
    """HTTP 헤더 이름은 원래 대소문자를 구별하지 않는다. 연동하는 쪽이 헷갈리지 않게 확인해 둔다."""
    response = client.post("/score", json=SCORE_BODY, headers={"x-api-key": locked})
    assert response.status_code == 200
