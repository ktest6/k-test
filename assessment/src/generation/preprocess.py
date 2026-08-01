"""안전 문서 텍스트를 문항 생성에 쓸 수 있게 다듬는 모듈.

왜 우리가 다듬는가:
인용을 대조할 기준 텍스트가 곧 **우리가 본 텍스트**여야 하기 때문이다.
백엔드가 다듬은 글로 문항을 만들고 우리가 다른 글과 대조하면
"문서에 있는 인용"이라는 말이 성립하지 않는다.

무엇을 다듬는가 (실제 KOSHA PDF 를 뽑아 보고 정한 것):
PDF 에서 뽑은 텍스트는 쪽마다 같은 머리글이 반복되고 쪽번호 줄이 섞여 있다.
그것을 그냥 두면 문서 내용이 아닌 글자가 문항에 섞인다.

여기 있는 규칙은 **전부 결정적**이다. 같은 문서를 두 번 넣으면 언제나 같은 결과가 나온다.
그리고 무엇을 지웠는지 notes 로 사람이 읽을 수 있게 보고한다.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field

#: 잘라낸 자리에 남기는 표시 (U+3013, 게타 기호).
#:
#: 왜 필요한가:
#: 머리글을 지우면 앞뒤 문장이 딱 붙는다. 모델이 그 이음매를 가로질러 인용을 복사하면,
#: 그 구절은 정제 텍스트에는 있지만 **실제 문서에는 없는 문장**이 된다.
#: 이 기호는 인용 대조기(citation.py)가 무시하는 문자 목록에 없으므로 비교할 때도 남는다.
#: 그래서 "인용에 이 기호가 있으면 폐기"라는 한 줄 규칙으로 그 경우를 정확히 잡을 수 있다.
CUT_MARKER = "〓"

#: 쪽마다 반복되는 줄로 볼 최소 등장 횟수와 최대 길이.
#: 길이를 제한하는 이유: 긴 문장이 세 번 나오는 것은 머리글이 아니라 진짜 본문일 수 있다.
REPEATED_LINE_MIN_COUNT = 3
REPEATED_LINE_MAX_CHARS = 40

#: 쪽번호만 있는 줄. '12', '- 12 -', '12 -' 같은 모양을 잡는다.
_PAGE_NUMBER_RE = re.compile(r"^\s*-?\s*\d{1,4}\s*-?\s*$")

#: 줄바꿈 없는 특수 공백들. 눈에는 공백인데 코드에서는 다른 글자라 비교를 어긋나게 한다.
_INVISIBLE_SPACES = (" ", "​", "﻿")


@dataclass
class PreprocessResult:
    """문서를 다듬은 결과."""

    text: str                              # 다듬은 문서 전문. 인용 위치의 기준이 되는 글이다
    notes: list[str] = field(default_factory=list)  # 무엇을 지웠는지 사람이 읽는 목록
    raw_chars: int = 0                     # 받은 그대로의 글자 수
    clean_chars: int = 0                   # 다듬은 뒤 글자 수
    sha256: str = ""                       # 다듬은 글의 해시. 재검증 때 같은 문서인지 확인한다


def sha256_of(text: str) -> str:
    """글 하나의 지문(해시)을 만든다.

    같은 글이면 같은 값이 나오므로, 나중에 재검증 요청이 왔을 때
    "그때 그 문서가 맞는지"를 글자 하나까지 대조하지 않고도 확인할 수 있다.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def preprocess_document(text: str) -> PreprocessResult:
    """안전 문서 텍스트를 정제한다.

    순서대로 여섯 가지를 한다.
      1) 원문에 있던 절단 표시 기호를 공백으로 바꾼다 (우리가 쓸 표시와 헷갈리지 않게)
      2) 줄바꿈과 특수 공백을 보통 글자로 맞춘다
      3) 쪽마다 반복되는 짧은 줄(머리글·바닥글)을 지운다
      4) 쪽번호만 있는 줄을 지운다
      5) 지운 자리에 절단 표시를 남긴다
      6) 지나친 공백과 빈 줄을 줄인다
    """
    raw_chars = len(text)
    notes: list[str] = []

    # 1) 원문이 이미 이 기호를 쓰고 있으면 우리가 남길 '잘라낸 자리 표시'와 구별되지 않는다.
    #    문서 쪽 기호를 공백으로 바꿔 표시의 뜻을 하나로 유지한다
    if CUT_MARKER in text:
        marker_count = text.count(CUT_MARKER)
        text = text.replace(CUT_MARKER, " ")
        notes.append(
            f"원문에 있던 '{CUT_MARKER}' 기호 {marker_count}개를 공백으로 바꿨다"
            "(잘라낸 자리 표시와 헷갈리지 않게)."
        )

    # 2) 운영체제마다 다른 줄바꿈과, 눈에는 공백인데 코드에서는 다른 글자인 문자들을 맞춘다
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for space in _INVISIBLE_SPACES:
        text = text.replace(space, " ")

    lines = text.split("\n")

    # 3) 어떤 줄이 쪽마다 반복되는지 먼저 세어 둔다.
    #    세 번 이상 나오면서 짧은 줄은 내용이 아니라 머리글·바닥글로 본다
    stripped_counts = Counter(line.strip() for line in lines if line.strip())
    repeated_lines = {
        line
        for line, count in stripped_counts.items()
        if count >= REPEATED_LINE_MIN_COUNT and len(line) <= REPEATED_LINE_MAX_CHARS
    }

    # 4~5) 지울 줄을 골라내면서, 지운 자리마다 절단 표시를 남긴다.
    #      그냥 지우면 앞뒤 문장이 붙어 '문서에 없는 문장'이 만들어지기 때문이다
    kept_lines: list[str] = []
    removed_repeated: Counter[str] = Counter()
    removed_page_numbers = 0

    for line in lines:
        stripped = line.strip()
        if stripped and stripped in repeated_lines:
            removed_repeated[stripped] += 1
            kept_lines.append(CUT_MARKER)
            continue
        if _PAGE_NUMBER_RE.match(line):
            removed_page_numbers += 1
            kept_lines.append(CUT_MARKER)
            continue
        kept_lines.append(line)

    text = "\n".join(kept_lines)

    # 지운 내용을 사람이 읽을 수 있게 보고한다.
    # 무엇이 지워졌는지 모르면 "왜 이 구절로 문항이 안 만들어졌지"를 설명할 수 없다
    if removed_repeated:
        samples = ", ".join(f"'{line}'" for line, _ in removed_repeated.most_common(3))
        notes.append(
            f"쪽마다 반복되는 줄 {sum(removed_repeated.values())}개를 지웠다"
            f"(머리글·바닥글로 보임). 예: {samples}"
        )
    if removed_page_numbers:
        notes.append(f"쪽번호만 있는 줄 {removed_page_numbers}개를 지웠다.")

    # 6) 표시가 여러 개 붙어 있으면 하나로 합치고, 지나친 공백과 빈 줄을 줄인다.
    #    표시는 '여기서 뭔가 잘렸다'는 사실만 알리면 되므로 개수는 중요하지 않다
    text = re.sub(rf"(?:[ \t]*\n?[ \t]*{CUT_MARKER}[ \t]*\n?[ \t]*)+", f"\n{CUT_MARKER}\n", text)
    text = re.sub(r"[ \t]{3,}", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()

    return PreprocessResult(
        text=text,
        notes=notes,
        raw_chars=raw_chars,
        clean_chars=len(text),
        sha256=sha256_of(text),
    )
