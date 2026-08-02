"""안전 문서에서 쓰기 문항 초안을 만드는 모듈.

이 패키지는 **문항을 만들기만 하고 점수는 내지 않는다.**
채점은 src/scoring/ 이 하고, 이 패키지는 그쪽 코드를 '쓰기만' 한다.
반대 방향(채점이 생성을 불러다 쓰는 것)은 금지이며 테스트로 막아 두었다.
그래야 문항 생성 기능을 붙였다는 이유로 채점 결과가 달라지는 일이 없다.

여기서 만든 문항은 언제나 status="draft"(초안)다.
사람이 승인해야 시험에 쓸 수 있고, 승인 처리는 백엔드의 몫이다.
"""

from __future__ import annotations

from .generate import GenerationRequestError, generate_items, verify_items
from .schema import (
    GENERATION_VERSION,
    MAX_DOCUMENT_CHARS,
    MIN_DOCUMENT_CHARS,
    DropReason,
    GeneratedItem,
    GeneratedItemType,
    GenerateItemsRequest,
    GenerateItemsResponse,
    VerifyItemsRequest,
    VerifyItemsResponse,
)

__all__ = [
    "GENERATION_VERSION",
    "MAX_DOCUMENT_CHARS",
    "MIN_DOCUMENT_CHARS",
    "DropReason",
    "GeneratedItem",
    "GeneratedItemType",
    "GenerateItemsRequest",
    "GenerateItemsResponse",
    "GenerationRequestError",
    "VerifyItemsRequest",
    "VerifyItemsResponse",
    "generate_items",
    "verify_items",
]
