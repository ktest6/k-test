# anti-cheat

- **담당자**: 김도영

Azure Document Intelligence와 AWS Rekognition을 활용해 시험 시작 전 본인 인증·이어폰 탐지와 시험 중 부정행위 모니터링을 수행하는 FastAPI 서비스입니다.

탐지 결과는 Rule Engine에서 위험도와 조치로 평가되며, Event Engine을 거쳐 백엔드에서 사용할 수 있는 이벤트 응답으로 변환됩니다.

---

# 1. 구조

```text
anti-cheat/
├── app/
│   ├── main.py
│   │   └── FastAPI 애플리케이션 생성 및 API Router 등록
│   │
│   ├── api/
│   │   ├── identity.py
│   │   │   └── 시험 시작 전 본인 인증 요청 처리
│   │   ├── earphone_detection.py
│   │   │   └── 시험 시작 전 양쪽 귀 이미지 검사
│   │   └── monitoring.py
│   │       └── 시선 보정 및 시험 중 프레임 분석
│   │
│   ├── schemas/
│   │   ├── identity.py
│   │   ├── earphone_detection.py
│   │   ├── monitoring.py
│   │   └── error.py
│   │       └── 요청·응답 및 오류 스키마 정의
│   │
│   └── core/
│       ├── config.py
│       │   └── 외부 서비스 설정 및 탐지 임계값 관리
│       └── error_handlers.py
│           └── 공통 API 오류 응답 처리
│
├── modules/
│   ├── aws_rekognition/
│   │   └── client.py
│   │       └── AWS Rekognition Client 생성
│   │
│   ├── azure_document_intelligence/
│   │   ├── client.py
│   │   │   └── Azure Document Intelligence Client 생성
│   │   └── id_document.py
│   │       └── 여권 문서 분석 요청
│   │
│   ├── identity_verification/
│   │   ├── service.py
│   │   │   └── 시험 시작 전 본인 인증 전체 흐름 관리
│   │   ├── document_reader.py
│   │   │   └── 여권 정보 판독 및 필수 항목 추출
│   │   ├── document_classifier.py
│   │   │   └── 문서 종류 확인
│   │   ├── applicant_matcher.py
│   │   │   └── 여권 정보와 신청 정보 비교
│   │   ├── field_normalizer.py
│   │   │   └── 이름·생년월일·여권번호 정규화
│   │   └── face_compare.py
│   │       └── 여권 사진과 웹캠 얼굴 비교
│   │
│   ├── earphone_detection/
│   │   ├── detector.py
│   │   │   └── 얼굴 자세 및 이어폰 관련 Label 탐지
│   │   ├── analyzer.py
│   │   │   └── 귀 노출 여부와 이어폰 착용 여부 판단
│   │   └── service.py
│   │       └── 양쪽 귀 이미지 검사 흐름 관리
│   │
│   ├── cheating_detection/
│   │   ├── face_detection.py
│   │   │   └── 프레임에서 얼굴 정보 검출
│   │   ├── face_monitor.py
│   │   │   └── 얼굴 화면 이탈 및 다중 인원 판단
│   │   ├── gaze_calibration.py
│   │   │   └── 응시자별 시선·고개 중앙 기준값 계산
│   │   ├── gaze_monitor.py
│   │   │   └── 시선 및 고개 방향 분석
│   │   ├── gaze_state.py
│   │   │   └── 프레임 간 연속 이탈 상태 관리
│   │   ├── identity_monitor.py
│   │   │   └── 시험 중 기준 얼굴과 현재 얼굴 비교
│   │   ├── rule_engine.py
│   │   │   └── 탐지 결과의 위험도와 조치 결정
│   │   ├── event_engine.py
│   │   │   └── Rule 결과를 이벤트 응답으로 변환
│   │   └── service.py
│   │       └── 시험 중 프레임 분석 전체 흐름 관리
│   │
│   ├── object_detection/
│   │   ├── detector.py
│   │   │   └── 휴대폰·이어폰 관련 Label 탐지
│   │   └── analyzer.py
│   │       └── 신뢰도와 고개 각도를 이용한 금지 객체 판정
│   │
│   └── common/
│       ├── exceptions.py
│       │   └── 서비스 공통 예외 정의
│       └── image_validation.py
│           └── 이미지 형식과 크기 검증
│
├── scripts/
│   ├── run_identity_verification.py
│   ├── run_document_reader.py
│   ├── run_applicant_matcher.py
│   ├── run_earphone_detection.py
│   ├── run_gaze_calibration.py
│   ├── run_gaze_monitor.py
│   ├── run_gaze_monitor_manual_test.py
│   └── run_monitoring.py
│       └── 기능별 로컬 수동 테스트 스크립트
│
├── tests/
│   └── Rule Engine, Event Engine, 시선 상태 및 API 계약 테스트
│
├── .env.example
├── requirements.txt
├── Dockerfile
├── docker-compose.yml
└── README.md
```

---

# 2. 주요 기능

## 시험 시작 전 본인 인증

- 여권 이미지와 시험 시작 전 웹캠 캡처 이미지 수신
- 여권의 이름·생년월일·여권번호 판독
- 판독한 여권 정보와 응시자가 입력한 신청 정보 대조
- 신청 정보가 일치한 경우 여권 사진과 웹캠 얼굴 비교
- 얼굴 유사도 임계값에 따른 본인 여부 판정
- 신청 정보 및 얼굴 비교 결과 반환
- 현재 지원 문서 종류는 여권(`passport`)

## 시험 시작 전 이어폰 탐지

- 응시자의 왼쪽·오른쪽 귀 이미지 수신
- 이미지 형식과 크기 검증
- 얼굴 yaw를 이용한 귀 노출 자세 확인
- `Earbuds`, `Headphones` 등 이어폰 관련 Label 분석
- 설정된 신뢰도 임계값에 따른 이어폰 착용 여부 판정
- 한쪽이라도 이어폰이 탐지되면 시험 시작 제한
- 양쪽 귀 노출 여부와 재촬영 안내 메시지 반환

## 시선 보정

- 시험 시작 전 화면 중앙을 응시한 이미지 여러 장 수신
- 정상적으로 검출된 얼굴의 Eye Direction과 Head Pose 분석
- 응시자별 눈·고개 중앙 기준값 계산
- 최소 유효 샘플 수를 충족한 경우 보정값 반환
- 계산된 보정값을 시험 중 모니터링 요청에 사용

## 시험 중 모니터링

- 시험 중 웹캠 프레임 이미지 수신
- 얼굴 화면 이탈 및 다중 인원 감지
- Eye Direction과 Head Pose 기반 시선·고개 방향 분석
- 응시자별 보정값을 적용한 상대 시선·고개 방향 계산
- 이전 프레임 상태를 이용한 연속 이탈 횟수와 지속 시간 관리
- 요청된 시점에 기준 얼굴과 현재 얼굴을 비교해 동일인 여부 확인
- 휴대폰 탐지
- 고개 각도 조건을 만족하는 경우 이어폰 추가 탐지
- Rule Engine을 이용한 위험도(`severity`)와 조치(`decision`) 결정
- Event Engine을 이용한 `event_summary`와 `events` 응답 생성

현재 프레임의 얼굴 분석 결과는 얼굴·시선·고개 방향 판단에서 함께 사용하므로, 동일 프레임에 대한 얼굴 검출을 중복 호출하지 않습니다.

---

# 3. API

서버 실행 후 Swagger 문서는 다음 주소에서 확인할 수 있습니다.

```text
http://localhost:8000/docs
```

## 상태 확인

```http
GET /
GET /health
```

## 본인 인증

```http
POST /identity/verify
```

주요 입력값:

- `exam_id`
- `examinee_id`
- `captured_at`
- `document_type`
- `last_name`
- `first_name`
- `birth_date`
- `document_number`
- `source_image`: 여권 이미지
- `target_image`: 웹캠 캡처 이미지

## 시험 시작 전 이어폰 탐지

```http
POST /earphone/detect
```

주요 입력값:

- `exam_id`
- `examinee_id`
- `left_ear_image`
- `right_ear_image`

## 시선 보정

```http
POST /monitoring/gaze-calibration
```

주요 입력값:

- `exam_id`
- `examinee_id`
- `calibration_images`: 화면 중앙 응시 이미지 목록

## 시험 중 프레임 분석

```http
POST /monitoring/analyze
```

주요 입력값:

- `exam_id`
- `examinee_id`
- `request_id`
- `captured_at`: 타임존을 포함한 촬영 시각
- `elapsed_ms`
- `capture_sequence`
- `run_identity_check`
- `eye_yaw_center`
- `eye_pitch_center`
- `head_yaw_center`
- `head_pitch_center`
- `previous_gaze_state`
- `current_image`
- `reference_image`: 중간 동일인 확인을 수행할 때 사용

`run_identity_check=true`인 경우 `reference_image`를 함께 전달해야 합니다. 응답의 `gaze_monitor.state`는 백엔드가 저장한 뒤 다음 요청의 `previous_gaze_state`로 전달합니다.

---

# 4. 개발 환경

- Python 3.11
- FastAPI
- Uvicorn
- Pydantic
- Boto3
- AWS Rekognition
- Azure AI Document Intelligence
- OpenCV
- NumPy
- python-dotenv
- python-multipart

---

# 5. 로컬 실행

프로젝트의 `anti-cheat` 디렉토리로 이동합니다.

```bash
cd anti-cheat
```

가상환경을 생성하고 활성화합니다.

### macOS / Linux

```bash
python3.11 -m venv face_api
source face_api/bin/activate
```

### Windows PowerShell

```powershell
python -m venv face_api
face_api\Scripts\Activate.ps1
```

의존성을 설치합니다.

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

서버를 실행합니다.

```bash
uvicorn app.main:app --reload
```

기본 실행 주소는 다음과 같습니다.

```text
http://localhost:8000
```

---

# 6. 환경변수

`.env.example`을 참고해 `anti-cheat/.env` 파일을 구성합니다.

외부 서비스 설정:

```dotenv
AWS_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=
```

주요 판정 설정:

```dotenv
IDENTITY_SIMILARITY_THRESHOLD=80
IDENTITY_SIMILARITY_RETRIEVAL_THRESHOLD=0.0

EARPHONE_CONFIDENCE_THRESHOLD=45.0
PRE_EXAM_EARPHONE_CONFIDENCE_THRESHOLD=55.0
PRE_EXAM_EARPHONE_HEAD_YAW_THRESHOLD=50.0

GAZE_EYE_YAW_THRESHOLD=15.0
GAZE_EYE_PITCH_THRESHOLD=15.0
GAZE_HEAD_YAW_THRESHOLD=25.0
GAZE_HEAD_PITCH_THRESHOLD=20.0
GAZE_MINIMUM_EYE_CONFIDENCE=80.0
GAZE_PERSISTENT_COUNT_THRESHOLD=3
GAZE_CALIBRATION_MINIMUM_SAMPLE_COUNT=3

PHONE_CONFIDENCE_THRESHOLD=50.0
EARPHONE_HEAD_YAW_THRESHOLD=40.0
```

전체 환경변수와 기본값은 `.env.example`과 `app/core/config.py`에서 확인할 수 있습니다. 운영 환경에 맞는 임계값은 코드에 직접 작성하지 않고 환경변수로 관리합니다.

---

# 7. 로컬 테스트

`scripts` 디렉토리에는 로컬 이미지로 각 기능을 확인할 수 있는 실행 파일이 있습니다.

```bash
python scripts/run_document_reader.py
python scripts/run_applicant_matcher.py
python scripts/run_identity_verification.py
python scripts/run_earphone_detection.py
python scripts/run_gaze_calibration.py
python scripts/run_gaze_monitor.py
python scripts/run_gaze_monitor_manual_test.py
python scripts/run_monitoring.py
```

각 스크립트에서 사용하는 이미지 경로와 테스트 입력값을 로컬 환경에 맞게 설정해야 합니다.

전체 Python 파일의 문법을 확인하려면 다음 명령을 실행합니다.

```bash
python -m compileall app modules scripts
```

테스트 코드는 다음 명령으로 실행할 수 있습니다.

```bash
python -m pytest
```

실제 여권, 신분증, 얼굴 이미지나 개인정보가 포함된 로그는 저장소에 커밋하지 않습니다.

---

# 8. 보안 주의 사항

다음 정보는 GitHub, README, 소스 코드, 공유 문서 또는 공개 메신저 채널에 작성하지 않습니다.

- AWS Access Key ID
- AWS Secret Access Key
- AWS Session Token
- Azure Document Intelligence Endpoint
- Azure Document Intelligence API Key
- `.env`
- `~/.aws/credentials`
- 실제 여권 및 신분증 이미지
- 실제 응시자의 웹캠 이미지
- 개인정보가 포함된 로그
- 운영 서버 자격 증명

자격 증명이 저장소에 노출된 경우 즉시 키를 폐기·재발급하고 담당자에게 공유합니다.
