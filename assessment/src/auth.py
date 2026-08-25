"""API 키로 쓰기 요청(POST)을 잠그는 문지기.

**키를 심는 순간부터 잠기는 구조다.**

    환경변수 KTEST_API_KEY 가 있으면   -> 모든 POST 에 X-API-Key 헤더를 요구한다
    환경변수 KTEST_API_KEY 가 없으면   -> 지금까지처럼 전부 열려 있다 (개발 모드)

왜 이렇게 했는가:
백엔드와의 실호출 연동이 아직 안 끝났다. 지금 인증을 강제하면 연동 테스트가 먼저 막힌다.
그렇다고 인증을 나중에 붙이면 '나중'이 안 온다.
그래서 코드는 지금 넣어 두고, 켜는 시점을 키 하나로 정할 수 있게 했다.
운영 서버에 키를 넣는 순간 잠기고, 개발 PC 에서는 아무것도 바뀌지 않는다.

키는 **영문·숫자로만 만든다.** HTTP 헤더 값에는 한글을 담을 수 없어서
한글이 섞인 키는 헤더에 실리지도 못한다(실제로 확인했다).

`GET /health` 와 `/docs` 는 언제나 열어 둔다.
서버가 살아 있는지 확인하는 일과 연동 문서를 읽는 일까지 막으면
장애가 났을 때 원인을 확인할 방법이 사라진다.
"""

from __future__ import annotations

import os
import secrets

from dotenv import load_dotenv
from fastapi import Header, HTTPException

from .scoring.messages import notice

# .env 에 적어 둔 키도 읽는다. 이미 설정된 환경변수는 덮어쓰지 않는다
load_dotenv(override=False)

#: 요청에 붙여야 하는 헤더 이름.
API_KEY_HEADER = "X-API-Key"

#: 키를 담아 두는 환경변수 이름.
API_KEY_ENV = "KTEST_API_KEY"


def configured_api_key() -> str:
    """지금 설정된 키를 읽는다.

    부를 때마다 환경변수를 다시 읽는다. 서버를 켠 뒤에 키를 넣거나 빼도
    다시 시작하지 않고 반영되고, 테스트가 켜짐·꺼짐을 둘 다 확인할 수 있다.
    """
    return (os.getenv(API_KEY_ENV) or "").strip()


def auth_enabled() -> bool:
    """인증이 켜져 있는지. 키가 비어 있으면 개발 모드(전부 열림)다."""
    return bool(configured_api_key())


def require_api_key(x_api_key: str | None = Header(default=None, alias=API_KEY_HEADER)) -> None:
    """POST 엔드포인트 앞에 세우는 문지기.

    키가 설정돼 있지 않으면 아무것도 하지 않고 통과시킨다(개발 모드).
    """
    expected = configured_api_key()
    # 개발 모드: 키를 정하지 않았으면 잠그지 않는다
    if not expected:
        return

    # 헤더를 아예 안 보낸 경우와 값이 틀린 경우를 나눠 알려 준다.
    # 연동하는 쪽이 '헤더를 빠뜨렸는지, 키가 틀렸는지'를 바로 알 수 있어야 하기 때문이다.
    #
    # detail 은 글자 하나가 아니라 {code, params, message} 묶음으로 나간다.
    # 응시자 화면에는 영어가 떠야 하는데 우리가 만드는 문장은 한국어라서,
    # 백엔드가 code 로 자기 쪽 영어 문장을 골라 띄울 수 있어야 하기 때문이다
    if x_api_key is None:
        raise HTTPException(
            status_code=401,
            detail=notice("AUTH_API_KEY_MISSING", header=API_KEY_HEADER).model_dump(),
        )

    # 글자를 하나씩 비교하는 시간 차이로 키를 추측당하지 않도록 전용 비교 함수를 쓴다
    if not secrets.compare_digest(x_api_key.strip(), expected):
        raise HTTPException(
            status_code=401,
            detail=notice("AUTH_API_KEY_INVALID", header=API_KEY_HEADER).model_dump(),
        )
