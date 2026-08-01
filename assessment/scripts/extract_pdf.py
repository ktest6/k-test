"""PDF 안전문서에서 글자만 뽑아 텍스트 파일로 저장하는 스크립트.

왜 필요한가 (시연 폴백):
원래 PDF → 텍스트 추출은 파일을 가진 백엔드의 몫이다.
그 기능이 늦어지면 시연이 통째로 막히므로, 관리자가 텍스트를 붙여넣는
경로로도 시연할 수 있게 여기에 최소한의 추출기를 둔다.

여기서 뽑은 글은 다듬지 않은 원문 그대로다.
머리글·쪽번호를 지우는 일은 생성 모듈의 전처리가 한다
(인용을 대조할 기준 글이 곧 우리가 본 글이어야 하기 때문이다).

실행:
    .venv\\Scripts\\python.exe scripts\\extract_pdf.py 문서.pdf
    .venv\\Scripts\\python.exe scripts\\extract_pdf.py 문서.pdf --pages 4-16 --out 문서.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def parse_pages(spec: str, total: int) -> tuple[int, int]:
    """'4-16' 같은 쪽 범위를 (시작, 끝) 숫자로 바꾼다.

    사람이 세는 쪽 번호(1부터)를 받아서, 코드가 세는 번호(0부터)로 바꿔 돌려준다.
    """
    # 범위를 안 적었으면 문서 전체를 뽑는다
    if not spec:
        return 0, total
    if "-" in spec:
        first, last = spec.split("-", 1)
        return max(0, int(first) - 1), min(total, int(last))
    # 한 쪽만 적은 경우
    page = int(spec)
    return max(0, page - 1), min(total, page)


def extract(pdf_path: Path, pages: str = "") -> str:
    """PDF 에서 글자를 뽑아 한 덩어리 글로 만든다."""
    try:
        from pypdf import PdfReader
    except ImportError:  # pragma: no cover
        raise SystemExit("pypdf 가 설치돼 있지 않습니다. pip install pypdf 를 먼저 해 주세요.")

    reader = PdfReader(str(pdf_path))
    first, last = parse_pages(pages, len(reader.pages))

    # 쪽마다 따로 뽑아 빈 줄로 이어 붙인다.
    # 쪽 경계를 남겨 두어야 전처리가 머리글·쪽번호를 줄 단위로 찾아낼 수 있다
    chunks: list[str] = []
    for index in range(first, last):
        text = reader.pages[index].extract_text() or ""
        if text.strip():
            chunks.append(text.strip())
    return "\n\n".join(chunks)


def main() -> None:
    parser = argparse.ArgumentParser(description="PDF 안전문서에서 텍스트를 뽑는다")
    parser.add_argument("pdf", help="읽을 PDF 파일 경로")
    parser.add_argument("--pages", default="", help="뽑을 쪽 범위(예: 4-16). 비우면 전체")
    parser.add_argument("--out", default="", help="저장할 텍스트 파일 경로. 비우면 화면에만 보여 준다")
    args = parser.parse_args()

    pdf_path = Path(args.pdf)
    if not pdf_path.exists():
        raise SystemExit(f"파일을 찾을 수 없습니다: {pdf_path}")

    text = extract(pdf_path, args.pages)
    print(f"뽑아낸 글자 수: {len(text):,}자")

    # 저장할 곳을 적었으면 파일로, 아니면 앞부분만 화면에 보여 준다
    if args.out:
        out_path = Path(args.out)
        out_path.write_text(text, encoding="utf-8")
        print(f"저장: {out_path}")
    else:
        print("-" * 70)
        print(text[:1500])
        if len(text) > 1500:
            print(f"... (앞 1,500자만 보여 줍니다. 전체를 보려면 --out 으로 저장하세요)")


if __name__ == "__main__":
    main()
