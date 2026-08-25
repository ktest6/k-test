# K-TEST 채점 API — 사용자 대면 한국어 문구 목록 (영어화 대상)

**목적**: 백엔드가 사용자에게 보여줄 때 영어로 바꿔야 하는, 우리 채점 API가 내보내는 한국어 문구를 API 엔드포인트별로 전수 정리한다. 백엔드는 이 목록을 번역 대상 원본으로 쓴다.

**추출 대상**: (1) HTTP 오류/상태 메시지(400/401/503 등의 `detail`·예외 메시지), (2) 응답 본문 `warnings`·영역 `note` 등 사용자 대면 상태 문구, (3) 체크리스트 채점 근거(comment/설명)의 **코드 고정 템플릿**.

**제외**: **STT 전사(받아쓴 글, `meta.stt_transcript`)는 한국어 그대로 유지하므로 이 목록에서 제외한다.** 전사 원문은 응시자가 실제로 한국어로 말한 내용이라 번역 대상이 아니다. (단, 오류 메시지 안에 전사 앞부분 40자가 변수로 끼는 경우가 하나 있는데, **메시지 틀은 번역 대상이고 그 안의 전사 조각만 한국어 유지**다 — 아래 `too_quiet_message` 참고.)

**표 읽는 법**
- "한국어 문구"는 코드 원문 **그대로**다. 숫자·이름 등 변수가 f-string 으로 끼는 자리는 `{…}` 로 표시했다.
- "변수 포함=예" 는 문장 안에 변수가 끼어 통짜 번역이 안 되는 문구다(백엔드가 틀만 번역하고 변수는 그대로 채워 넣어야 한다).
- 파일 경로는 전부 `c:\해커톤\assessment\src\` 아래다.

---

## 0. 인증 — 모든 POST 엔드포인트 공통 (`/score`, `/finalize`, `/generate-items`, `/verify-items`)

서버에 `KTEST_API_KEY` 가 설정돼 있을 때만 잠긴다. 잠긴 상태에서 헤더가 없거나 틀리면 아래 401 이 나간다. `{API_KEY_HEADER}` 는 상수 `"X-API-Key"` 로 치환된다.

| HTTP | 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|---|
| 401 | X-API-Key 헤더를 아예 안 보냄 | `{API_KEY_HEADER} 헤더가 없습니다. 발급받은 채점 API 키를 헤더에 넣어 주세요.` | auth.py:68 | 예(헤더명) |
| 401 | X-API-Key 값이 틀림 | `{API_KEY_HEADER} 헤더의 값이 올바르지 않습니다.` | auth.py:76 | 예(헤더명) |

---

## 1. POST /score — 문항 하나 채점

### 1-A. HTTP 예외 (요청 자체가 성립 안 함 → 400 / 받아쓰기 실패 → 503)

`/score` 는 두 종류의 예외만 HTTP 오류로 바꾼다: `AudioRequestError`→400, `SttUnavailable`→503 (api.py:401~406). 실제 문구는 아래 speech 모듈들에서 나온다. **아래 STT 관련 문구는 전부 `/score` 응답으로 나간다.**

#### 400 — AudioRequestError (음성 요청이 틀림, 다시 보내도 같은 결과)

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 못 읽는 형식을 format 으로 지정 | `'{audio.format}' 형식은 받아쓸 수 없다(받는 형식: {allowed}).` | speech/audio.py:127 | 예 |
| 형식을 전혀 알 수 없음 | `음성 형식을 알 수 없다. audio.format 에 형식을 적어서 다시 보내야 한다(받는 형식: {allowed}).` | speech/audio.py:143 | 예 |
| 주소가 http/https 가 아님 | `음성 파일 주소는 http 또는 https 여야 한다(서버 안의 파일 경로는 받지 않는다).` | speech/audio.py:189 | 아니오 |
| 파일 주소가 4xx/5xx 응답 | `음성 파일을 받지 못했다(주소가 {response.status_code} 로 응답했다). 파일 주소와 접근 권한을 확인해야 한다.` | speech/audio.py:202 | 예 |
| 서버가 알려준 크기가 한도 초과 | `음성 파일이 {…}MB 로 너무 크다(최대 {…}MB).` | speech/audio.py:210 | 예 |
| 받는 도중 크기 한도 초과 | `음성 파일이 최대 {…}MB 를 넘는다.` | speech/audio.py:221 | 예(숫자) |
| 빈 파일(0바이트) | `음성 파일이 비어 있다(0바이트).` | speech/audio.py:245 | 아니오 |
| 쓰기 답안에 음성을 붙임 | `쓰기 답안에는 음성 파일을 붙일 수 없다. 음성 채점은 mode 를 speaking 으로 보내야 한다.` | speech/intake.py:329 | 아니오 |
| 글과 음성을 함께 보냄 | `answer_text 와 audio 가 함께 왔다. 어느 것을 채점해야 할지 알 수 없다. 음성으로 채점하려면 answer_text 를 비워서 보내야 한다.` | speech/intake.py:337 | 아니오 |

#### 503 — SttUnavailable (음성을 글자로 못 옮김, 대체 경로 없음)

공통(모든 STT 제공자):

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 내려받기 시간 초과 | `음성 파일을 내려받지 못했다(제한 시간 {…}초). 저장소 주소가 살아 있는지 확인해야 한다.` | speech/audio.py:233 | 예 |
| 받아쓴 글이 빈 글(파이프라인 최종 가드) | `음성에서 말을 하나도 옮겨 적지 못했다. 녹음 상태를 확인해야 한다.` | speech/intake.py:349 | 아니오 |
| 무음(소리 없음) | `음성에서 소리를 찾지 못했다(녹음이 무음이다). 마이크가 꺼져 있었거나 녹음이 실패했는지 확인해야 한다. 측정값: {loudness.describe()}` | speech/loudness.py:210 (`silence_message`) | 예 |
| 소리가 너무 작음(지어낸 글 의심) | `받아쓴 글이 나왔지만 녹음의 소리가 사람이 말한 것이라기에는 너무 작아서 채점하지 않는다(받아쓰기가 지어낸 글일 수 있다). 측정값: {loudness.describe()} / 받아쓴 글 앞부분: "{preview}"` | speech/loudness.py:217 (`too_quiet_message`) | 예 |
| (위 두 무음 문구에 끼는 측정값 조립) | `가장 큰 0.1초 구간 {…}, 전체 평균 {…} (0~{…} 눈금, 실측한 사람 발화는 8,500 이상)` | speech/loudness.py:86 (`Loudness.describe`) | 예 |

> **주의(전사 제외 규칙 적용)**: `too_quiet_message` 의 `{preview}` 는 받아쓴 글(STT 전사)의 앞부분 40자다. **메시지 틀은 번역 대상이지만 `{preview}` 안에 들어오는 전사 조각은 한국어 그대로 둔다.**

제공자별(어떤 STT 가 꽂혀 있느냐에 따라 아래 중 하나가 나옴):

| 제공자 | 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|---|
| Gemini | 말/빈 글 없음 | `음성에서 말을 하나도 옮겨 적지 못했다. 녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다.` | speech/gemini_stt.py:186 | 아니오 |
| Gemini | 키 없음 등 클라이언트 준비 실패 | `음성을 글자로 옮길 수 없다. {exc}` | speech/gemini_stt.py:230 | 예(LLM 사유) |
| Gemini | 호출 자체 실패 | `음성을 글자로 옮기지 못했다. {classify_failure(exc)}` | speech/gemini_stt.py:262 | 예(LLM 사유) |
| LoRA | 서버 주소 미설정 | `음성을 글자로 옮길 수 없다. LoRA 받아쓰기 서버 주소({LORA_STT_URL_ENV})가 설정돼 있지 않다.` | speech/lora_stt.py:201 | 예(환경변수명) |
| LoRA | 말/빈 글 없음 | `음성에서 말을 하나도 옮겨 적지 못했다. 녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다.` | speech/lora_stt.py:221 | 아니오 |
| LoRA | 서버 시간 초과 | `음성을 글자로 옮기지 못했다. LoRA 서버가 제한 시간({…}초) 안에 답하지 않았다.` | speech/lora_stt.py:278 | 예 |
| LoRA | 서버에 못 닿음 | `음성을 글자로 옮기지 못했다. LoRA 받아쓰기 서버에 닿지 못했다(주소가 맞는지, 서버가 떠 있는지 확인해야 한다).` | speech/lora_stt.py:284 | 아니오 |
| LoRA | 서버 4xx/5xx | `음성을 글자로 옮기지 못했다. LoRA 서버가 {response.status_code} 로 응답했다.` | speech/lora_stt.py:292 | 예 |
| LoRA | 응답이 JSON 아님 | `LoRA 서버의 응답을 읽지 못했다(JSON 이 아니다).` | speech/lora_stt.py:300 | 아니오 |
| Azure | wav 열기 실패 | `음성 파일을 열지 못했다. wav 파일이 맞는지 확인해야 한다.` | speech/azure_stt.py:139 | 아니오 |
| Azure | 16비트 wav 아님 | `이 음성은 {…}비트 wav 라서 발음 평가로 보낼 수 없다(16비트 wav 로 녹음해야 한다).` | speech/azure_stt.py:147 | 예 |
| Azure | 말/빈 글 없음 | `음성에서 말을 하나도 옮겨 적지 못했다. 녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다.` | speech/azure_stt.py:243 | 아니오 |
| Azure | 열쇠 미설정 | `음성을 글자로 옮길 수 없다. Azure 음성 서비스 열쇠(AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)가 설정돼 있지 않다.` | speech/azure_stt.py:341 | 아니오 |
| Azure | wav 아닌 형식 | `'{fetched.audio_format}' 형식은 Azure 발음 평가로 보낼 수 없다(지금은 wav 만 처리한다).` | speech/azure_stt.py:355 | 예 |
| Azure | SDK 미설치 | `발음 평가에 필요한 Azure 음성 SDK 가 설치돼 있지 않다(pip install azure-cognitiveservices-speech).` | speech/azure_stt.py:430 | 아니오 |
| Azure | 호출 실패 | `음성을 글자로 옮기지 못했다. Azure 음성 서비스 호출이 실패했다.` | speech/azure_stt.py:501 | 아니오 |
| Azure | 인식 시간 초과 | `발음 평가가 제한 시간({…}초) 안에 끝나지 않았다.` | speech/azure_stt.py:514 | 예 |
| Azure | 요청 거절됨 | `음성을 글자로 옮기지 못했다. Azure 음성 서비스가 요청을 거절했다.` | speech/azure_stt.py:518 | 아니오 |

> Azure 문구 중 `assess_pronunciation`(발음만 재는 경로)에서 나온 `SttUnavailable`/`AudioRequestError` 는 삼켜져서 응답에 안 나간다(발음만 못 재고 delivery 만 비움). 위 Azure 문구가 `/score` 오류로 실제로 나가는 것은 **provider=azure 로 받아쓰기까지 Azure 가 하는 경우**다.

#### LLM 실패 사유 문구 (위 Gemini 503 의 `{exc}`·`{classify_failure(exc)}` 에 끼고, 아래 1-B warnings·`/generate-items` 503 에도 공유됨)

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 하루 호출 한도 초과(429) | `LLM 하루 호출 한도를 다 썼다(429). 한도가 풀리거나 결제를 활성화해야 한다.` | llm/client.py:81 | 아니오 |
| 모델 없음(404) | `요청한 LLM 모델을 쓸 수 없다(404). .env 의 GEMINI_MODEL 을 확인해야 한다.` | llm/client.py:83 | 아니오 |
| 접근 거부(403) | `LLM 접근이 거부됐다(403). API 키가 올바른지 확인해야 한다.` | llm/client.py:85 | 아니오 |
| 인증 실패(401) | `LLM 인증에 실패했다(401). API 키를 확인해야 한다.` | llm/client.py:87 | 아니오 |
| 응답 시간 초과 | `LLM 응답이 제한 시간 안에 오지 않았다.` | llm/client.py:89 | 아니오 |
| 서버 일시 오류 | `LLM 서버가 일시적으로 응답하지 않는다.` | llm/client.py:91 | 아니오 |
| 연결 실패 | `LLM 서버에 연결하지 못했다. 네트워크를 확인해야 한다.` | llm/client.py:93 | 아니오 |
| 그 밖의 실패 | `LLM 호출에 실패했다({type(exc).__name__}).` | llm/client.py:110 | 예(예외종류) |
| 키 미설정 | `GEMINI_API_KEY 가 설정되어 있지 않습니다. .env 파일이나 환경변수에 키를 넣어 주세요.` | llm/client.py:209 | 아니오 |
| 답이 잘림(재시도 꺼짐) | `LLM 답이 길이 제한에 걸려 잘렸다(답변 예산이 모자랐다).` | llm/client.py:292 | 아니오 |
| 답이 잘림(재시도해도) | `LLM 답이 길이 제한에 걸려 잘렸다(예산을 늘려 다시 불러도 마찬가지였다).` | llm/client.py:305 | 아니오 |
| 빈 응답 | `LLM이 빈 응답을 보냈다(안전 필터에 걸렸거나 답을 만들지 못했다).` | llm/client.py:313 | 아니오 |
| JSON 해석 실패 | `LLM 응답을 JSON으로 해석하지 못했다.` | llm/client.py:363, 371 | 아니오 |
| 최상위가 객체 아님 | `LLM 응답의 최상위가 JSON 객체가 아니다.` | llm/client.py:377 | 아니오 |

> `/score` 에서는 위 LLM 실패가 **예외로 안 나가고 warnings 로만 남는다**(규칙 자질로 채점 계속). `/generate-items` 에서는 503 으로 나간다.

### 1-B. 응답 본문 상태 문구 (`ScoreResponse.warnings`, 사용자 대면)

`/score` 는 오류를 안 내고 `warnings[]` 로 상태를 알린다. 아래는 그 warnings 에 담기는 코드 문구다.

#### 답안 유효성 가드 (한국어 아님·베낌 등 → 채점 무효 사유)

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 하드 가드 걸림(래핑) | `[채점 무효] {check.reason}` | scoring/pipeline.py:556 | 예 |
| 소프트 가드 걸림(래핑) | `[답안 유효성] {check.reason}` | scoring/pipeline.py:345 | 예 |
| 무효 응답 영역 note(래핑) | `답안 유효성 가드에 걸려 채점하지 않았다: {report.reason}` | scoring/pipeline.py:275 | 예 |
| 가드A 한글비율 | `답안의 한글 비율이 {…}로 기준({…})에 못 미쳐 한국어 답안으로 볼 수 없다. 채점을 무효로 처리했다.` | scoring/validity.py:226 | 예 |
| 가드B 최소길이 | `답안이 {…}어절로 기준({…}어절)보다 짧아 오류 자질을 신뢰할 수 없다. 틀릴 기회 자체가 적어 '오류 0건'이 실력의 근거가 되지 못한다.` | scoring/validity.py:281 | 예 |
| 가드C 지시문겹침 | `답안 글자의 {…}가 지시문과 그대로 겹쳐(기준 {…}) 응시자가 직접 쓴 글로 볼 수 없다. 채점을 무효로 처리했다.` | scoring/validity.py:385 | 예 |
| 가드D 문장성립(하드) | `어미가 붙은 문장이 {…}/{…}뿐이라 낱말을 나열한 글로 보인다. 채점할 문장이 없어 무효로 처리했다.` | scoring/validity.py:473 | 예 |
| 가드D 문장성립(소프트) | `어미가 붙은 문장이 {…}/{…}에 그쳐 온전한 문장으로 보기 어렵다.` | scoring/validity.py:478 | 예 |

#### 신뢰도·결합 상태

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 신뢰도 표시(래핑) | `[신뢰도 {reliability.value}] {reliability_reason}` | scoring/pipeline.py:652 | 예 |
| 대체 경로(핵심어)로 내용 판정 | `LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. 이 점수는 내용 판정의 결과가 아니므로 응시자에게 보여주면 안 된다.` | scoring/pipeline.py:459 | 아니오 |
| 체크리스트 없음 | `문항에 체크리스트가 없어 내용·과제 수행을 판정하지 못했다.` | scoring/pipeline.py:467 | 아니오 |
| 자질 일부 누락 | `{…} 영역을 일부 자질 없이 계산했다.` | scoring/pipeline.py:475 | 예 |
| 자질 하나도 없음 | `점수를 낼 수 있는 자질이 하나도 없다.` | scoring/combine.py:238 | 아니오 |
| 채점 가능한 영역 없음 | `점수를 낼 수 있는 영역이 없어 종합 점수를 내지 못했다.` | scoring/combine.py:574 | 아니오 |
| 영역 부분 계산 | `'{s.label}' 영역이 일부 자질 없이 계산되었다: {s.note}` | scoring/combine.py:580 | 예 |
| 영역 채점 실패 | `'{s.label}' 영역을 채점하지 못했다: {s.note}` | scoring/combine.py:582 | 예 |

#### 전사 보정 / 오류 자질 / STT 안내 (말하기 답안)

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 쓰기에 보정 요청 | `쓰기 답안에는 STT 전사 보정을 적용하지 않는다. 응시자가 직접 입력한 글이므로 보정하면 실제 오류가 지워진다.` | scoring/pipeline.py:192 | 아니오 |
| 보정 적용됨 | `STT 전사 보정을 {…}군데 적용했다. 보정본은 내용·과제 수행에만 쓰이고, 문법·어휘는 전사 원문으로 채점했다.` | scoring/pipeline.py:211 | 예 |
| 오류 자질 예외(방어) | `오류 자질 추출이 예기치 않게 실패했다: {exc}` | scoring/pipeline.py:416 | 예 |
| 체크리스트 예외(방어) | `체크리스트 판정이 예기치 않게 실패했다: {exc}` | scoring/pipeline.py:425 | 예 |
| 보정구간-오류 겹침 | `오류 지적 {…}건이 STT 보정 구간과 겹쳐 신뢰도 낮음으로 표시됐다. 전사 오류를 문법 오류로 잘못 센 것일 수 있으니 감점 근거로 쓸 때 확인이 필요하다.` | scoring/pipeline.py:611 | 예 |
| 받아쓴 글로 채점함 | `음성을 {…}({…})로 받아쓴 글을 채점했다. 받아쓰기가 응시자의 말과 다를 수 있으므로 이의가 있으면 meta.stt_transcript 와 원본 녹음을 함께 확인해야 한다.` | speech/intake.py:78 | 예 |
| 발음 못 잼 | `발음 평가를 하지 못해 발화 전달력(delivery)은 채점하지 않았다(전사는 {…} 로 정상 처리됨).` | speech/intake.py:283 | 예 |
| 발음 따로 채점 | `발화 전달력(delivery)은 {…} 발음평가로 따로 채점했다(받아쓰기는 {…}).` | speech/intake.py:293 | 예 |
| 압축형식 길이 못 잼 | `{audio_format} 형식은 파일에서 길이를 재지 못한다. 녹음 길이가 필요하면 audio.duration_ms 로 알려 줘야 한다.` | speech/audio.py:256 | 예 |
| 낭독형 정답지 사용 | `낭독형 문항이라 제시문을 정답지로 주고 발음을 평가했다. 받아쓴 글이 제시문 쪽으로 맞춰졌을 수 있으므로 문법 채점의 근거로 쓸 때 확인이 필요하다.` | speech/azure_stt.py:390 | 아니오 |
| 억양 점수 없음 | `억양·강세 점수(ProsodyScore)를 받지 못해 발화 전달력에서 억양은 채점하지 않았다.` | speech/azure_stt.py:615 | 아니오 |
| 자유발화 완전성 미사용 | `자유 발화라서 읽을 원문이 없다. 발화 완전성(completeness)은 채점에 쓰지 않았다.` | speech/azure_stt.py:621 | 아니오 |

#### 오류 자질 추출(errors.py) / 전사 보정(transcript.py) / 인용 폐기(citation.py) warnings

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| LLM 껐음(오류 자질) | `LLM 사용이 꺼져 있어 오류 자질(조사·어미·어휘·높임법)을 계산하지 못했다.` | features/errors.py:289 | 아니오 |
| 키 없음(오류 자질) | `GEMINI_API_KEY 가 없어 오류 자질을 계산하지 못했다. 언어 사용 점수는 규칙 자질만으로 계산된 임시 결과다.` | features/errors.py:296 | 아니오 |
| 오류 자질 추출 실패 | `LLM 오류 자질 추출 실패(규칙 자질만으로 진행): {exc}` | features/errors.py:313 | 예 |
| errors 목록 없음 | `LLM 응답에 errors 목록이 없어 오류를 0건으로 처리했다.` | features/errors.py:320 | 아니오 |
| 인용 폐기(래핑) | `인용 폐기: '{quote}' — {reason}` | llm/citation.py:145 | 예 |
| ↳ 폐기 사유1 | `인용이 비어 있음` | llm/citation.py:83 | 아니오 |
| ↳ 폐기 사유2 | `인용이 너무 짧아 근거로 인정하지 않음(최소 {…}자)` | llm/citation.py:97 | 예 |
| ↳ 폐기 사유3 | `답안 원문에서 찾을 수 없는 인용(폐기)` | llm/citation.py:106 | 아니오 |
| 보정 사유 폐기 | `전사 보정 사유 폐기: '{claimed[:40]}' — {check.reason}` | llm/transcript.py:344 | 예 |
| 보정본 없음 | `전사 보정 응답에 corrected_text 가 없어 원문을 그대로 쓴다.` | llm/transcript.py:395 | 아니오 |
| 고칠 곳 없음 | `전사 보정에서 고칠 곳을 찾지 못해 원문을 그대로 쓴다.` | llm/transcript.py:415 | 아니오 |
| 과보정 폐기 | `※ 전사 보정 폐기 ※ 원문의 {…}가 바뀌어 과보정으로 판단했다(허용 한도 {…}). 보정 없이 원문으로 채점한다.` | llm/transcript.py:422 | 예 |
| 원문 비어 있음 | `전사 원문이 비어 있어 보정하지 않았다.` | llm/transcript.py:473 | 아니오 |
| LLM 껐음(보정) | `LLM 사용이 꺼져 있어 STT 전사 보정을 하지 않았다. 내용·과제 수행도 전사 원문 그대로 채점된다.` | llm/transcript.py:478 | 아니오 |
| 키 없음(보정) | `GEMINI_API_KEY 가 없어 STT 전사 보정을 하지 못했다. 내용·과제 수행이 전사 오류의 영향을 그대로 받는다.` | llm/transcript.py:487 | 아니오 |
| 보정 실패 | `STT 전사 보정 실패(원문으로 채점 진행): {exc}` | llm/transcript.py:502 | 예 |

#### 체크리스트 판정(checklist.py) warnings

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| results 목록 없음 | `LLM 응답에 results 목록이 없어 전 항목을 미충족으로 처리했다.` | features/checklist.py:134 | 아니오 |
| 항목 판정 누락 | `체크리스트 '{item.id}' 에 대한 LLM 판정이 없어 0으로 처리했다.` | features/checklist.py:162 | 예 |
| 근거 인용 폐기 | `체크리스트 '{item.id}': 충족 판정의 근거 인용이 원문에 없어 폐기하고 미충족(0)으로 내렸다 — {check.reason}` | features/checklist.py:194 | 예 |
| 임시 대체 판정 안내 | `※ 임시 ※ LLM을 쓸 수 없어 체크리스트를 핵심어 일치로만 판정했다. 이 결과는 내용 판정이 아니라 대체값이며 운영 채점에 쓸 수 없다.` | features/checklist.py:253 | 아니오 |
| 체크리스트 없음 | `문항에 체크리스트가 없어 내용·과제 수행을 판정할 수 없다.` | features/checklist.py:327 | 아니오 |
| LLM 미사용 사유(래핑) | `LLM 미사용 사유: {reason}` | features/checklist.py:336 | 예 |
| ↳ 사유 값 | `옵션에서 LLM 사용을 껐다` / `GEMINI_API_KEY 없음` | features/checklist.py:333 | 아니오 |
| 체크리스트 판정 실패 | `LLM 체크리스트 판정 실패: {exc}` | features/checklist.py:350 | 예 |

### 1-C. 영역 note / delivery 상태 (`ScoreResponse.subscores[].note`, 사용자 대면)

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 발음 평가 없음(delivery) | `발음 평가 결과가 없어 채점하지 않았다(종합 점수에서 제외). 쓰기 답안이거나, 발음을 재지 못하는 받아쓰기로 채점한 경우다.` | scoring/combine.py:471 | 아니오 |
| 체크리스트 임시판정 | `체크리스트가 임시 대체 판정(핵심어 일치)으로 매겨졌다.` | scoring/combine.py:309 | 아니오 |
| 체크리스트 없음(영역) | `체크리스트가 없어 충족률을 반영하지 못했다.` | scoring/combine.py:312 | 아니오 |
| 자질 제외(내용) | `자질 '{fid}' 를 쓸 수 없어 가중치를 다시 나눴다.` | scoring/combine.py:320 | 예 |
| 반말 확인 불가 | `반말 혼입 횟수를 확인할 수 없어 가중치를 다시 나눴다.` | scoring/combine.py:369 | 아니오 |
| 자질 묶음 제외(언어) | `자질 {…}개({…}) 제외 — {reason}` | scoring/combine.py:400 | 예 |
| 자질 제외(발음) | `자질 '{fid}' 를 쓸 수 없어 가중치를 다시 나눴다.` | scoring/combine.py:452 | 예 |

---

## 2. POST /finalize — 시험 전체 최종 등급

`/finalize` 는 HTTP 예외를 던지지 않는다. 모든 상태는 `FinalizeResponse.warnings[]` / `note` 로 나간다.

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 채점 안 끝난 문항 제외 | `채점이 끝나지 않은 문항 {…}개를 빼고 계산했다: {ids}` | scoring/finalize.py:451 | 예 |
| 결과 안 온 문항 제외 | `결과가 넘어오지 않은 문항 {…}개를 빼고 계산했다: {ids}` | scoring/finalize.py:455 | 예 |
| 실패 문항 제외 | `채점에 실패한 문항 {…}개를 빼고 계산했다: {ids}` | scoring/finalize.py:459 | 예 |
| 신뢰도 표시(래핑) | `[신뢰도 {reliability.value}] {reliability_reason}` | scoring/finalize.py:489 | 예 |
| ↳ 신뢰도 사유 | `문항 {…}개({ids})의 채점이 온전하지 않다 — {worst_reason}` | scoring/finalize.py:89 | 예 |
| 문항 부족(등급 미확정) | `채점된 문항이 부족해 최종 등급을 확정하지 않았다 (채점 {…}/{…}문항, 비중 {…}). 기준: 최소 {…}문항 이상이며 비중 {…} 이상. ※ 이 기준값은 임시값이다.` | scoring/finalize.py:507 | 예 |
| 교차검증 신호(래핑) | `교차검증 신호: {cross.note}` | scoring/finalize.py:575 | 예 |
| ↳ 교차검증 걸림 | `말하기 {…} / 쓰기 {…} 로 {…}등급 차이가 난다({…} 쪽이 높음). 사람이 한 번 확인해 볼 것을 권한다. ※ 이것은 검토 권장 신호일 뿐이며 부정행위 판정이 아니다. 기준값 {…}등급은 임시값이다.` | scoring/finalize.py:401 | 예 |
| ↳ 교차검증 정상 | `말하기 {…} / 쓰기 {…}, {…}등급 차이로 기준값({…}등급) 안에 있다.` | scoring/finalize.py:408 | 예 |
| ↳ 교차검증 불가1 | `말하기와 쓰기 중 한쪽이 채점되지 않아 교차검증을 할 수 없었다.` | scoring/finalize.py:380 | 아니오 |
| ↳ 교차검증 불가2 | `등급 표에 없는 값이 들어와 교차검증을 할 수 없었다.` | scoring/finalize.py:393 | 아니오 |
| ↳ 교차검증 불가3(문항부족) | `채점된 문항이 부족해 교차검증을 하지 않았다.` | scoring/finalize.py:532 | 아니오 |
| 영역 note: 발음 미도입 | `Azure 발음평가 미도입으로 이번 범위에서 채점하지 않는다(종합 점수에서 제외).` | scoring/finalize.py:291 | 아니오 |
| 영역 note: 채점 문항 없음 | `이 영역을 채점한 문항이 없어 최종 점수를 내지 못했다.` | scoring/finalize.py:293 | 아니오 |
| 영역 note: 정상 평균 | `문항별 채점 결과를 문항 비중으로 평균했다.` | scoring/finalize.py:321 | 아니오 |
| 영역 note: 부분 결과 | `일부 문항이 자질 누락 상태로 채점되어 최종 점수도 부분 결과다.` | scoring/finalize.py:322 | 아니오 |

> 영역 이름 라벨(`내용 및 과제 수행` / `언어 사용` / `발화 전달력`)은 `finalize.py:47`, `combine.py`, `pipeline.py` 여러 곳에서 `SubScore.label` 로 나간다. 사용자 대면 라벨이므로 번역 대상이다.

---

## 3. POST /generate-items — 안전 문서에서 쓰기 문항 초안 만들기

### 3-A. HTTP 예외

| HTTP | 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|---|
| 400 | 말하기 문항 요청 | `지금은 쓰기 문항만 만든다. 말하기 문항 생성은 아직 없다.` | generation/generate.py:89 | 아니오 |
| 400 | 문서가 너무 짧음 | `문서가 {…}자로 너무 짧아 문항을 만들 수 없다(최소 {…}자).` | generation/generate.py:98 | 예 |
| 400 | 문서가 너무 김 | `문서가 {…}자로 너무 길다(최대 {…}자). 장·절 단위로 나눠서 보내야 한다.` | generation/generate.py:103 | 예 |
| 503 | LLM 사용 불가 | (위 **1-A LLM 실패 사유 문구** 표와 동일. `LLMUnavailable` 이 그대로 503 `detail` 로 나감) | llm/client.py | — |

### 3-B. 응답 본문 상태 문구 (`GenerateItemsResponse.warnings[]`)

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 문서에 없는 핵심어 제거 | `[{final_id}] 문서에 없는 핵심어 {…} 를 뺐다(LLM 을 못 쓸 때의 대체 채점이 엉뚱하게 돌지 않게 하려는 것).` | generation/generate.py:191 | 예 |
| 모델이 0개 생성 | `모델이 문항을 하나도 만들지 않았다. 문서 내용을 확인하고 다시 시도해야 한다.` | generation/generate.py:216 | 아니오 |
| 전부 폐기됨 | `만들어진 문항 {…}개가 모두 검증 관문에서 폐기됐다. 근거를 댈 수 없는 문항은 내보내지 않는다. 문서를 바꿔 다시 시도해야 한다.` | generation/generate.py:219 | 예 |
| 요청보다 적게 통과 | `요청한 {…}개 중 {…}개만 관문을 통과했다. 더 필요하면 문항 수를 늘려 다시 요청해야 한다.` | generation/generate.py:223 | 예 |
| 유형 편중 | `'{item_type}' 유형 문항이 {…}개로 몰려 있다. 시험이 한 가지 상황만 묻게 되지 않는지 확인해야 한다.` | generation/generate.py:231 | 예 |
| 암기 문제 의심(검증) | `[{provisional_item_id}] 지시문에 '{marker}' 가 있어 암기 문제로 보일 수 있다. 승인 전에 사람이 확인해야 한다.` | generation/validate.py:461 | 예 |
| 문항 중복(조립) | `앞 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이다.` | generation/generate.py:165 | 아니오 |

### 3-C. 폐기 사유 상세 (`GenerateItemsResponse.dropped[].detail`, 관리자 대면)

폐기된 문항의 `reason` 은 영문 코드(`DropReason` enum: `SCHEMA_INVALID` 등)라 번역 불필요. **`detail` 이 한국어라 번역 대상이다.**

| 관문 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| G1 | `문항이 JSON 객체 모양이 아니다.` | generation/validate.py:162 | 아니오 |
| G1 | `필수 항목 '{key}' 이(가) 비었거나 글자가 아니다.` | generation/validate.py:168 | 예 |
| G1 | `checklist 가 목록이 아니다.` | generation/validate.py:172 | 아니오 |
| G1 | `문항 유형 '{item_type}' 은(는) 쓸 수 있는 유형이 아니다(허용: {…}).` | generation/validate.py:180 | 예 |
| G1 | `말투 '{register}' 는 formal 또는 polite 가 아니다.` | generation/validate.py:188 | 예 |
| G1 | `체크리스트가 {…}개다(허용 {…}~{…}개).` | generation/validate.py:195 | 예 |
| G1 | `체크리스트 {…}번이 객체가 아니다.` | generation/validate.py:199 | 예 |
| G1 | `체크리스트 {…}번에 설명이 없다.` | generation/validate.py:201 | 예 |
| G1 | `체크리스트 {…}번의 weight 가 숫자가 아니다.` | generation/validate.py:204 | 예 |
| G1 | `체크리스트 {…}번의 weight 가 {…} 로 허용 범위({…}~{…})를 벗어났다.` | generation/validate.py:211 | 예 |
| G1 | `지시문이 {…}자다(허용 {…}~{…}자).` | generation/validate.py:220 | 예 |
| G1 | `지시문에 번호 기호 {…} 가 없어 무엇을 써야 하는지 나뉘어 있지 않다.` | generation/validate.py:226 | 예 |
| G1 | `지시문에 띄어쓰기 없이 {…}자가 이어지는 곳이 있다(허용 {…}자). 문서에서 띄어쓰기가 사라진 문구가 그대로 새어 나온 것으로 보인다.` | generation/validate.py:232 | 예 |
| G1 | `지시문에 쓰기를 시키는 말(쓰세요·작성하세요·알리세요 등)이 없다. 글을 쓰게 하는 문항이 아니라 지식을 묻는 문항으로 보인다.` | generation/validate.py:241 | 아니오 |
| G2 | `근거 인용이 비어 있다.` | generation/validate.py:262 | 아니오 |
| G2 | `인용이 문서에서 잘라낸 자리를 가로지른다. 실제 문서에는 이어져 있지 않은 문장이다.` | generation/validate.py:268 | 아니오 |
| G2 | `인용에 이음표 '{marker}' 가 있어 여러 구절을 합친 것으로 보인다.` | generation/validate.py:277 | 예 |
| G2 | `인용이 {…}자로 너무 짧아 근거로 인정하지 않는다(최소 {…}자).` | generation/validate.py:284 | 예 |
| G2 | `인용이 {…}자로 너무 길다(최대 {…}자). 짧은 한 구절만 인용해야 어디를 근거로 삼았는지 사람이 확인할 수 있다.` | generation/validate.py:289 | 예 |
| G2/G3 래핑 | `{label}: {detail}` (label = `문항 근거` 또는 `체크리스트 {id}번 근거`) | generation/validate.py:399 | 예 |
| G3 | `{label}: 문서에서 찾을 수 없는 인용이다(지어낸 근거로 보고 폐기했다).` | generation/validate.py:407 | 예 |
| G4 | `지시문 글자의 {…}가 근거 구절과 그대로 겹친다(기준 {…}). 답이 문제 안에 들어 있다.` | generation/validate.py:340 | 예 |
| G4 | `근거 구절을 그대로 옮겨 쓴 답안이 채점기의 '지시문 베끼기' 가드에 걸린다. 성실한 응시자가 무효 0점을 받을 수 있는 문항이다.` | generation/validate.py:350 | 아니오 |
| G5 | `채점 API 형식으로 바꾸지 못했다({type}).` | generation/validate.py:452 | 예 |

---

## 4. POST /verify-items — 관리자가 고친 문항 재검증

LLM 을 안 부르고 HTTP 예외도 없다. `VerifyItemsResponse.warnings[]` / `results[].failures[].detail` 로 나간다.

| 상황 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 문서 지문 불일치 | `보내온 문서가 문항을 만들 때 쓴 문서와 다르다. 인용 위치가 어긋날 수 있으니 문서를 다시 확인해야 한다.` | generation/generate.py:304 | 아니오 |
| 재검증 중 문항 중복 | `'{twin.item_id}' 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이 됐다.` | generation/generate.py:334 | 예 |
| 그 밖의 폐기 사유 | (**3-C 폐기 사유 상세 표와 동일** — 같은 `validate_item` 관문을 재사용) | generation/validate.py | — |

---

## 5. 체크리스트 채점 근거 문구 (코드 고정 템플릿)

**여기가 팀장이 영어화 대상으로 확정한 "체크리스트 채점 근거 문구"다.** 체크리스트 판정 결과(`ChecklistResult.evidence[].comment`, `.note`)에 붙는 문구 중 **코드가 만드는 고정 템플릿만** 아래에 옮긴다.

> **코드 고정 vs LLM 자유생성 구분**
> - LLM 이 준 `reason`(판정 이유 한 문장)은 **자유 생성**이라 번역 대상이지만 **문구가 정해져 있지 않다**(입력마다 달라짐). 아래 "reason 폴백"은 LLM 이 reason 을 비워 보냈을 때만 쓰는 **코드 고정** 기본값이다.
> - `{check.reason}` 자리에는 인용 검증 사유(citation.py: `인용이 비어 있음` 등, 위 1-B 참고)가 들어간다.

| 자리 | 한국어 문구 | 파일:줄 | 변수 | 종류 |
|---|---|---|---|---|
| comment (판정 누락) | `LLM이 이 항목을 판정하지 않아 미충족으로 처리했다.` | features/checklist.py:157 | 아니오 | 코드 고정 |
| note (판정 누락) | `LLM 응답 누락` | features/checklist.py:159 | 아니오 | 코드 고정 |
| comment (미충족 폴백) | `답안에서 해당 내용을 찾지 못했다.` | features/checklist.py:181 | 아니오 | 코드 고정(reason 폴백) |
| comment (인용 폐기) | `LLM은 충족이라고 했으나 근거 인용이 답안 원문에 없어 폐기했다. ({check.reason})` | features/checklist.py:207 | 예 | 코드 고정 |
| note (인용 폐기) | `근거 인용 폐기로 미충족 처리` | features/checklist.py:214 | 아니오 | 코드 고정 |
| comment (충족 폴백) | `답안에서 해당 내용을 확인했다.` | features/checklist.py:233 | 아니오 | 코드 고정(reason 폴백) |
| comment (임시-충족) | `※ 임시 판정 ※ 핵심어 '{hit_word}' 가 답안에 나타남` | features/checklist.py:281 | 예 | 코드 고정(임시 대체) |
| note (임시 판정) | `※ 임시 ※ 핵심어 일치 기반 대체 판정(LLM 미사용)` | features/checklist.py:293, 310 | 아니오 | 코드 고정(임시 대체) |
| comment (임시-미충족) | `※ 임시 판정 ※ 관련 핵심어가 답안에서 발견되지 않음` | features/checklist.py:307 | 아니오 | 코드 고정(임시 대체) |

**내용·과제 수행 영역 근거로 끌어올릴 때의 래퍼** (체크리스트 근거를 영역 evidence 로 올리는 자리):

| 자리 | 한국어 문구 | 파일:줄 | 변수 | 종류 |
|---|---|---|---|---|
| 영역 evidence comment | `[{mark}] {c.description} — {ev.comment}` (`mark` = `충족`/`미충족`) | scoring/combine.py:302 | 예 | 코드 고정 래퍼(`충족`/`미충족`만 고정, `description`은 문항 데이터, `comment`는 위 템플릿) |
| 최종 등급 영역 근거 래퍼 | `[문항 {item.item_id}] {ev.comment}` | scoring/finalize.py:283 | 예 | 코드 고정 래퍼 |

### 참고: 유효성 가드·전사 보정 근거 comment (코드 고정, 체크리스트는 아님)

체크리스트 근거는 아니지만 **같은 성격의 채점 근거 문구**로 `evidence[].comment` 에 실려 사용자에게 나간다. 번역 대상에 함께 넣을지 백엔드가 판단할 수 있게 여기 별도로 남긴다.

| 자리 | 한국어 문구 | 파일:줄 | 변수 |
|---|---|---|---|
| 가드A 근거 | `한국어가 아닌 글자가 이어지는 구간` | scoring/validity.py:237 | 아니오 |
| 가드A 근거 | `답안 앞부분 (한글 {…}자 / 센 글자 {…}자)` | scoring/validity.py:242 | 예 |
| 가드B 근거 | `답안 전체 {…}어절` | scoring/validity.py:287 | 예 |
| 가드C 근거 | `지시문에 그대로 있는 구간` | scoring/validity.py:393 | 아니오 |
| 가드D 근거 | `어미(서술어)가 없어 문장으로 보기 어려운 조각` | scoring/validity.py:491 | 아니오 |
| 전사 보정 근거(래핑) | `STT 전사 보정: {d.describe()} — {d.reason}` | llm/transcript.py:199 | 예 |
| 저신뢰 오류 래핑 | `[신뢰도 낮음] {ev.comment}` | scoring/pipeline.py:122 | 예 |
| 저신뢰 사유(detail) | `이 구간은 STT 전사 보정이 일어난 자리다. 응시자의 문법 오류가 아니라 전사 오류일 수 있다.` | scoring/pipeline.py:118 | 아니오 |
| 저신뢰 note | `이 중 {…}건은 STT 보정 구간에서 나온 지적이라 신뢰도가 낮다(전사 오류일 가능성).` | scoring/pipeline.py:131 | 예 |
| 보정본 자질 note | `내용·과제 수행 영역에 쓰이는 자질이라 보정본 기준으로 계산했다. 근거의 글자 위치도 보정본 기준이다.` | scoring/pipeline.py:162 | 아니오 |

---

## 6. GET /health · GET /features — 설명·라벨 문구 (참고)

`/health`, `/features` 는 오류가 아니라 API 스키마/상태를 설명하는 응답이다. 응답 안에 한국어 `label`·`note` 가 섞여 있다. 프론트가 이 값을 화면에 그대로 쓰면 번역 대상이 되므로 참고용으로 남긴다(백엔드 판단 필요).

| 자리 | 한국어 문구(발췌) | 파일:줄 |
|---|---|---|
| 영역 라벨 | `내용 및 과제 수행` / `언어 사용` / `발화 전달력` | api.py:235~239 |
| delivery note | `Azure 발음평가로 음성을 채점한 경우에만 점수가 나온다(비중 0.20, 임시값). …` | api.py:244 |
| 유효성 가드 라벨 | `한글 비율` / `최소 길이` / `지시문 겹침` / `문장 성립` | api.py:277~296 |
| answer_validity note | `invalid 이면 overall_score 와 overall_grade 가 null 이고 … 기준값은 전부 임시값이다.` | api.py:302 |
| speech 실패코드 설명 | `요청이 성립하지 않는다(쓰기에 음성 첨부 / 글과 음성이 함께 옴 / 형식·크기 위반)` / `받아쓰지 못했다. 대체 경로가 없다` | api.py:333~334 |
| speech note | `발음(delivery)은 전사 제공자와 별개로, Azure 열쇠가 있으면 채점된다 …` | api.py:336 |
| item_generation | `전처리(머리글·쪽번호 제거) 후 글자 수` / `자르지 않고 400 으로 거절한다` | api.py:352~353 |

> 이 섹션은 문구가 많고 API 메타데이터 성격이라 전수 대신 발췌만 실었다. 필요하면 `api.py:133~361` 을 별도로 뽑아 준다.

---

## 7. 내부용 (사용자 비대면) — 영어화 불필요

아래는 응답에 실리더라도 응시자가 아니라 **운영자/개발자에게 주는 안내**이거나, 아예 응답에 안 나가는 문구다. 팀장 지침에 따라 "내부용"으로 구분한다.

| 종류 | 한국어 문구 | 파일:줄 | 비고 |
|---|---|---|---|
| provisional 경고(채점) | `※ 임시 ※ 결합 가중치와 등급 커트라인은 학습된 값이 아니라 손으로 정한 임시값이다. 절대 등급으로 쓰지 말고 답안 사이 비교에만 쓸 것.` | scoring/combine.py:589 | 운영자 대상. 팀장이 예시로 든 내부용 provisional 경고 |
| provisional 경고(최종) | `※ 임시 ※ 결합 가중치는 학습된 값이 아니고, 등급 커트라인도 전문가가 확정한 앵커 답안에서 나온 값이 아니다. … 확정 등급으로 통보하지 말 것.` | scoring/finalize.py:587 | 운영자 대상 |
| detail(응답 미노출) | `SttUnavailable.detail` / `LLMUnavailable.detail` 에 담기는 서버 원문·스택 | port.py:60, client.py:72 등 | 로그 전용, 응답 본문에 안 실림 |
| 패키지 로드 실패 | `google-genai 패키지를 불러올 수 없습니다: {exc}` | llm/client.py:221 | 배포 오류. 개발/운영 진단용 |
| 스크립트 전용 | `음성 파일을 찾을 수 없다: {file_path}` 등 `load_local_audio` 문구 | speech/audio.py:281, 286, 293 | 확인용 스크립트 전용 경로. `/score` 로는 안 나감 |
| LLM 프롬프트(SYSTEM_INSTRUCTION) | 체크리스트/오류/보정/생성 프롬프트 전문 | checklist.py:30 등 | 모델에게 보내는 지시문. 사용자에게 안 나감 |

> **판단 유보**: combine.py:589, finalize.py:587 의 provisional 경고는 `warnings[]` 에 실려 응답 본문으로는 나간다. 다만 내용이 "확정 등급으로 통보하지 말 것" 같은 **운영 지침**이라 팀장이 예로 든 내부용에 해당한다고 보고 여기 넣었다. 응시자 화면에 노출한다면 번역 대상으로 옮겨야 하니, 백엔드에서 이 두 줄의 노출 여부를 한 번 확인해 주면 좋겠다.

---

## 부록 — 집계

- **오류/상태 메시지: 약 118개**
  - 인증(모든 POST): 2
  - `/score` HTTP 예외(400/503, speech 계열): 30 (400: 10, 503: 20) + 측정값 조립 1
  - LLM 실패 사유(공유, `/score` warnings·`/generate-items` 503): 14
  - `/score` warnings·note(유효성/신뢰도/결합/전사/오류/인용/체크리스트/영역): 51
  - `/finalize`: 16
  - `/generate-items` HTTP+warnings: 10
  - `/generate-items`·`/verify-items` 폐기 사유 detail: 24
  - `/verify-items` 전용: 2
- **체크리스트 채점 근거 문구(코드 고정 템플릿): 11** (checklist 판정 9 + 영역 래퍼 2). 참고로 성격이 같은 가드/보정 근거 comment 11개를 별도 표에 추가.
- **내부용(영어화 불필요): 6종**

### 엔드포인트별 개수 요약
| 엔드포인트 | 오류/상태 문구 수(대략) |
|---|---|
| 공통(인증) | 2 |
| POST /score | 30(HTTP) + 14(LLM 공유) + 51(warnings/note) + 근거 22 |
| POST /finalize | 16 |
| POST /generate-items | 10 + 24(폐기 detail) + LLM 공유 |
| POST /verify-items | 2 + 폐기 detail(3-C 재사용) |
| GET /health·/features | 참고(발췌만) |

- **변수 포함(통짜 번역 불가) 문구**: 위 표에서 "변수=예"로 표시한 것 **약 70개**. 백엔드는 이 문구들은 틀만 번역하고 `{…}` 자리(숫자·이름·환경변수명 등)는 그대로 채워야 한다.
- **STT 전사 제외 확인**: `meta.stt_transcript`(받아쓴 글)는 목록에 넣지 않았다. 단 `too_quiet_message`(loudness.py:217) 하나만 메시지 틀 안에 전사 앞부분 40자를 변수로 물고 있어, **틀은 번역 / `{preview}`는 한국어 유지**로 표시해 두었다.

### 놓쳤을 수 있는 곳 / 불확실한 점 (정직하게)
1. **`/health`·`/features` 의 label·note 는 발췌만** 실었다(api.py:133~361 에 한국어 설명이 더 있다). API 메타데이터라 응시자 대면인지 애매해 전수화하지 않았다 — 프론트가 이 값을 그대로 화면에 쓴다면 별도 전수 추출이 필요하다.
2. **provisional 경고 2개(combine.py:589, finalize.py:587)** 의 내부용/사용자 대면 구분은 팀장 지침 해석에 기댄 것이다(위 7번 주 참고). 노출 여부 확인 요청.
3. `DropReason` enum 값 자체(`SCHEMA_INVALID` 등 영문 코드)는 번역 불필요로 보고 제외했다. `detail`(한국어)만 넣었다.
4. LLM 이 생성하는 `reason`(체크리스트 판정 이유), 문항 데이터의 `checklist.description`·`prompt` 등 **문항 저작 시 사람이 넣는 한국어**는 코드 문구가 아니라 데이터라 이 목록 밖이다(백엔드 DB 문항 데이터 쪽에서 따로 다뤄야 한다).
5. 이 목록은 **코드 정적 분석 기준**이다. 실제로 어떤 문구가 자주 나가는지는 런타임 로그로 한 번 대조하면 더 정확하다.
