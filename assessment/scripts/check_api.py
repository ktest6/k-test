"""FastAPI 앱이 실제로 뜨고 엔드포인트가 동작하는지 확인하는 스크립트.

LLM API 키 없이 돌아간다(키가 없는 상태에서 대체 경로로 도는지까지 확인한다).
서버를 따로 띄우지 않고 TestClient 로 앱을 직접 호출한다.

확인하려는 것:
  1) /health, /features 가 응답하는가
  2) /score 가 종합 점수 + 영역별 점수 + 근거를 담아 돌려주는가
  3) OpenAPI 스키마(자동 생성 문서)에 계약이 제대로 뜨는가

실행: .venv\\Scripts\\python.exe scripts\\check_api.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from src.api import app  # noqa: E402

# 백엔드가 보낼 요청과 똑같은 모양으로 만든다.
REQUEST_BODY = {
    "submission_id": "sub-0001",
    "mode": "speaking",
    "answer_text": (
        "지난주 화요일 오전에 3번 라인 포장 기계가 갑자기 멈췄습니다. "
        "저는 먼저 전원을 차단하고 반장님께 상황을 보고드렸습니다. "
        "반장님이 오셔서 함께 확인해 보니 벨트가 헐거워진 것이 원인이었습니다. "
        "정비팀에 수리를 요청했고, 재발을 막기 위해 매일 점검하는 절차를 새로 만들었습니다."
    ),
    "item": {
        "item_id": "spk-012",
        "prompt": "작업 중 기계가 고장 났던 경험을 말하고, 어떻게 대처했는지 설명하십시오.",
        "item_type": "free_response",
        "expected_register": "formal",
        "checklist": [
            {"id": "c1", "description": "고장이 난 상황을 구체적으로 설명했는가", "weight": 1.0},
            {"id": "c2", "description": "본인이 취한 조치를 말했는가", "weight": 1.0},
            {"id": "c3", "description": "재발 방지 대책을 말했는가", "weight": 1.0},
        ],
        "reference_keywords": ["고장", "조치", "재발"],
    },
    "options": {"use_llm": True, "weights_profile": "provisional_v0"},
}


def main() -> None:
    client = TestClient(app)
    failed = 0

    print("=" * 78)
    print("FastAPI 앱 기동 확인 (LLM 키 없이 실행)")
    print("=" * 78)

    # 1) 서버 상태
    r = client.get("/health")
    print(f"\n[GET /health] status={r.status_code}")
    print(json.dumps(r.json(), ensure_ascii=False, indent=2))
    if r.status_code != 200:
        failed += 1

    # 2) 자질 카탈로그
    r = client.get("/features")
    catalog = r.json()
    print(f"\n[GET /features] status={r.status_code} "
          f"공통 자질 {catalog['common_feature_count']}종 "
          f"(쓰기 전용 포함 전체 {len(catalog['features'])}종)")
    for f in catalog["features"]:
        print(f"    {f['id']:30s} source={f['source']:5s} scope={f['scope']}")
    if catalog["common_feature_count"] != 13:
        print("    !! 공통 자질이 13종이 아니다")
        failed += 1

    # 3) 실제 채점
    r = client.post("/score", json=REQUEST_BODY)
    print(f"\n[POST /score] status={r.status_code}")
    if r.status_code != 200:
        print(r.text[:2000])
        failed += 1
        sys.exit(1)

    body = r.json()
    print(f"  종합 점수: {body['overall_score']}  등급: {body['overall_grade']}")
    print(f"  meta: llm_used={body['meta']['llm_used']} "
          f"weights_provisional={body['meta']['weights_provisional']} "
          f"dropped_citations={body['meta']['dropped_citations']}")
    print("  영역별:")
    for s in body["subscores"]:
        score_text = "채점 안 함" if s["score"] is None else f"{s['score']:.2f}"
        print(f"    - {s['label']:12s} {score_text:>10s}  비중 {s['weight']}  상태 {s['status']}  "
              f"근거 {len(s['evidence'])}건 / 내역 {len(s['contributions'])}건")
    print("  체크리스트 판정:")
    for c in body["checklist_results"]:
        print(f"    - [{c['met']}] {c['description']}  (근거 {len(c['evidence'])}건)")
    print("  근거 예시 (언어 사용 영역):")
    for s in body["subscores"]:
        if s["area"] == "language_use":
            for ev in s["evidence"][:3]:
                print(f"    [{ev['start']}:{ev['end']}] '{ev['quote']}' — {ev['comment'][:60]}")
    print("  경고:")
    for w in body["warnings"][:6]:
        print(f"    - {w[:110]}")

    # 4) OpenAPI 스키마가 계약대로 나오는지
    schema = client.get("/openapi.json").json()
    paths = sorted(schema["paths"].keys())
    response_schema = schema["components"]["schemas"]["ScoreResponse"]["properties"]
    print(f"\n[GET /openapi.json] 엔드포인트: {paths}")
    print(f"  ScoreResponse 필드: {sorted(response_schema.keys())}")

    print("\n" + "-" * 78)
    print("확인 항목")
    print("-" * 78)
    required_fields = {
        "submission_id", "item_id", "mode", "overall_score", "overall_grade",
        "subscores", "features", "checklist_results", "warnings", "meta",
    }
    checks = [
        ("/health, /features, /score, /openapi.json 이 모두 열려 있다",
         {"/health", "/features", "/score"}.issubset(set(paths))),
        ("종합 점수가 나온다", body["overall_score"] is not None),
        ("영역별 서브스코어가 3개 나온다", len(body["subscores"]) == 3),
        ("발화 전달력은 not_evaluated 로 자리만 남는다",
         any(s["area"] == "delivery" and s["status"] == "not_evaluated"
             for s in body["subscores"])),
        ("점수가 나온 모든 영역에 점수 내역이 붙는다",
         all(s["contributions"] for s in body["subscores"] if s["score"] is not None)),
        ("모든 자질이 응답에 실린다(값 없는 것도 상태와 함께)",
         len(body["features"]) == 15),
        ("키가 없으므로 llm_used 가 False 다", body["meta"]["llm_used"] is False),
        ("임시 가중치임이 meta 에 표시된다", body["meta"]["weights_provisional"] is True),
        ("응답 스키마에 계약 필드가 모두 있다",
         required_fields.issubset(set(response_schema.keys()))),
    ]
    for desc, ok in checks:
        print(f"  [{'OK ' if ok else 'NG '}] {desc}")
        if not ok:
            failed += 1

    print()
    if failed:
        print(f"확인 실패 {failed}건.")
        sys.exit(1)
    print("FastAPI 확인 전부 통과.")


if __name__ == "__main__":
    main()
