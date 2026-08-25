# K-TEST 채점 API — 오류·상태 문구 코드표 (백엔드 전달용)

> **이 문서는 손으로 쓰지 않는다.** `assessment/src/scoring/messages.py` 의 카탈로그에서
> `python scripts/export_message_codes.py` 로 뽑아 만든다. 코드를 고치면 다시 돌려 주세요.

## 한눈에 — 무엇이 바뀌었나

우리 채점 API가 내보내던 문구는 전부 한국어였다. 응시자는 외국인 노동자라서 화면에는
영어가 떠야 하는데, 우리가 영어 문장까지 만들어 보내면 문구 하나 고칠 때마다 채점 서버를
다시 배포해야 한다. 그래서 **문장 대신 '코드'와 '값'을 보낸다.**

```json
{"code": "AUDIO_FILE_TOO_LARGE", "params": {"actualMb": 25.3, "maxMb": 20}}
```

백엔드는 이 `code` 로 자기 쪽 영어 문장을 고르고, `params` 값을 그 문장에 끼워 넣는다.
문구를 바꾸고 싶으면 백엔드만 고치면 되고, 나중에 베트남어·네팔어가 늘어도 우리 코드는
그대로다.

### 바뀐 것 세 가지

| 자리 | 어떻게 바뀌었나 |
|---|---|
| HTTP 오류의 `detail` | 글자 하나가 아니라 `{code, params, message}` **묶음**으로 나간다. 401·400·503 전부 같은 모양이다. **모양이 바뀌는 자리는 여기 하나뿐이다.** |
| 응답 본문 | `warnings` 옆에 `notices` 가 **새로 생겼다**. 같은 내용을 코드로 담은 목록이고, 두 목록의 길이와 차례는 언제나 같다. |
| 근거·상태 문구 | `subscores[].note` 옆에 `notice`, `evidence[].comment` 옆에 `notice`, `checklist_results[].note` 옆에 `notice`, `dropped[].detail` 옆에 `notice` 가 생겼다. |

**지금 쓰고 있는 필드는 하나도 모양이 바뀌지 않았다.** 필드를 지우거나 이름을 바꾼 것도
없다. 위 `detail` 하나만 빼면 전부 '더하기'다.

### ★ 새 연동은 `notices` 만 쓰세요 ★

`warnings` · `note` · `comment` · `detail` 에 담긴 **한국어 문장은 호환용으로 남겨 둔 것**이다.
백엔드가 지금 그것을 쓰고 있어서 갑자기 없애면 화면이 깨지기 때문에, 갈아탈 때까지만
같이 내보낸다. 백엔드가 `notices` / `notice` 로 다 옮기고 나면 **이 한국어 문장들은 없앨
예정**이다. 그러니 **새로 붙이는 화면은 처음부터 `notices` 만 보고 만들어 주세요.**
한국어 문장을 화면에 그대로 쓰는 코드를 새로 만들면, 나중에 그 화면부터 깨진다.

### 백엔드가 알아야 할 규칙 네 가지

**1. `message` 는 우리가 만든 한국어 문장이다.**
백엔드가 아직 영어 문장을 안 만든 코드를 만나면 이 값을 대신 띄우면 된다. 아무것도 안
뜨는 것보다는 한국어라도 뜨는 편이 낫다.

**2. 안쪽에 또 코드가 들어 있는 경우가 있다(중첩).**
`[채점 무효] {reason}` 처럼 겉 문구가 안쪽 사유를 감싸는 자리가 있다. 이럴 때 params 에
`reasonNotice` 같은 이름으로 **안쪽 Notice 가 통째로** 들어간다. 겉과 속을 각각 영어로
바꾼 뒤 이어 붙이면 된다.

```json
{"code": "VALIDITY_INVALID_WRAP",
 "params": {"reason": "답안의 한글 비율이 12%로 …",
            "reasonNotice": {"code": "VALIDITY_HANGUL_RATIO",
                             "params": {"ratio": "12%", "threshold": "50%"},
                             "message": "답안의 한글 비율이 12%로 …"}}}
```

params 이름이 `...Notice` 로 끝나면 전부 이 중첩이다.

**3. 한국어를 그대로 두어야 하는 값이 있다.**
`STT_TOO_QUIET` 의 `preview`, `CITATION_DISCARDED_WRAP` 의 `quote`,
`CHECKLIST_EVIDENCE_WRAP` 의 `description` 처럼 **응시자가 실제로 쓴 글이나 문항 원문**이
들어오는 자리는 번역하지 말고 그대로 끼워 넣어야 한다. 응시자의 말을 영어로 바꿔
보여 주면 "나는 그렇게 말하지 않았다"는 이의를 확인할 길이 사라진다.
표의 params 칸에 `str(한국어 그대로)` 라고 적힌 것이 그 자리다.

**4. LLM 이 그때그때 쓴 문장에는 고정 코드가 없다.**
체크리스트 판정 이유처럼 모델이 직접 쓰는 문장은 문구가 정해져 있지 않다. 그런 자리는
`LLM_FREE_TEXT` 코드에 `text` 값으로 원문이 들어온다. 미리 만들어 둔 영어 문장이 없으니
그대로 보여 주거나 그쪽에서 번역해야 한다.

### 내부용 표시

코드 뒤에 `※내부용` 이 붙은 것은 응시자가 아니라 **운영자에게 주는 안내**다
(예: "이 점수는 임시값이니 확정 등급으로 통보하지 말 것"). 응시자 화면에 띄우지 않는다면
영어 문장을 만들 필요가 없다. 그래도 코드는 붙여 두었는데, 그래야 `warnings` 와
`notices` 의 길이가 어긋나지 않기 때문이다.

### 표 읽는 법

- **code** — 백엔드가 영어 문장을 고를 때 쓰는 열쇠
- **params** — 그 문장에 끼워 넣을 값. `키 (타입) 예: 예시값` 꼴로 적었다
- **한국어 원문** — 지금 `message` 로 나가는 문장. `{키}` 자리에 params 값이 들어간다
- **영어 초안** — 우리가 적어 둔 제안. 백엔드가 고쳐 써도 된다
- **어디서 나오는지** — 응답의 어느 자리에 실리는지


**전체 189개** (그중 내부용 2개는 영어화 대상이 아님)


---

## 공통(모든 POST) — 인증 (2개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `AUTH_API_KEY_MISSING` | `header` (str) 예: "X-API-Key" | {header} 헤더가 없습니다. 발급받은 채점 API 키를 헤더에 넣어 주세요. | The {header} header is missing. Put your scoring API key in this header. | HTTP 401 detail |
| `AUTH_API_KEY_INVALID` | `header` (str) 예: "X-API-Key" | {header} 헤더의 값이 올바르지 않습니다. | The value of the {header} header is not valid. | HTTP 401 detail |

---

## POST /score (116개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `AUDIO_FORMAT_UNSUPPORTED` | `format` (str) 예: "flac"<br>`allowed` (str) 예: "wav, webm, mp3, m4a, ogg" | '{format}' 형식은 받아쓸 수 없다(받는 형식: {allowed}). | Audio format '{format}' cannot be transcribed (accepted: {allowed}). | HTTP 400 detail |
| `AUDIO_FORMAT_UNKNOWN` | `allowed` (str) 예: "wav, webm, mp3, m4a, ogg" | 음성 형식을 알 수 없다. audio.format 에 형식을 적어서 다시 보내야 한다(받는 형식: {allowed}). | The audio format could not be determined. Send it again with audio.format set (accepted: {allowed}). | HTTP 400 detail |
| `AUDIO_URL_SCHEME_INVALID` | (없음) | 음성 파일 주소는 http 또는 https 여야 한다(서버 안의 파일 경로는 받지 않는다). | The audio file URL must use http or https (server-local file paths are not accepted). | HTTP 400 detail |
| `AUDIO_FETCH_HTTP_ERROR` | `statusCode` (int) 예: 403 | 음성 파일을 받지 못했다(주소가 {statusCode} 로 응답했다). 파일 주소와 접근 권한을 확인해야 한다. | The audio file could not be downloaded (the URL answered with {statusCode}). Check the URL and its access permissions. | HTTP 400 detail |
| `AUDIO_FILE_TOO_LARGE` | `actualMb` (float) 예: 25.3<br>`maxMb` (int) 예: 20 | 음성 파일이 {actualMb}MB 로 너무 크다(최대 {maxMb}MB). | The audio file is {actualMb}MB, which is too large (maximum {maxMb}MB). | HTTP 400 detail |
| `AUDIO_FILE_TOO_LARGE_STREAM` | `maxMb` (int) 예: 20 | 음성 파일이 최대 {maxMb}MB 를 넘는다. | The audio file exceeds the maximum of {maxMb}MB. | HTTP 400 detail |
| `AUDIO_FILE_EMPTY` | (없음) | 음성 파일이 비어 있다(0바이트). | The audio file is empty (0 bytes). | HTTP 400 detail |
| `AUDIO_NOT_ALLOWED_FOR_WRITING` | (없음) | 쓰기 답안에는 음성 파일을 붙일 수 없다. 음성 채점은 mode 를 speaking 으로 보내야 한다. | A writing answer cannot carry an audio file. Send mode=speaking to have audio scored. | HTTP 400 detail |
| `AUDIO_TEXT_AND_AUDIO_BOTH` | (없음) | answer_text 와 audio 가 함께 왔다. 어느 것을 채점해야 할지 알 수 없다. 음성으로 채점하려면 answer_text 를 비워서 보내야 한다. | Both answer_text and audio were sent, so it is unclear which one to score. Leave answer_text empty to have the audio scored. | HTTP 400 detail |
| `AUDIO_DOWNLOAD_TIMEOUT` | `timeoutSec` (int(초)) 예: 30 | 음성 파일을 내려받지 못했다(제한 시간 {timeoutSec}초). 저장소 주소가 살아 있는지 확인해야 한다. | The audio file could not be downloaded within {timeoutSec} seconds. Check that the storage URL is reachable. | HTTP 503 detail |
| `STT_EMPTY_TRANSCRIPT_FINAL` | (없음) | 음성에서 말을 하나도 옮겨 적지 못했다. 녹음 상태를 확인해야 한다. | No speech at all could be transcribed from the audio. Check the recording. | HTTP 503 detail |
| `STT_EMPTY_TRANSCRIPT` | `provider` (str) 예: "lora" | 음성에서 말을 하나도 옮겨 적지 못했다. 녹음이 비어 있거나 소리가 너무 작은지 확인해야 한다. | No speech at all could be transcribed from the audio. Check whether the recording is empty or too quiet. | HTTP 503 detail |
| `STT_SILENT_AUDIO` | `loudness` (str) 예: "가장 큰 0.1초 구간 12.0, 전체 평균 3.4 (0~32767 눈금, 실측한 사람 발화는 8,500 이상)"<br>`loudnessNotice` (notice) 예: → AUDIO_LOUDNESS_DESCRIBE | 음성에서 소리를 찾지 못했다(녹음이 무음이다). 마이크가 꺼져 있었거나 녹음이 실패했는지 확인해야 한다. 측정값: {loudness} | No sound was found in the audio (the recording is silent). Check whether the microphone was off or the recording failed. Measurements: {loudness} | HTTP 503 detail |
| `STT_TOO_QUIET` | `loudness` (str) 예: "가장 큰 0.1초 구간 210.5, 전체 평균 40.2 (0~32767 눈금, 실측한 사람 발화는 8,500 이상)"<br>`preview` (str(한국어 그대로)) 예: "안녕하세요 저는 오늘 지각을 했습니다"<br>`loudnessNotice` (notice) 예: → AUDIO_LOUDNESS_DESCRIBE | 받아쓴 글이 나왔지만 녹음의 소리가 사람이 말한 것이라기에는 너무 작아서 채점하지 않는다(받아쓰기가 지어낸 글일 수 있다). 측정값: {loudness} / 받아쓴 글 앞부분: "{preview}" | A transcript was produced, but the recording is too quiet to be human speech, so it is not scored (the transcript may be fabricated). Measurements: {loudness} / Transcript preview: "{preview}" | HTTP 503 detail |
| `AUDIO_LOUDNESS_DESCRIBE` | `peak` (float) 예: 210.5<br>`mean` (float) 예: 40.2<br>`scaleMax` (int) 예: 32767 | 가장 큰 0.1초 구간 {peak}, 전체 평균 {mean} (0~{scaleMax} 눈금, 실측한 사람 발화는 8,500 이상) | Loudest 0.1s window {peak}, overall average {mean} (scale 0-{scaleMax}; measured human speech is above 8,500) | 위 두 무음 문구 안에 끼는 측정값 |
| `STT_CLIENT_UNAVAILABLE` | `provider` (str) 예: "gemini"<br>`reason` (str) 예: "GEMINI_API_KEY 가 설정되어 있지 않습니다. .env 파일이나 환경변수에 키를 넣어 주세요."<br>`reasonNotice` (notice) 예: → LLM_API_KEY_MISSING | 음성을 글자로 옮길 수 없다. {reason} | The audio cannot be transcribed. {reason} | HTTP 503 detail |
| `STT_CALL_FAILED` | `provider` (str) 예: "gemini"<br>`reason` (str) 예: "LLM 하루 호출 한도를 다 썼다(429). 한도가 풀리거나 결제를 활성화해야 한다."<br>`reasonNotice` (notice) 예: → LLM_QUOTA_EXHAUSTED | 음성을 글자로 옮기지 못했다. {reason} | The audio could not be transcribed. {reason} | HTTP 503 detail |
| `STT_LORA_URL_NOT_SET` | `envVar` (str) 예: "LORA_STT_URL" | 음성을 글자로 옮길 수 없다. LoRA 받아쓰기 서버 주소({envVar})가 설정돼 있지 않다. | The audio cannot be transcribed. The LoRA transcription server URL ({envVar}) is not set. | HTTP 503 detail |
| `STT_LORA_TIMEOUT` | `timeoutSec` (int(초)) 예: 120 | 음성을 글자로 옮기지 못했다. LoRA 서버가 제한 시간({timeoutSec}초) 안에 답하지 않았다. | The audio could not be transcribed. The LoRA server did not answer within {timeoutSec} seconds. | HTTP 503 detail |
| `STT_LORA_UNREACHABLE` | (없음) | 음성을 글자로 옮기지 못했다. LoRA 받아쓰기 서버에 닿지 못했다(주소가 맞는지, 서버가 떠 있는지 확인해야 한다). | The audio could not be transcribed. The LoRA transcription server could not be reached (check the URL and whether the server is running). | HTTP 503 detail |
| `STT_LORA_HTTP_ERROR` | `statusCode` (int) 예: 500 | 음성을 글자로 옮기지 못했다. LoRA 서버가 {statusCode} 로 응답했다. | The audio could not be transcribed. The LoRA server answered with {statusCode}. | HTTP 503 detail |
| `STT_LORA_BAD_JSON` | (없음) | LoRA 서버의 응답을 읽지 못했다(JSON 이 아니다). | The LoRA server response could not be read (it is not JSON). | HTTP 503 detail |
| `STT_AZURE_WAV_OPEN_FAILED` | (없음) | 음성 파일을 열지 못했다. wav 파일이 맞는지 확인해야 한다. | The audio file could not be opened. Check that it really is a wav file. | HTTP 503 detail |
| `STT_AZURE_WAV_NOT_16BIT` | `bits` (int) 예: 32 | 이 음성은 {bits}비트 wav 라서 발음 평가로 보낼 수 없다(16비트 wav 로 녹음해야 한다). | This audio is {bits}-bit wav and cannot be sent for pronunciation assessment (record it as 16-bit wav). | HTTP 503 detail |
| `STT_AZURE_KEY_NOT_SET` | (없음) | 음성을 글자로 옮길 수 없다. Azure 음성 서비스 열쇠(AZURE_SPEECH_KEY / AZURE_SPEECH_REGION)가 설정돼 있지 않다. | The audio cannot be transcribed. The Azure Speech credentials (AZURE_SPEECH_KEY / AZURE_SPEECH_REGION) are not set. | HTTP 503 detail |
| `STT_AZURE_FORMAT_NOT_WAV` | `format` (str) 예: "webm" | '{format}' 형식은 Azure 발음 평가로 보낼 수 없다(지금은 wav 만 처리한다). | Format '{format}' cannot be sent to Azure pronunciation assessment (only wav is supported for now). | HTTP 503 detail |
| `STT_AZURE_SDK_MISSING` | (없음) | 발음 평가에 필요한 Azure 음성 SDK 가 설치돼 있지 않다(pip install azure-cognitiveservices-speech). | The Azure Speech SDK required for pronunciation assessment is not installed (pip install azure-cognitiveservices-speech). | HTTP 503 detail |
| `STT_AZURE_CALL_FAILED` | (없음) | 음성을 글자로 옮기지 못했다. Azure 음성 서비스 호출이 실패했다. | The audio could not be transcribed. The call to the Azure Speech service failed. | HTTP 503 detail |
| `STT_AZURE_TIMEOUT` | `timeoutSec` (int(초)) 예: 60 | 발음 평가가 제한 시간({timeoutSec}초) 안에 끝나지 않았다. | Pronunciation assessment did not finish within {timeoutSec} seconds. | HTTP 503 detail |
| `STT_AZURE_REQUEST_CANCELED` | (없음) | 음성을 글자로 옮기지 못했다. Azure 음성 서비스가 요청을 거절했다. | The audio could not be transcribed. The Azure Speech service rejected the request. | HTTP 503 detail |
| `LLM_FREE_TEXT` | `text` (str(LLM 자유 생성, 고정 문구 아님)) 예: "답안에서 지각한 이유를 밝혔다." | {text} | {text} | evidence comment 등 |
| `VALIDITY_INVALID_WRAP` | `reason` (str) 예: "답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …"<br>`reasonNotice` (notice) 예: → VALIDITY_HANGUL_RATIO | [채점 무효] {reason} | [Not scored] {reason} | warnings |
| `VALIDITY_SOFT_WRAP` | `reason` (str) 예: "어미가 붙은 문장이 1/5에 그쳐 온전한 문장으로 보기 어렵다."<br>`reasonNotice` (notice) 예: → VALIDITY_NO_SENTENCE_SOFT | [답안 유효성] {reason} | [Answer validity] {reason} | warnings |
| `VALIDITY_NOT_SCORED_NOTE` | `reason` (str) 예: "답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …"<br>`reasonNotice` (notice) 예: → VALIDITY_HANGUL_RATIO | 답안 유효성 가드에 걸려 채점하지 않았다: {reason} | Not scored because the answer failed a validity guard: {reason} | subscore note |
| `VALIDITY_HANGUL_RATIO` | `ratio` (str) 예: "12%"<br>`threshold` (str) 예: "50%" | 답안의 한글 비율이 {ratio}로 기준({threshold})에 못 미쳐 한국어 답안으로 볼 수 없다. 채점을 무효로 처리했다. | The Korean-script ratio of the answer is {ratio}, below the threshold of {threshold}, so it cannot be treated as a Korean answer. Scoring was voided. | warnings |
| `VALIDITY_TOO_SHORT` | `words` (int) 예: 4<br>`minWords` (int) 예: 10 | 답안이 {words}어절로 기준({minWords}어절)보다 짧아 오류 자질을 신뢰할 수 없다. 틀릴 기회 자체가 적어 '오류 0건'이 실력의 근거가 되지 못한다. | The answer is {words} words long, shorter than the minimum of {minWords}, so the error features cannot be trusted. With so few chances to make a mistake, 'zero errors' is not evidence of ability. | warnings |
| `VALIDITY_PROMPT_OVERLAP` | `ratio` (str) 예: "82%"<br>`threshold` (str) 예: "60%" | 답안 글자의 {ratio}가 지시문과 그대로 겹쳐(기준 {threshold}) 응시자가 직접 쓴 글로 볼 수 없다. 채점을 무효로 처리했다. | {ratio} of the answer's characters are copied verbatim from the prompt (threshold {threshold}), so it cannot be treated as the test taker's own writing. Scoring was voided. | warnings |
| `VALIDITY_NO_SENTENCE_HARD` | `sentences` (int) 예: 0<br>`total` (int) 예: 6 | 어미가 붙은 문장이 {sentences}/{total}뿐이라 낱말을 나열한 글로 보인다. 채점할 문장이 없어 무효로 처리했다. | Only {sentences} of {total} segments carry a sentence ending, so the answer reads as a list of words. There is no sentence to score, so it was voided. | warnings |
| `VALIDITY_NO_SENTENCE_SOFT` | `sentences` (int) 예: 1<br>`total` (int) 예: 5 | 어미가 붙은 문장이 {sentences}/{total}에 그쳐 온전한 문장으로 보기 어렵다. | Only {sentences} of {total} segments carry a sentence ending, so the answer is hard to read as complete sentences. | warnings |
| `RELIABILITY_CONTENT_KEYWORD_FALLBACK` | (없음) | LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. 이 점수는 내용 판정의 결과가 아니므로 응시자에게 보여주면 안 된다. | The LLM was unavailable, so content/task fulfilment was judged by keyword matching only. This score is not the result of a content judgement and must not be shown to the test taker. | warnings |
| `RELIABILITY_NO_CHECKLIST` | (없음) | 문항에 체크리스트가 없어 내용·과제 수행을 판정하지 못했다. | The item has no checklist, so content/task fulfilment could not be judged. | warnings |
| `SUBSCORE_PARTIAL_AREAS` | `areas` (str) 예: "언어 사용" | {areas} 영역을 일부 자질 없이 계산했다. | The {areas} area(s) were computed with some features missing. | warnings |
| `SUBSCORE_NO_FEATURES` | (없음) | 점수를 낼 수 있는 자질이 하나도 없다. | There is not a single feature available to compute a score from. | warnings |
| `SUBSCORE_NO_SCORABLE_AREA` | (없음) | 점수를 낼 수 있는 영역이 없어 종합 점수를 내지 못했다. | No area could be scored, so no overall score was produced. | warnings |
| `SUBSCORE_AREA_PARTIAL` | `label` (str) 예: "언어 사용"<br>`note` (str) 예: "자질 3개(...) 제외 — LLM 사용 불가"<br>`noteNotice` (notice) 예: → SUBSCORE_FEATURES_EXCLUDED_GROUP | '{label}' 영역이 일부 자질 없이 계산되었다: {note} | The '{label}' area was computed with some features missing: {note} | warnings |
| `SUBSCORE_AREA_FAILED` | `label` (str) 예: "발화 전달력"<br>`note` (str) 예: "발음 평가 결과가 없어 채점하지 않았다(종합 점수에서 제외). …"<br>`noteNotice` (notice) 예: → SUBSCORE_DELIVERY_NO_PRONUNCIATION | '{label}' 영역을 채점하지 못했다: {note} | The '{label}' area could not be scored: {note} | warnings |
| `SUBSCORE_NOTE_LIST` | `notes` (str) 예: "체크리스트가 없어 충족률을 반영하지 못했다. / 자질 'response_length' 를 쓸 수 없어 가중치를 다시 나눴다."<br>`items` (list[notice]) 예: [2개] | {notes} | {notes} | subscore note |
| `SUBSCORE_DELIVERY_NO_PRONUNCIATION` | (없음) | 발음 평가 결과가 없어 채점하지 않았다(종합 점수에서 제외). 쓰기 답안이거나, 발음을 재지 못하는 받아쓰기로 채점한 경우다. | No pronunciation assessment result, so this area was not scored (excluded from the overall score). This happens for writing answers, or when transcription was done by a provider that cannot measure pronunciation. | subscore note |
| `SUBSCORE_CHECKLIST_FALLBACK` | (없음) | 체크리스트가 임시 대체 판정(핵심어 일치)으로 매겨졌다. | The checklist was judged by the provisional fallback (keyword matching). | subscore note |
| `SUBSCORE_CHECKLIST_MISSING` | (없음) | 체크리스트가 없어 충족률을 반영하지 못했다. | There is no checklist, so the fulfilment rate could not be reflected. | subscore note |
| `SUBSCORE_FEATURE_EXCLUDED` | `featureId` (str) 예: "pron_accuracy" | 자질 '{featureId}' 를 쓸 수 없어 가중치를 다시 나눴다. | Feature '{featureId}' is unavailable, so the weights were redistributed. | subscore note |
| `SUBSCORE_BANMAL_UNAVAILABLE` | (없음) | 반말 혼입 횟수를 확인할 수 없어 가중치를 다시 나눴다. | The count of casual-speech intrusions could not be determined, so the weights were redistributed. | subscore note |
| `SUBSCORE_FEATURES_EXCLUDED_GROUP` | `count` (int) 예: 4<br>`featureIds` (str) 예: "err_particle, err_ending, err_lexical, err_honorific"<br>`reason` (str) 예: "LLM 사용 불가"<br>`reasonNotice` (notice) 예: → LLM_FREE_TEXT | 자질 {count}개({featureIds}) 제외 — {reason} | {count} feature(s) excluded ({featureIds}) - {reason} | subscore note |
| `TRANSCRIPT_SKIPPED_FOR_WRITING` | (없음) | 쓰기 답안에는 STT 전사 보정을 적용하지 않는다. 응시자가 직접 입력한 글이므로 보정하면 실제 오류가 지워진다. | STT transcript correction is not applied to writing answers. The text was typed by the test taker, so correcting it would erase real errors. | warnings |
| `TRANSCRIPT_APPLIED` | `count` (int) 예: 3 | STT 전사 보정을 {count}군데 적용했다. 보정본은 내용·과제 수행에만 쓰이고, 문법·어휘는 전사 원문으로 채점했다. | STT transcript correction was applied in {count} place(s). The corrected text is used only for content/task fulfilment; grammar and vocabulary were scored on the raw transcript. | warnings |
| `ERRORS_UNEXPECTED_FAILURE` | `reason` (str) 예: "KeyError('errors')" | 오류 자질 추출이 예기치 않게 실패했다: {reason} | Error-feature extraction failed unexpectedly: {reason} | warnings |
| `CHECKLIST_UNEXPECTED_FAILURE` | `reason` (str) 예: "TimeoutError()" | 체크리스트 판정이 예기치 않게 실패했다: {reason} | Checklist judging failed unexpectedly: {reason} | warnings |
| `TRANSCRIPT_LOW_CONFIDENCE_OVERLAP` | `count` (int) 예: 2 | 오류 지적 {count}건이 STT 보정 구간과 겹쳐 신뢰도 낮음으로 표시됐다. 전사 오류를 문법 오류로 잘못 센 것일 수 있으니 감점 근거로 쓸 때 확인이 필요하다. | {count} error finding(s) overlap a corrected region of the transcript and were marked low-confidence. They may be transcription errors miscounted as grammar errors, so check them before using them to deduct points. | warnings |
| `STT_SCORED_FROM_TRANSCRIPT` | `provider` (str) 예: "lora"<br>`model` (str) 예: "whisper-large-v3-ko-lora" | 음성을 {provider}({model})로 받아쓴 글을 채점했다. 받아쓰기가 응시자의 말과 다를 수 있으므로 이의가 있으면 meta.stt_transcript 와 원본 녹음을 함께 확인해야 한다. | The audio was transcribed by {provider} ({model}) and that text was scored. The transcript may differ from what the test taker actually said, so check meta.stt_transcript together with the original recording if it is disputed. | warnings |
| `STT_PRONUNCIATION_UNAVAILABLE` | `provider` (str) 예: "lora" | 발음 평가를 하지 못해 발화 전달력(delivery)은 채점하지 않았다(전사는 {provider} 로 정상 처리됨). | Pronunciation could not be assessed, so delivery was not scored (transcription by {provider} succeeded). | warnings |
| `STT_PRONUNCIATION_SEPARATE` | `pronouncer` (str) 예: "azure"<br>`sttProvider` (str) 예: "lora" | 발화 전달력(delivery)은 {pronouncer} 발음평가로 따로 채점했다(받아쓰기는 {sttProvider}). | Delivery was scored separately by {pronouncer} pronunciation assessment (transcription was done by {sttProvider}). | warnings |
| `AUDIO_DURATION_UNMEASURABLE` | `format` (str) 예: "webm" | {format} 형식은 파일에서 길이를 재지 못한다. 녹음 길이가 필요하면 audio.duration_ms 로 알려 줘야 한다. | The duration of a {format} file cannot be measured from the file itself. If the recording length is needed, send it as audio.duration_ms. | warnings |
| `AZURE_READALOUD_REFERENCE_USED` | (없음) | 낭독형 문항이라 제시문을 정답지로 주고 발음을 평가했다. 받아쓴 글이 제시문 쪽으로 맞춰졌을 수 있으므로 문법 채점의 근거로 쓸 때 확인이 필요하다. | This is a read-aloud item, so the given passage was used as the reference text for pronunciation assessment. The transcript may have been pulled toward that passage, so check it before using it as evidence for grammar scoring. | warnings |
| `AZURE_NO_PROSODY_SCORE` | (없음) | 억양·강세 점수(ProsodyScore)를 받지 못해 발화 전달력에서 억양은 채점하지 않았다. | No ProsodyScore was returned, so intonation was not scored within delivery. | warnings |
| `AZURE_COMPLETENESS_UNUSED` | (없음) | 자유 발화라서 읽을 원문이 없다. 발화 완전성(completeness)은 채점에 쓰지 않았다. | This is free speech, so there is no reference text to read. Completeness was not used in scoring. | warnings |
| `ERRORS_LLM_DISABLED` | (없음) | LLM 사용이 꺼져 있어 오류 자질(조사·어미·어휘·높임법)을 계산하지 못했다. | LLM use is turned off, so the error features (particles, endings, word choice, honorifics) could not be computed. | warnings |
| `ERRORS_API_KEY_MISSING` | (없음) | GEMINI_API_KEY 가 없어 오류 자질을 계산하지 못했다. 언어 사용 점수는 규칙 자질만으로 계산된 임시 결과다. | GEMINI_API_KEY is missing, so the error features could not be computed. The language-use score is a provisional result computed from rule-based features only. | warnings |
| `ERRORS_EXTRACTION_FAILED` | `reason` (str) 예: "LLM 하루 호출 한도를 다 썼다(429). …"<br>`reasonNotice` (notice) 예: → LLM_QUOTA_EXHAUSTED | LLM 오류 자질 추출 실패(규칙 자질만으로 진행): {reason} | LLM error-feature extraction failed (continuing with rule-based features only): {reason} | warnings |
| `ERRORS_NO_ERRORS_LIST` | (없음) | LLM 응답에 errors 목록이 없어 오류를 0건으로 처리했다. | The LLM response has no 'errors' list, so the error count was treated as zero. | warnings |
| `CITATION_DISCARDED_WRAP` | `quote` (str(한국어 그대로)) 예: "저는 늦었습니다"<br>`reason` (str) 예: "답안 원문에서 찾을 수 없는 인용(폐기)"<br>`reasonNotice` (notice) 예: → CITATION_NOT_FOUND | 인용 폐기: '{quote}' — {reason} | Citation discarded: '{quote}' - {reason} | warnings |
| `CITATION_EMPTY` | (없음) | 인용이 비어 있음 | The citation is empty | warnings |
| `CITATION_TOO_SHORT` | `minLength` (int) 예: 2 | 인용이 너무 짧아 근거로 인정하지 않음(최소 {minLength}자) | The citation is too short to count as evidence (minimum {minLength} characters) | warnings |
| `CITATION_ITEM_MALFORMED` | (없음) | 형식이 올바르지 않은 항목 | The item is not in a valid format | warnings |
| `CITATION_FIELD_MISSING` | (없음) | 인용 필드가 없음 | The citation field is missing | warnings |
| `CITATION_NOT_FOUND` | (없음) | 답안 원문에서 찾을 수 없는 인용(폐기) | The citation cannot be found in the original answer (discarded) | warnings |
| `TRANSCRIPT_REASON_DISCARDED` | `claimed` (str(한국어 그대로)) 예: "안녕하십니까"<br>`reason` (str) 예: "답안 원문에서 찾을 수 없는 인용(폐기)"<br>`reasonNotice` (notice) 예: → CITATION_NOT_FOUND | 전사 보정 사유 폐기: '{claimed}' — {reason} | Transcript correction reason discarded: '{claimed}' - {reason} | warnings |
| `TRANSCRIPT_NO_CORRECTED_TEXT` | (없음) | 전사 보정 응답에 corrected_text 가 없어 원문을 그대로 쓴다. | The correction response has no corrected_text, so the raw transcript is used as is. | warnings |
| `TRANSCRIPT_NOTHING_TO_FIX` | (없음) | 전사 보정에서 고칠 곳을 찾지 못해 원문을 그대로 쓴다. | The correction found nothing to fix, so the raw transcript is used as is. | warnings |
| `TRANSCRIPT_OVERCORRECTION_DISCARDED` | `changedRatio` (str) 예: "38%"<br>`maxRatio` (str) 예: "25%" | ※ 전사 보정 폐기 ※ 원문의 {changedRatio}가 바뀌어 과보정으로 판단했다(허용 한도 {maxRatio}). 보정 없이 원문으로 채점한다. | *** Correction discarded *** {changedRatio} of the transcript was changed, which counts as over-correction (limit {maxRatio}). Scoring proceeds on the raw transcript. | warnings |
| `TRANSCRIPT_SOURCE_EMPTY` | (없음) | 전사 원문이 비어 있어 보정하지 않았다. | The raw transcript is empty, so no correction was made. | warnings |
| `TRANSCRIPT_LLM_DISABLED` | (없음) | LLM 사용이 꺼져 있어 STT 전사 보정을 하지 않았다. 내용·과제 수행도 전사 원문 그대로 채점된다. | LLM use is turned off, so no STT transcript correction was made. Content/task fulfilment is also scored on the raw transcript. | warnings |
| `TRANSCRIPT_API_KEY_MISSING` | (없음) | GEMINI_API_KEY 가 없어 STT 전사 보정을 하지 못했다. 내용·과제 수행이 전사 오류의 영향을 그대로 받는다. | GEMINI_API_KEY is missing, so no STT transcript correction could be made. Content/task fulfilment is fully exposed to transcription errors. | warnings |
| `TRANSCRIPT_FAILED` | `reason` (str) 예: "LLM 서버가 일시적으로 응답하지 않는다."<br>`reasonNotice` (notice) 예: → LLM_SERVER_ERROR | STT 전사 보정 실패(원문으로 채점 진행): {reason} | STT transcript correction failed (scoring proceeds on the raw transcript): {reason} | warnings |
| `CHECKLIST_NO_RESULTS_LIST` | (없음) | LLM 응답에 results 목록이 없어 전 항목을 미충족으로 처리했다. | The LLM response has no 'results' list, so every checklist item was treated as unmet. | warnings |
| `CHECKLIST_ITEM_MISSING_VERDICT` | `itemId` (str) 예: "c1" | 체크리스트 '{itemId}' 에 대한 LLM 판정이 없어 0으로 처리했다. | There is no LLM verdict for checklist item '{itemId}', so it was scored 0. | warnings |
| `CHECKLIST_CITATION_DISCARDED` | `itemId` (str) 예: "c2"<br>`reason` (str) 예: "답안 원문에서 찾을 수 없는 인용(폐기)"<br>`reasonNotice` (notice) 예: → CITATION_NOT_FOUND | 체크리스트 '{itemId}': 충족 판정의 근거 인용이 원문에 없어 폐기하고 미충족(0)으로 내렸다 — {reason} | Checklist item '{itemId}': the citation backing the 'met' verdict is not in the original answer, so it was discarded and the item was lowered to unmet (0) - {reason} | warnings |
| `CHECKLIST_FALLBACK_USED` | (없음) | ※ 임시 ※ LLM을 쓸 수 없어 체크리스트를 핵심어 일치로만 판정했다. 이 결과는 내용 판정이 아니라 대체값이며 운영 채점에 쓸 수 없다. | *** Provisional *** The LLM was unavailable, so the checklist was judged by keyword matching only. This is a fallback value, not a content judgement, and must not be used for operational scoring. | warnings |
| `CHECKLIST_NONE` | (없음) | 문항에 체크리스트가 없어 내용·과제 수행을 판정할 수 없다. | The item has no checklist, so content/task fulfilment cannot be judged. | warnings |
| `CHECKLIST_LLM_UNUSED_WRAP` | `reason` (str) 예: "GEMINI_API_KEY 없음"<br>`reasonNotice` (notice) 예: → CHECKLIST_API_KEY_MISSING | LLM 미사용 사유: {reason} | Reason the LLM was not used: {reason} | warnings |
| `CHECKLIST_LLM_DISABLED_OPTION` | (없음) | 옵션에서 LLM 사용을 껐다 | LLM use was turned off in the options | warnings |
| `CHECKLIST_API_KEY_MISSING` | (없음) | GEMINI_API_KEY 없음 | GEMINI_API_KEY is missing | warnings |
| `CHECKLIST_JUDGE_FAILED` | `reason` (str) 예: "LLM 응답을 JSON으로 해석하지 못했다."<br>`reasonNotice` (notice) 예: → LLM_JSON_PARSE_FAILED | LLM 체크리스트 판정 실패: {reason} | LLM checklist judging failed: {reason} | warnings |
| `CHECKLIST_COMMENT_NO_VERDICT` | (없음) | LLM이 이 항목을 판정하지 않아 미충족으로 처리했다. | The LLM did not judge this item, so it was treated as unmet. | evidence comment |
| `CHECKLIST_NOTE_NO_VERDICT` | (없음) | LLM 응답 누락 | LLM response missing | checklist note |
| `CHECKLIST_COMMENT_UNMET_FALLBACK` | (없음) | 답안에서 해당 내용을 찾지 못했다. | This content was not found in the answer. | evidence comment |
| `CHECKLIST_COMMENT_CITATION_DISCARDED` | `reason` (str) 예: "답안 원문에서 찾을 수 없는 인용(폐기)"<br>`reasonNotice` (notice) 예: → CITATION_NOT_FOUND | LLM은 충족이라고 했으나 근거 인용이 답안 원문에 없어 폐기했다. ({reason}) | The LLM judged this met, but the supporting citation is not in the original answer, so it was discarded. ({reason}) | evidence comment |
| `CHECKLIST_NOTE_CITATION_DISCARDED` | (없음) | 근거 인용 폐기로 미충족 처리 | Marked unmet because the supporting citation was discarded | checklist note |
| `CHECKLIST_COMMENT_MET_FALLBACK` | (없음) | 답안에서 해당 내용을 확인했다. | This content was confirmed in the answer. | evidence comment |
| `CHECKLIST_COMMENT_FALLBACK_MET` | `keyword` (str(한국어 그대로)) 예: "지각" | ※ 임시 판정 ※ 핵심어 '{keyword}' 가 답안에 나타남 | *** Provisional verdict *** the keyword '{keyword}' appears in the answer | evidence comment |
| `CHECKLIST_NOTE_FALLBACK` | (없음) | ※ 임시 ※ 핵심어 일치 기반 대체 판정(LLM 미사용) | *** Provisional *** fallback verdict based on keyword matching (LLM not used) | checklist note |
| `CHECKLIST_COMMENT_FALLBACK_UNMET` | (없음) | ※ 임시 판정 ※ 관련 핵심어가 답안에서 발견되지 않음 | *** Provisional verdict *** no related keyword was found in the answer | evidence comment |
| `CHECKLIST_MET` | (없음) | 충족 | Met | evidence comment 안의 마크 |
| `CHECKLIST_UNMET` | (없음) | 미충족 | Unmet | evidence comment 안의 마크 |
| `CHECKLIST_EVIDENCE_WRAP` | `mark` (str) 예: "충족"<br>`markNotice` (notice) 예: → CHECKLIST_MET<br>`description` (str(문항 데이터, 한국어 그대로)) 예: "지각한 이유를 말했는가"<br>`comment` (str) 예: "답안에서 해당 내용을 확인했다."<br>`commentNotice` (notice) 예: → CHECKLIST_COMMENT_MET_FALLBACK | [{mark}] {description} — {comment} | [{mark}] {description} - {comment} | subscore evidence comment |
| `VALIDITY_EVIDENCE_NON_HANGUL_RUN` | (없음) | 한국어가 아닌 글자가 이어지는 구간 | A run of non-Korean characters | evidence comment |
| `VALIDITY_EVIDENCE_HEAD` | `hangul` (int) 예: 12<br>`counted` (int) 예: 100 | 답안 앞부분 (한글 {hangul}자 / 센 글자 {counted}자) | Beginning of the answer ({hangul} Korean characters out of {counted} counted) | evidence comment |
| `VALIDITY_EVIDENCE_WORD_COUNT` | `words` (int) 예: 4 | 답안 전체 {words}어절 | {words} words in the whole answer | evidence comment |
| `VALIDITY_EVIDENCE_PROMPT_COPY` | (없음) | 지시문에 그대로 있는 구간 | A run copied verbatim from the prompt | evidence comment |
| `VALIDITY_EVIDENCE_NO_ENDING` | (없음) | 어미(서술어)가 없어 문장으로 보기 어려운 조각 | A fragment with no predicate ending, hard to read as a sentence | evidence comment |
| `TRANSCRIPT_EVIDENCE_WRAP` | `change` (str(한국어 그대로)) 예: "'안년하세요' → '안녕하세요'"<br>`reason` (str(LLM 자유 생성)) 예: "발음이 비슷한 오전사" | STT 전사 보정: {change} — {reason} | STT transcript correction: {change} - {reason} | evidence comment |
| `TRANSCRIPT_EVIDENCE_NO_REASON` | `change` (str(한국어 그대로)) 예: "'안년하세요' → '안녕하세요'" | STT 전사 보정: {change} | STT transcript correction: {change} | evidence comment |
| `RELIABILITY_LOW_EVIDENCE_WRAP` | `comment` (str) 예: "조사 '을' 자리에 '를' 을 썼다"<br>`commentNotice` (notice) 예: → LLM_FREE_TEXT | [신뢰도 낮음] {comment} | [Low confidence] {comment} | evidence comment |
| `RELIABILITY_LOW_EVIDENCE_DETAIL` | (없음) | 이 구간은 STT 전사 보정이 일어난 자리다. 응시자의 문법 오류가 아니라 전사 오류일 수 있다. | This span is where the STT transcript was corrected. It may be a transcription error rather than a grammar error by the test taker. | evidence detail |
| `RELIABILITY_LOW_NOTE` | `count` (int) 예: 2 | 이 중 {count}건은 STT 보정 구간에서 나온 지적이라 신뢰도가 낮다(전사 오류일 가능성). | {count} of these findings come from a corrected span of the transcript and are therefore low-confidence (they may be transcription errors). | feature note |
| `TRANSCRIPT_CORRECTED_FEATURE_NOTE` | (없음) | 내용·과제 수행 영역에 쓰이는 자질이라 보정본 기준으로 계산했다. 근거의 글자 위치도 보정본 기준이다. | This feature feeds the content/task area, so it was computed on the corrected transcript. The character offsets in the evidence also refer to the corrected transcript. | feature note |
| `SCORE_PROVISIONAL_WEIGHTS` ※내부용 | (없음) | ※ 임시 ※ 결합 가중치와 등급 커트라인은 학습된 값이 아니라 손으로 정한 임시값이다. 절대 등급으로 쓰지 말고 답안 사이 비교에만 쓸 것. | *** Provisional *** The combination weights and grade cutoffs are hand-set values, not learned ones. Do not use them as absolute grades; use them only to compare answers. | warnings |

---

## POST /score · POST /generate-items 공용 — LLM 실패 사유 (14개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `LLM_QUOTA_EXHAUSTED` | (없음) | LLM 하루 호출 한도를 다 썼다(429). 한도가 풀리거나 결제를 활성화해야 한다. | The daily LLM request quota is used up (429). Wait for the quota to reset or enable billing. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_MODEL_NOT_FOUND` | (없음) | 요청한 LLM 모델을 쓸 수 없다(404). .env 의 GEMINI_MODEL 을 확인해야 한다. | The requested LLM model is not available (404). Check GEMINI_MODEL in .env. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_PERMISSION_DENIED` | (없음) | LLM 접근이 거부됐다(403). API 키가 올바른지 확인해야 한다. | Access to the LLM was denied (403). Check that the API key is correct. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_UNAUTHENTICATED` | (없음) | LLM 인증에 실패했다(401). API 키를 확인해야 한다. | LLM authentication failed (401). Check the API key. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_TIMEOUT` | (없음) | LLM 응답이 제한 시간 안에 오지 않았다. | The LLM did not answer within the time limit. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_SERVER_ERROR` | (없음) | LLM 서버가 일시적으로 응답하지 않는다. | The LLM server is temporarily not responding. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_CONNECTION_FAILED` | (없음) | LLM 서버에 연결하지 못했다. 네트워크를 확인해야 한다. | Could not connect to the LLM server. Check the network. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_CALL_FAILED` | `excType` (str) 예: "ValueError" | LLM 호출에 실패했다({excType}). | The LLM call failed ({excType}). | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_API_KEY_MISSING` | (없음) | GEMINI_API_KEY 가 설정되어 있지 않습니다. .env 파일이나 환경변수에 키를 넣어 주세요. | GEMINI_API_KEY is not set. Put the key in the .env file or an environment variable. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_RESPONSE_TRUNCATED` | (없음) | LLM 답이 길이 제한에 걸려 잘렸다(답변 예산이 모자랐다). | The LLM answer was cut off by the length limit (the answer budget was too small). | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_RESPONSE_TRUNCATED_RETRIED` | (없음) | LLM 답이 길이 제한에 걸려 잘렸다(예산을 늘려 다시 불러도 마찬가지였다). | The LLM answer was cut off by the length limit (it was still cut off after retrying with a larger budget). | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_EMPTY_RESPONSE` | (없음) | LLM이 빈 응답을 보냈다(안전 필터에 걸렸거나 답을 만들지 못했다). | The LLM returned an empty response (it was blocked by a safety filter or produced no answer). | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_JSON_PARSE_FAILED` | (없음) | LLM 응답을 JSON으로 해석하지 못했다. | The LLM response could not be parsed as JSON. | HTTP 503 detail / warnings 안에 끼는 사유 |
| `LLM_JSON_NOT_OBJECT` | (없음) | LLM 응답의 최상위가 JSON 객체가 아니다. | The top level of the LLM response is not a JSON object. | HTTP 503 detail / warnings 안에 끼는 사유 |

---

## POST /finalize (18개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `FINALIZE_EVIDENCE_WRAP` | `itemId` (str) 예: "W-001"<br>`comment` (str) 예: "[충족] 지각한 이유를 말했는가 — 답안에서 해당 내용을 확인했다."<br>`commentNotice` (notice) 예: → CHECKLIST_EVIDENCE_WRAP | [문항 {itemId}] {comment} | [Item {itemId}] {comment} | subscore evidence comment |
| `FINALIZE_EXCLUDED_PENDING` | `count` (int) 예: 2<br>`itemIds` (str) 예: "W-003, S-002" | 채점이 끝나지 않은 문항 {count}개를 빼고 계산했다: {itemIds} | {count} item(s) whose scoring has not finished were excluded: {itemIds} | warnings |
| `FINALIZE_EXCLUDED_MISSING` | `count` (int) 예: 1<br>`itemIds` (str) 예: "S-004" | 결과가 넘어오지 않은 문항 {count}개를 빼고 계산했다: {itemIds} | {count} item(s) whose results never arrived were excluded: {itemIds} | warnings |
| `FINALIZE_EXCLUDED_FAILED` | `count` (int) 예: 1<br>`itemIds` (str) 예: "S-001" | 채점에 실패한 문항 {count}개를 빼고 계산했다: {itemIds} | {count} item(s) that failed scoring were excluded: {itemIds} | warnings |
| `FINALIZE_RELIABILITY_REASON` | `count` (int) 예: 2<br>`itemIds` (str) 예: "W-001, W-002"<br>`worstReason` (str) 예: "LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. …" | 문항 {count}개({itemIds})의 채점이 온전하지 않다 — {worstReason} | The scoring of {count} item(s) ({itemIds}) is not intact - {worstReason} | warnings |
| `FINALIZE_RELIABILITY_REASON_PLAIN` | `count` (int) 예: 1<br>`itemIds` (str) 예: "W-003" | 문항 {count}개({itemIds})의 채점이 온전하지 않다 | The scoring of {count} item(s) ({itemIds}) is not intact | warnings |
| `FINALIZE_GRADE_WITHHELD` | `scored` (int) 예: 2<br>`total` (int) 예: 8<br>`weight` (str) 예: "25%"<br>`minItems` (int) 예: 4<br>`minWeight` (str) 예: "50%" | 채점된 문항이 부족해 최종 등급을 확정하지 않았다 (채점 {scored}/{total}문항, 비중 {weight}). 기준: 최소 {minItems}문항 이상이며 비중 {minWeight} 이상. ※ 이 기준값은 임시값이다. | The final grade was withheld because too few items were scored ({scored}/{total} items, weight {weight}). Requirement: at least {minItems} items and weight {minWeight} or more. *** These thresholds are provisional. *** | warnings |
| `FINALIZE_CROSS_CHECK_WRAP` | `note` (str) 예: "말하기 3급 / 쓰기 6급 로 3등급 차이가 난다(쓰기 쪽이 높음). …"<br>`noteNotice` (notice) 예: → FINALIZE_CROSS_CHECK_GAP | 교차검증 신호: {note} | Cross-check signal: {note} | warnings |
| `FINALIZE_CROSS_CHECK_GAP` | `speaking` (str) 예: "3급"<br>`writing` (str) 예: "6급"<br>`gap` (int) 예: 3<br>`higher` (str) 예: "쓰기"<br>`threshold` (int) 예: 2 | 말하기 {speaking} / 쓰기 {writing} 로 {gap}등급 차이가 난다({higher} 쪽이 높음). 사람이 한 번 확인해 볼 것을 권한다. ※ 이것은 검토 권장 신호일 뿐이며 부정행위 판정이 아니다. 기준값 {threshold}등급은 임시값이다. | Speaking {speaking} / writing {writing} - a gap of {gap} grade(s) ({higher} is higher). A human review is recommended. *** This is only a review hint, not a cheating verdict. The threshold of {threshold} grade(s) is provisional. *** | warnings |
| `FINALIZE_CROSS_CHECK_OK` | `speaking` (str) 예: "4급"<br>`writing` (str) 예: "5급"<br>`gap` (int) 예: 1<br>`threshold` (int) 예: 2 | 말하기 {speaking} / 쓰기 {writing}, {gap}등급 차이로 기준값({threshold}등급) 안에 있다. | Speaking {speaking} / writing {writing}, a gap of {gap} grade(s), within the threshold of {threshold} grade(s). | warnings |
| `FINALIZE_CROSS_CHECK_ONE_MODE_MISSING` | (없음) | 말하기와 쓰기 중 한쪽이 채점되지 않아 교차검증을 할 수 없었다. | One of speaking and writing was not scored, so the cross-check could not be done. | warnings |
| `FINALIZE_CROSS_CHECK_UNKNOWN_GRADE` | (없음) | 등급 표에 없는 값이 들어와 교차검증을 할 수 없었다. | A value outside the grade table arrived, so the cross-check could not be done. | warnings |
| `FINALIZE_CROSS_CHECK_TOO_FEW_ITEMS` | (없음) | 채점된 문항이 부족해 교차검증을 하지 않았다. | Too few items were scored, so the cross-check was not done. | warnings |
| `FINALIZE_AREA_DELIVERY_NOT_INTRODUCED` | (없음) | Azure 발음평가 미도입으로 이번 범위에서 채점하지 않는다(종합 점수에서 제외). | Azure pronunciation assessment is not in place yet, so this area is out of scope and not scored (excluded from the overall score). | subscore note |
| `FINALIZE_AREA_NO_ITEMS` | (없음) | 이 영역을 채점한 문항이 없어 최종 점수를 내지 못했다. | No item scored this area, so no final score could be produced. | subscore note |
| `FINALIZE_AREA_WEIGHTED_MEAN` | (없음) | 문항별 채점 결과를 문항 비중으로 평균했다. | The per-item scores were averaged using the item weights. | subscore note |
| `FINALIZE_AREA_PARTIAL` | (없음) | 일부 문항이 자질 누락 상태로 채점되어 최종 점수도 부분 결과다. | Some items were scored with features missing, so the final score is a partial result too. | subscore note |
| `FINALIZE_PROVISIONAL_WEIGHTS` ※내부용 | (없음) | ※ 임시 ※ 결합 가중치는 학습된 값이 아니고, 등급 커트라인도 전문가가 확정한 앵커 답안에서 나온 값이 아니다. 백분위 역시 실제 응시자 분포가 아니라 임시 환산표에서 나온 값이다. 확정 등급으로 통보하지 말 것. | *** Provisional *** The combination weights are not learned, the grade cutoffs do not come from expert-confirmed anchor answers, and the percentile comes from a provisional conversion table rather than a real test-taker distribution. Do not report this as a confirmed grade. | warnings |

---

## POST /score · POST /finalize 공용 (1개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `RELIABILITY_WRAP` | `level` (str) 예: "low"<br>`reason` (str) 예: "LLM을 쓰지 못해 내용·과제 수행을 핵심어 일치로만 판정했다. …"<br>`reasonNotice` (notice) 예: → RELIABILITY_CONTENT_KEYWORD_FALLBACK | [신뢰도 {level}] {reason} | [Reliability: {level}] {reason} | warnings |

---

## POST /generate-items (9개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `GEN_SPEAKING_NOT_SUPPORTED` | (없음) | 지금은 쓰기 문항만 만든다. 말하기 문항 생성은 아직 없다. | Only writing items can be generated for now. Speaking item generation does not exist yet. | HTTP 400 detail |
| `GEN_DOCUMENT_TOO_SHORT` | `chars` (int) 예: 120<br>`minChars` (int) 예: 300 | 문서가 {chars}자로 너무 짧아 문항을 만들 수 없다(최소 {minChars}자). | The document is {chars} characters long, too short to generate items from (minimum {minChars}). | HTTP 400 detail |
| `GEN_DOCUMENT_TOO_LONG` | `chars` (int) 예: 42000<br>`maxChars` (int) 예: 20000 | 문서가 {chars}자로 너무 길다(최대 {maxChars}자). 장·절 단위로 나눠서 보내야 한다. | The document is {chars} characters long, too long (maximum {maxChars}). Split it into chapters or sections and send them separately. | HTTP 400 detail |
| `GEN_KEYWORD_REMOVED` | `itemId` (str) 예: "GEN-W-001"<br>`keywords` (str(한국어 그대로)) 예: "'보호구', '점검표'" | [{itemId}] 문서에 없는 핵심어 {keywords} 를 뺐다(LLM 을 못 쓸 때의 대체 채점이 엉뚱하게 돌지 않게 하려는 것). | [{itemId}] Removed the keyword(s) {keywords} that do not appear in the document (so the fallback scoring used when the LLM is unavailable does not misfire). | warnings |
| `GEN_NO_ITEMS_PRODUCED` | (없음) | 모델이 문항을 하나도 만들지 않았다. 문서 내용을 확인하고 다시 시도해야 한다. | The model produced no items at all. Check the document content and try again. | warnings |
| `GEN_ALL_DROPPED` | `count` (int) 예: 5 | 만들어진 문항 {count}개가 모두 검증 관문에서 폐기됐다. 근거를 댈 수 없는 문항은 내보내지 않는다. 문서를 바꿔 다시 시도해야 한다. | All {count} generated item(s) were dropped at the validation gates. Items without traceable evidence are never released. Try again with a different document. | warnings |
| `GEN_FEWER_THAN_REQUESTED` | `requested` (int) 예: 5<br>`passed` (int) 예: 3 | 요청한 {requested}개 중 {passed}개만 관문을 통과했다. 더 필요하면 문항 수를 늘려 다시 요청해야 한다. | Only {passed} of the {requested} requested items passed the gates. Ask again with a larger item count if you need more. | warnings |
| `GEN_TYPE_SKEWED` | `itemType` (str) 예: "report"<br>`count` (int) 예: 4 | '{itemType}' 유형 문항이 {count}개로 몰려 있다. 시험이 한 가지 상황만 묻게 되지 않는지 확인해야 한다. | {count} items are concentrated in the '{itemType}' type. Check that the test is not asking about only one situation. | warnings |
| `GEN_DUPLICATE_ITEM` | (없음) | 앞 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이다. | The prompt largely overlaps the previous item, so it is effectively the same item. | warnings |

---

## POST /generate-items · POST /verify-items 공용 (27개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `GEN_MEMORIZATION_SUSPECT` | `itemId` (str) 예: "GEN-W-002"<br>`marker` (str(한국어 그대로)) 예: "몇 조" | [{itemId}] 지시문에 '{marker}' 가 있어 암기 문제로 보일 수 있다. 승인 전에 사람이 확인해야 한다. | [{itemId}] The prompt contains '{marker}', which may make it look like a memorization question. A human should check it before approval. | warnings |
| `DROP_NOT_OBJECT` | (없음) | 문항이 JSON 객체 모양이 아니다. | The item is not shaped like a JSON object. | dropped detail |
| `DROP_REQUIRED_FIELD_MISSING` | `key` (str) 예: "prompt" | 필수 항목 '{key}' 이(가) 비었거나 글자가 아니다. | The required field '{key}' is empty or is not a string. | dropped detail |
| `DROP_CHECKLIST_NOT_LIST` | (없음) | checklist 가 목록이 아니다. | 'checklist' is not a list. | dropped detail |
| `DROP_ITEM_TYPE_INVALID` | `itemType` (str) 예: "quiz"<br>`allowed` (str) 예: "report, request, notice" | 문항 유형 '{itemType}' 은(는) 쓸 수 있는 유형이 아니다(허용: {allowed}). | Item type '{itemType}' is not a usable type (allowed: {allowed}). | dropped detail |
| `DROP_REGISTER_INVALID` | `register` (str) 예: "casual" | 말투 '{register}' 는 formal 또는 polite 가 아니다. | Register '{register}' is neither formal nor polite. | dropped detail |
| `DROP_CHECKLIST_COUNT` | `count` (int) 예: 1<br>`min` (int) 예: 2<br>`max` (int) 예: 5 | 체크리스트가 {count}개다(허용 {min}~{max}개). | The checklist has {count} entries (allowed {min}-{max}). | dropped detail |
| `DROP_CHECKLIST_ENTRY_NOT_OBJECT` | `index` (int) 예: 2 | 체크리스트 {index}번이 객체가 아니다. | Checklist entry #{index} is not an object. | dropped detail |
| `DROP_CHECKLIST_ENTRY_NO_DESCRIPTION` | `index` (int) 예: 3 | 체크리스트 {index}번에 설명이 없다. | Checklist entry #{index} has no description. | dropped detail |
| `DROP_CHECKLIST_WEIGHT_NOT_NUMBER` | `index` (int) 예: 1 | 체크리스트 {index}번의 weight 가 숫자가 아니다. | The weight of checklist entry #{index} is not a number. | dropped detail |
| `DROP_CHECKLIST_WEIGHT_OUT_OF_RANGE` | `index` (int) 예: 2<br>`weight` (float) 예: 4.0<br>`min` (float) 예: 0.5<br>`max` (float) 예: 2.0 | 체크리스트 {index}번의 weight 가 {weight} 로 허용 범위({min}~{max})를 벗어났다. | The weight of checklist entry #{index} is {weight}, outside the allowed range ({min}-{max}). | dropped detail |
| `DROP_PROMPT_LENGTH` | `chars` (int) 예: 40<br>`min` (int) 예: 80<br>`max` (int) 예: 400 | 지시문이 {chars}자다(허용 {min}~{max}자). | The prompt is {chars} characters long (allowed {min}-{max}). | dropped detail |
| `DROP_PROMPT_NO_NUMBERING` | `markers` (str) 예: "①, ②, 1), 2)" | 지시문에 번호 기호 {markers} 가 없어 무엇을 써야 하는지 나뉘어 있지 않다. | The prompt has none of the numbering markers {markers}, so what to write is not broken out into parts. | dropped detail |
| `DROP_PROMPT_RUNON` | `chars` (int) 예: 34<br>`maxChars` (int) 예: 25 | 지시문에 띄어쓰기 없이 {chars}자가 이어지는 곳이 있다(허용 {maxChars}자). 문서에서 띄어쓰기가 사라진 문구가 그대로 새어 나온 것으로 보인다. | The prompt has a run of {chars} characters with no space (limit {maxChars}). It looks like text that lost its spacing in the document leaked through. | dropped detail |
| `DROP_PROMPT_NO_WRITING_VERB` | (없음) | 지시문에 쓰기를 시키는 말(쓰세요·작성하세요·알리세요 등)이 없다. 글을 쓰게 하는 문항이 아니라 지식을 묻는 문항으로 보인다. | The prompt contains no instruction to write (write, fill in, notify, ...). It reads as a knowledge question rather than a writing task. | dropped detail |
| `DROP_EVIDENCE_EMPTY` | (없음) | 근거 인용이 비어 있다. | The supporting citation is empty. | dropped detail |
| `DROP_EVIDENCE_CROSSES_CHUNK` | (없음) | 인용이 문서에서 잘라낸 자리를 가로지른다. 실제 문서에는 이어져 있지 않은 문장이다. | The citation crosses a boundary where the document was split. These sentences are not contiguous in the real document. | dropped detail |
| `DROP_EVIDENCE_JOINER` | `marker` (str) 예: "…" | 인용에 이음표 '{marker}' 가 있어 여러 구절을 합친 것으로 보인다. | The citation contains the joiner '{marker}', so it looks like several passages stitched together. | dropped detail |
| `DROP_EVIDENCE_TOO_SHORT` | `chars` (int) 예: 4<br>`minChars` (int) 예: 10 | 인용이 {chars}자로 너무 짧아 근거로 인정하지 않는다(최소 {minChars}자). | The citation is {chars} characters long, too short to count as evidence (minimum {minChars}). | dropped detail |
| `DROP_EVIDENCE_TOO_LONG` | `chars` (int) 예: 320<br>`maxChars` (int) 예: 200 | 인용이 {chars}자로 너무 길다(최대 {maxChars}자). 짧은 한 구절만 인용해야 어디를 근거로 삼았는지 사람이 확인할 수 있다. | The citation is {chars} characters long, too long (maximum {maxChars}). Only a short passage should be cited so a human can check what it was based on. | dropped detail |
| `DROP_EVIDENCE_WRAP` | `label` (str) 예: "문항 근거"<br>`labelNotice` (notice) 예: → DROP_LABEL_ITEM_EVIDENCE<br>`detail` (str) 예: "근거 인용이 비어 있다."<br>`detailNotice` (notice) 예: → DROP_EVIDENCE_EMPTY | {label}: {detail} | {label}: {detail} | dropped detail |
| `DROP_LABEL_ITEM_EVIDENCE` | (없음) | 문항 근거 | Item evidence | dropped detail 안의 라벨 |
| `DROP_LABEL_CHECKLIST_EVIDENCE` | `index` (int\|str) 예: "c2" | 체크리스트 {index}번 근거 | Checklist #{index} evidence | dropped detail 안의 라벨 |
| `DROP_EVIDENCE_NOT_FOUND` | `label` (str) 예: "문항 근거"<br>`labelNotice` (notice) 예: → DROP_LABEL_ITEM_EVIDENCE | {label}: 문서에서 찾을 수 없는 인용이다(지어낸 근거로 보고 폐기했다). | {label}: this citation cannot be found in the document (treated as fabricated evidence and dropped). | dropped detail |
| `DROP_ANSWER_IN_PROMPT` | `ratio` (str) 예: "71%"<br>`threshold` (str) 예: "50%" | 지시문 글자의 {ratio}가 근거 구절과 그대로 겹친다(기준 {threshold}). 답이 문제 안에 들어 있다. | {ratio} of the prompt's characters overlap the evidence passage verbatim (threshold {threshold}). The answer is inside the question. | dropped detail |
| `DROP_TRIPS_COPY_GUARD` | (없음) | 근거 구절을 그대로 옮겨 쓴 답안이 채점기의 '지시문 베끼기' 가드에 걸린다. 성실한 응시자가 무효 0점을 받을 수 있는 문항이다. | An answer that copies the evidence passage verbatim would trip the scorer's 'prompt copying' guard. An honest test taker could be voided to zero on this item. | dropped detail |
| `DROP_CONVERT_FAILED` | `type` (str) 예: "ValidationError" | 채점 API 형식으로 바꾸지 못했다({type}). | The item could not be converted into the scoring API format ({type}). | dropped detail |

---

## POST /verify-items (2개)

| code | params | 한국어 원문 | 영어 초안 | 어디서 나오는지 |
|---|---|---|---|---|
| `VERIFY_DOCUMENT_MISMATCH` | (없음) | 보내온 문서가 문항을 만들 때 쓴 문서와 다르다. 인용 위치가 어긋날 수 있으니 문서를 다시 확인해야 한다. | The document sent differs from the one the items were generated from. Citation offsets may not line up, so check the document again. | warnings |
| `VERIFY_DUPLICATE_ITEM` | `itemId` (str) 예: "GEN-W-001" | '{itemId}' 문항과 지시문이 대부분 겹쳐 사실상 같은 문항이 됐다. | The prompt largely overlaps item '{itemId}', so it has become effectively the same item. | warnings |
