# 클덱 QA 로그

파이프라인 E2E 점검·개선점 보고 기록. 코드 수정 없음, 보고 전용.
새 점검은 맨 위에 추가.

---

## 2026-08-23 #1 — 전체 E2E 점검 (읽기 전용)

**한 줄**: 테스트 479개 전부 통과, 코드 흐름·스키마 끊긴 곳 없음. 단 `.env`가 LoRA 서버를 가리키는데 그 서버가 꺼져 있어 **말하기 채점은 지금 전부 503** — 그런데 `/health`는 "정상"이라고 보고함.

| # | 항목 | 판정 | 근거 |
|---|---|---|---|
| 1 | pytest | 정상 | 루트 `.venv` 로 `pytest tests -q` → 479 passed / 0 failed (30초, 네트워크 불필요) |
| 2 | api → pipeline → combine → finalize 흐름 | 정상 | `import src.api` OK, 라우트 6개 등록, 시그니처 전부 일치. TestClient `/score`→`/finalize` 200, 400/503 분기 정상 |
| 3 | schema.py ↔ 실제 출력 | 정상 | `ScoringMeta` 24필드 전부 채움/기본값. 스키마 밖 키 내보내는 곳 없음. (사소) `schema.py:41,62` "azure=범위 밖" 주석 구식 |
| 4 | 환경변수 | **이상** | `.env.example`에 `AZURE_SPEECH_KEY / AZURE_SPEECH_REGION / KTEST_STT_PROVIDER / LORA_STT_URL` 4키 누락. `.env.example:8` 기본 모델 주석(3.5-flash) ↔ 실제 `client.py:42`(3.1-flash-lite). `load_dotenv` 는 `auth.py:31`·`client.py:33`에서만 호출 → `speech/` 단독 임포트 시 .env 미적용 |
| 5 | 말하기 STT 분기 | **이상** | 분기(`intake.py:146-158`)·에러 매핑(503/400)은 정상. 문제: provider=lora 인데 8100 미기동 → 말하기 전부 503, 폴백 없음. `/health` `stt_available=True`(`lora_stt.py:88` URL 존재만 검사) → 죽은 서버를 살아있다고 보고. `azure_stt.py:286` `assess_pronunciation` 이 `AudioRequestError` 는 안 삼켜서 전사 성공 후에도 400 튐 |
| 6 | PLAN.md 미완료 항목 실상 | **이상(문서 낡음)** | A-1: 8000 포트 미수신 → 미완 맞음. A-2: HISTORY 8/22 + `backend/.../ai.module.ts:27-28` 실배선 → **사실상 완료인데 PLAN·CLAUDE.md("ai 모듈 stub") 미갱신**. LoRA 스모크: 로컬 GPU 완료, RunPod 배포판 미완(어댑터 tar 없음) |
| 7 | 신뢰성 개선점 | **이상** | (a) `client.py:153-157` 주석: temp 0 인데 같은 답안 3회 오류 4·2·2건 → "재현성 100%" 주장과 충돌. (b) 임시값: delivery 0.20 `combine.py:128`, 발음 정규화 `:89-91`, 등급컷 `:181`, 백분위 `finalize.py:104`(provisional 플래그는 있음). (c) LLM 타임아웃 300초×재시도 → `/score` 최악 ~3분, cloudflared 100초 524 제한 충돌 가능 — **미검증**. (d) `finalize.py:291` "Azure 발음평가 미도입" 문구 틀림(이미 도입). (e) 랜덤·시각 의존 없음, 예외 삼킴은 warnings 남김 — 양호 |

**개선 후보 (우선순위)**
1. `/health`·`stt_available` 이 LoRA `/health` 를 실제로 찔러 보게 — 지금은 죽은 서버를 정상으로 보고해 말하기 503을 못 알아챔 (`lora_stt.py:88`, `api.py:162`)
2. PLAN.md A-1/A-2·LoRA 스모크, CLAUDE.md "ai 모듈 stub" → 8/22 실상으로 갱신
3. `.env.example` 에 Azure/LoRA/STT_PROVIDER 4키 추가 + 기본 모델 주석 수정 — Cloud Run 이전 시 말하기 설정 누락 위험
4. 오류 자질 흔들림(4·2·2건) 을 "재현성 100%" 옆에 정직 표기 + 현 모델 조합으로 재측정 (`client.py:153`)
5. `assess_pronunciation` 에서 `AudioRequestError` 도 None 처리, LoRA→Azure 음성 2회 다운로드 1회로 합치기, `finalize.py:291` 문구 수정

**다음 루프에서 볼 것**: cloudflared 100초 제한 vs `/score` 실제 소요 시간 실측(7-c 미검증), 서버 재기동 후 `/health` 실응답.
