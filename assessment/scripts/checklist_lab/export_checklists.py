# -*- coding: utf-8 -*-
"""1~4차 실험에서 문항마다 어떤 체크리스트가 뽑혔는지 한 파일로 모은다.

실험마다 파일이 따로 있고 모양도 조금씩 달라서(3·4차는 겹마다 다섯 벌) 나란히 놓고
보기가 불편하다. 그래서 **문항 하나를 기준으로 1~4차를 한자리에 모은** 파일을 만든다.
사람이 눈으로 읽으라고 만드는 것이라, 문항별 성적(QWK)도 같이 붙인다.

읽는 파일: outputs/checklist_lab/checklists{,_v2,_v3,_v4}.json
           outputs/checklist_lab/results_summary{,_v2,_v3,_v4}.json (문항별 QWK)

쓰는 법:
    python export_checklists.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _lab_common import OUT_DIR, enable_utf8_output  # noqa: E402

OUT_PATH = OUT_DIR / "문항_체크리스트_1234차.json"

#: 실험마다 "체크리스트를 어떻게 만들었나"를 한 줄로. 읽는 사람이 파일만 보고 알 수 있게.
HOW = {
    "v1": "문항 지시문만 보고 생성. 항목 최대 5개(팀원 원 프롬프트).",
    "v2": "논문(RLCF) 후보 기반 — 품질이 다른 가상 답안 4개를 지어내고 그것들이 "
          "실패하는 방식으로 항목을 뽑음. 중요도 0~100 + 보편 항목 2개.",
    "v3": "실제 학습 겹 답안 8건(사람 점수 표시)을 보고 생성. 겹마다 따로(5벌). "
          "부정형 금지. 상한 8개.",
    "v4": "v3 와 같되 학습 답안 12건을 보여 주고 **항목 10개**를 요구. "
          "난이도를 섞으라고 명시(어려운 항목 3개 이상).",
}


def load(name: str):
    p = OUT_DIR / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def clean_items(items: list[dict]) -> list[dict]:
    """사람이 읽을 때 필요한 칸만 남긴다(내부 진단용 칸은 뺀다)."""
    keep = ("id", "question", "category", "difficulty", "required", "importance", "universal")
    out = []
    for it in items:
        out.append({k: it[k] for k in keep if k in it})
    return out


def fold_block(entry: dict) -> dict:
    """겹마다 다섯 벌인 3·4차용. 겹 번호 순으로 정렬해 담는다.

    **LLM 이 무엇을 보고 만들었는지**(학습 겹 답안 id 와 그 답안의 사람 점수)를 함께 담는다.
    이게 없으면 "이 항목이 어디서 나왔나"를 나중에 되짚을 수 없다.
    """
    folds = {}
    for fk in sorted(entry.get("folds", {}), key=lambda x: int(x)):
        f = entry["folds"][fk]
        seen = f.get("exemplar_ids") or []
        scores = f.get("exemplar_scores") or []
        folds[f"겹{fk}"] = {
            "항목_수": f.get("n_items", len(f.get("items", []))),
            "생성_모델": f.get("model"),
            "생성_시각": f.get("generated_at"),
            "LLM이_본_학습답안": {
                "개수": f.get("n_train_answers_seen"),
                "답안_id": seen,
                "그_답안들의_사람점수": scores,
            },
            "항목": clean_items(f.get("items", [])),
        }
    counts = [v["항목_수"] for v in folds.values()]
    return {"겹별_항목수": counts,
            "평균_항목수": round(mean(counts), 2) if counts else 0,
            "겹별_체크리스트": folds}


def main() -> int:
    enable_utf8_output()
    c1, c2, c3, c4 = (load("checklists.json"), load("checklists_v2.json"),
                      load("checklists_v3.json"), load("checklists_v4.json"))
    s1, s2, s3, s4 = (load("results_summary.json"), load("results_summary_v2.json"),
                      load("results_summary_v3.json"), load("results_summary_v4.json"))

    q1 = s1.get("per_prompt_qwk", {})
    q3 = s3.get("per_prompt_qwk", {})
    q4 = s4.get("per_prompt_qwk", {})

    문항 = []
    for pkey in sorted(c1 or c3 or c4):
        e1, e2 = c1.get(pkey, {}), c2.get(pkey, {})
        row = {
            "문항_id": pkey,
            "문항_지시문": (e1 or c3.get(pkey, {}) or c4.get(pkey, {})).get("prompt"),
            "이_문항의_답안_수": (e1 or c3.get(pkey, {})).get("n_answers"),
            "문항별_QWK": {
                "1차_A1_LLM직접": round(q1[pkey]["A1"], 3) if pkey in q1 else None,
                "1차_C_체크리스트학습": round(q1[pkey]["C"], 3) if pkey in q1 else None,
                "2차_F_체크리스트학습": round(q3[pkey]["F"], 3) if pkey in q3 else None,
                "3차_J_체크리스트학습": round(q3[pkey]["J"], 3) if pkey in q3 else None,
                "4차_Q_확률학습": round(q4[pkey]["Q"], 3) if pkey in q4 else None,
                "4차_Qbin_OX학습": round(q4[pkey]["Q_bin"], 3) if pkey in q4 else None,
            },
            "1차_체크리스트": {"항목_수": len(e1.get("items", [])),
                          "생성_모델": e1.get("model"),
                          "생성_시각": e1.get("generated_at"),
                          "LLM이_본_것": "문항 지시문만",
                          "항목": clean_items(e1.get("items", []))},
            "2차_체크리스트": {"항목_수": len(e2.get("items", [])),
                          "과제항목_수": e2.get("n_task_items"),
                          "생성_모델": e2.get("model"),
                          "생성_시각": e2.get("generated_at"),
                          # 2차는 LLM 이 '가상 답안'을 먼저 지어내고 그 실패 방식에서 항목을 뽑았다.
                          # 그 중간 산출물(지어낸 답안·실패 방식)까지 남겨야 항목의 출처가 보인다.
                          "LLM이_지어낸_가상답안": e2.get("candidates"),
                          "LLM이_찾은_실패방식": e2.get("failure_modes"),
                          "항목": clean_items(e2.get("items", []))},
            "3차_체크리스트": fold_block(c3.get(pkey, {})),
            "4차_체크리스트": fold_block(c4.get(pkey, {})),
        }
        문항.append(row)

    # LLM 에게 실제로 보낸 지시문. 파일 하나만 봐도 재현할 수 있어야 한다.
    prompts = {}
    for label, mod, names in (
            ("v1", "gen_checklists", ["TEAM_PROMPT"]),
            ("v2", "gen_checklists_v2", ["CANDIDATE_PROMPT", "CHECKLIST_PROMPT"]),
            ("v3", "gen_checklists_v3", ["CHECKLIST_V3_PROMPT"]),
            ("v4", "gen_checklists_v4", ["CHECKLIST_V4_PROMPT"])):
        m = __import__(mod)
        prompts[label] = {name: getattr(m, name, None) for name in names}

    doc = {
        "무엇인가": "K-TEST 체크리스트 채점 실험 1~4차에서 문항마다 뽑힌 체크리스트 전부. "
                "3·4차는 시험지 오염을 막으려고 겹마다 따로 만들어서 문항당 5벌이다.",
        "만든_날": s4.get("run_date") or s3.get("run_date"),
        "문항은_누가_만들었나": "문항(지시문)은 LLM 이 만든 것이 아니다. **AI Hub 한국어 말하기 "
                       "데이터에 원래 들어 있던 실제 시험 문항**이고, 우리는 그중 답안이 "
                       "25건 이상 모인 9종을 골라 썼을 뿐이다. LLM 이 만든 것은 체크리스트뿐이다.",
        "체크리스트는_누가_만들었나": "1~4차 전부 **gemini-3.1-flash-lite** 가 만들었다"
                            "(차수별 생성 모델은 각 체크리스트 안에도 적혀 있다).",
        "판정_모델": {"1~3차": "gemini-3.1-flash-lite",
                  "4차": s4.get("judge_model", "qwen3-30b-a3b-instruct-2507 (OpenRouter)")},
        "차수별_생성_방법": HOW,
        "LLM에게_보낸_지시문": prompts,
        "읽는_법": "문항 하나를 골라 1차→4차 순으로 항목을 비교해 보면 '항목이 어떻게 "
                "달라졌나'가 보인다. 항목이 2개(1차) → 6개(2차) → 3.5개(3차) → 8.9개(4차)로 "
                "움직였고, 정보 천장도 그에 따라 0.689 → 0.797 → 0.750 → 0.816 으로 움직였다.",
        "주의": "4차는 판정 모델이 달라서 4차 QWK 를 1~3차와 직접 비교하면 안 된다.",
        "문항": 문항,
    }

    OUT_PATH.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    total = sum(len(r["1차_체크리스트"]["항목"]) + len(r["2차_체크리스트"]["항목"])
                + sum(f["항목_수"] for f in r["3차_체크리스트"]["겹별_체크리스트"].values())
                + sum(f["항목_수"] for f in r["4차_체크리스트"]["겹별_체크리스트"].values())
                for r in 문항)
    print(f"저장: {OUT_PATH}")
    print(f"문항 {len(문항)}종 · 체크리스트 항목 총 {total}개 · {OUT_PATH.stat().st_size / 1024:.0f}KB")
    for r in 문항:
        print(f"  {r['문항_id']}  1차 {r['1차_체크리스트']['항목_수']}개 · "
              f"2차 {r['2차_체크리스트']['항목_수']}개 · "
              f"3차 {r['3차_체크리스트']['겹별_항목수']} · "
              f"4차 {r['4차_체크리스트']['겹별_항목수']}  | {r['문항_지시문'][:34]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
