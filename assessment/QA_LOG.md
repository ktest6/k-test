# 클덱 QA 로그

파이프라인 E2E 점검·개선점 보고 기록. 코드 수정 없음, 보고 전용.
새 점검은 맨 위에 추가.

---

## 2026-08-30 #3 — 시연 서버(GCP) 실사용 점검: 말하기 6문항 글 경로 13건 + /finalize

**한 줄**: 채점 결과 자체는 말이 되지만(좋은 답 B, 엉뚱한 답 D, 빈 답·영어 답 차단), **VM 코드가 저녁 커밋보다 오래돼** 이미 고친 두 문제가 서버에선 그대로 살아 있고, **Gemini 혼잡으로 1건에 40~140초·1건 타임아웃**이 났다.

| # | 항목 | 판정 | 근거 |
|---|---|---|---|
| 1 | 좋은 답안 6문항 | 정상 | 종합 71.9~78.8 B, 체크리스트 대부분 O, 근거 인용 원문 일치. `/finalize` 6문항 77.13 B, 백분위 73.8 |
| 2 | 나쁜/엉뚱/빈/영어 답안 | 정상 | 짧은 답 43.2 D(내용 7.5), 딴소리 40.4 D(내용 3.75), 빈 답·영어 답은 점수 None + `safe_to_show_candidate=false` |
| 3 | 오류 보존 답안(`안 돼습니다`) | 확인 필요 | 언어사용 53(오류 반영됨). 단 전사 보정이 이 진짜 오류를 'STT 오인'으로 고쳐서 `TRANSCRIPT_LOW_CONFIDENCE_OVERLAP` — 실제 학습자 오류가 "신뢰도 낮음"으로 약해지는 구조 |
| 4 | VM 코드 버전 | **문제** | '빨간 원'→'하얀 원' 잘못 보정(로컬은 고침), 보너스 c9/c10 이 LLM 인용 폐기로 0(로컬은 `requires` 코드 계산). 17:40 tar 이후 커밋 3개 미반영 → 재배포 필요 |
| 5 | 소요 시간 | **문제** | 13건 중 6건 40초 이상, SPK-106 140초, SPK-101 1회 타임아웃(>180초). `LLM_FALLBACK_MODEL_USED`·`TRANSCRIPT_FAILED` 동반 → `gemini-3-flash-preview` 혼잡. 백엔드 대기 한도 확인 필요 |
| 6 | 격식체 vs 구어체 | 확인 필요 | SPK-106 같은 내용을 '~합니다'로 하면 언어사용 76.5, '~해야 돼요'(구어·무구두점)로 하면 84.6. 격식체 쪽은 fallback 모델이 판정 — 모델 차이 때문일 수 있음 |
| 7 | 문구 | 사소 | `/finalize` 발화전달력 안내가 "Azure 발음평가 미도입"(실제는 도입, 글 경로라 없었을 뿐) |

- 못 한 것: **음성 경로**(TTS wav 9개 준비, scratch). 공개 주소가 필요해 cloudflared 터널을 열어야 하는데 이 세션에선 막혀 사용자 확인 필요. AI Hub 학습자 wav 는 외부로 안 내보냄.
- 결과 원본: 세션 scratchpad `out/text_*.json`, `finalize_goods.json`

## 2026-08-24 #2 — 7-c 후속: /score 소요 시간 실측 (cloudflared 100초 제한 대조)

**한 줄**: 보통 답안 4~7초, 길고 오류 많은 답안도 최대 59.7초 — **평상시는 100초 안에 안전**. 단 잘림 재시도(예산 2배 재호출)가 겹치는 드문 경우만 100초를 넘을 수 있는 구조로 남아 있다.

- 측정: TestClient로 실 LLM 호출(`gemini-3.1-flash-lite`), 각 3회
  - 보통 답안(4문장): 7.0 / 3.6 / 4.2초
  - 긴 오류 답안(11문장, 조사·어미·높임법 오류 다수): 59.7 / 55.1 / 18.1초
- 남은 위험: `client.py` 잘림 재시도가 발동하면 첫 호출(~60초) + 2배 예산 재호출(과거 실측 ~115초)로 100초 초과 가능. 발동은 드묾("실제로 부르는 일은 드물다", client.py:167). 이때 cloudflared가 524로 끊어도 **채점 자체는 서버에서 완료**되므로 백엔드가 실패로 오인하는 형태.
- 판단: 코드 수정으로 줄이면 8/7의 "60초 컷 → 정상 답안 사망" 사고를 되풀이할 위험. 구조적 해법은 **A-4 Cloud Run 이전**(요청 타임아웃 자유 설정) — 시연 전 이전 판단 시 이 수치를 근거로 쓸 것.

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
