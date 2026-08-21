# Anti-cheat FastAPI 서비스

시험 시작 전 본인인증·이어폰 검사와 시험 중 부정행위 모니터링을 담당하는 FastAPI 서비스입니다.

- Azure Document Intelligence: 여권 필드 판독
- AWS Rekognition CompareFaces: 얼굴 대조 및 시험 중 동일인 검사
- AWS Rekognition DetectFaces: 얼굴 수, EyeDirection, HeadPose 분석
- AWS Rekognition DetectLabels: 이어폰 및 휴대폰 탐지
- Rule/Event Engine: 탐지 결과를 위험도와 이벤트로 변환

백엔드는 `MONITERING_URL`을 base URL로 사용해 이 서비스의 API를 호출합니다. 환경변수 이름은 현재 백엔드 코드와의 호환을 위해 `MONITERING_URL` 철자를 사용합니다.

## 1. 제공 API

| Method | Path | 용도 |
| --- | --- | --- |
| `POST` | `/identity/verify` | 여권 정보와 웹캠 얼굴을 이용한 본인인증 |
| `POST` | `/earphone/detect` | 시험 시작 전 양쪽 귀 이미지의 이어폰 검사 |
| `POST` | `/monitoring/gaze-calibration` | 중앙 응시 이미지로 개인별 EyeDirection 기준값 계산 |
| `POST` | `/monitoring/analyze` | 시험 중 웹캠 프레임의 얼굴·시선·동일인·금지 객체 분석 |
| `GET` | `/health` | 애플리케이션 상태 확인 |

FastAPI 실행 후 Swagger 문서는 `http://localhost:8000/docs`에서 확인할 수 있습니다.

### 1.1 `POST /identity/verify`

`multipart/form-data` 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `exam_id` | string | O | 시험 식별자 |
| `examinee_id` | string | O | 응시자 식별자 |
| `captured_at` | datetime | O | 얼굴 이미지 촬영 시각 |
| `source_image` | file | O | 여권 이미지 |
| `target_image` | file | O | 웹캠 얼굴 이미지 |
| `last_name` | string | O | 신청 정보의 성 |
| `first_name` | string | O | 신청 정보의 이름 |
| `birth_date` | date | O | 신청 정보의 생년월일 |
| `document_number` | string | O | 신청 정보의 여권번호 |
| `document_type` | `passport` | O | 현재 지원 문서는 여권만 해당 |

처리 순서:

1. Azure Document Intelligence의 `prebuilt-idDocument` 모델로 여권을 판독합니다.
2. 성, 이름, 생년월일, 여권번호를 정규화해 신청 정보와 비교합니다.
3. 신청 정보가 모두 일치할 때만 AWS CompareFaces를 실행합니다.
4. 신청 정보와 얼굴 비교가 모두 성공해야 `verified=true`를 반환합니다.

응답의 `field_matches`에는 다음 값이 포함됩니다.

```json
{
  "last_name": true,
  "first_name": true,
  "birth_date": true,
  "document_number": true
}
```

### 1.2 `POST /earphone/detect`

`multipart/form-data` 필드:

| 필드 | 타입 | 필수 |
| --- | --- | --- |
| `exam_id` | string | O |
| `examinee_id` | string | O |
| `left_ear_image` | file | O |
| `right_ear_image` | file | O |

양쪽 이미지를 각각 검증하고 DetectLabels 결과의 `Earbuds`, `Headphones` 후보를 설정된 confidence 기준으로 판정합니다.

### 1.3 `POST /monitoring/gaze-calibration`

`multipart/form-data` 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `exam_id` | string | O | 시험 식별자 |
| `examinee_id` | string | O | 응시자 식별자 |
| `calibration_images` | file[] | O | 화면 중앙을 응시한 이미지 여러 장 |

각 이미지에 DetectFaces를 한 번 호출하며, 얼굴이 정확히 한 명이고 EyeDirection confidence가 기준 이상인 표본만 사용합니다. 유효 표본 수는 `GAZE_CALIBRATION_MINIMUM_SAMPLE_COUNT` 이상이어야 합니다.

유효 Yaw와 Pitch 표본의 중앙값(median)을 각각 `eye_yaw_center`, `eye_pitch_center`로 반환합니다.

```json
{
  "exam_id": "7",
  "examinee_id": "9",
  "calibrated": true,
  "sample_count": 6,
  "eye_yaw_center": -2.1937,
  "eye_pitch_center": -20.7994
}
```

FastAPI는 calibration을 저장하지 않습니다. 백엔드가 응답값을 DB에 저장하고 이후 `/monitoring/analyze` 요청에 다시 전달합니다.

### 1.4 `POST /monitoring/analyze`

`multipart/form-data` 필드:

| 필드 | 타입 | 필수 | 설명 |
| --- | --- | --- | --- |
| `exam_id` | string | O | 시험 식별자 |
| `examinee_id` | string | O | 응시자 식별자 |
| `request_id` | string | O | 요청 고유 식별자 |
| `captured_at` | timezone-aware datetime | O | 프레임 촬영 시각 |
| `elapsed_ms` | integer | O | 시험 시작 후 경과 시간, 0 이상 |
| `capture_sequence` | integer | O | 프레임 순번, 1 이상 |
| `run_identity_check` | boolean | X | 중간 동일인 검사 실행 요청, 기본 `false` |
| `eye_yaw_center` | number | X | calibration Yaw 중심값 |
| `eye_pitch_center` | number | X | calibration Pitch 중심값 |
| `previous_gaze_state` | JSON string | X | 직전 응답의 `gaze_monitor.state` |
| `current_image` | file | O | 현재 웹캠 프레임 |
| `reference_image` | file | X | 중간 동일인 검사용 기준 얼굴 |

프레임 처리 흐름:

1. 현재 이미지에 DetectFaces를 한 번 호출합니다.
2. 동일한 `FaceDetails`를 얼굴 수, EyeDirection, HeadPose 분석에 재사용합니다.
3. calibration이 있으면 상대 EyeDirection을 계산합니다.

```text
relative_eye_yaw = current_eye_yaw - eye_yaw_center
relative_eye_pitch = current_eye_pitch - eye_pitch_center
```

4. `previous_gaze_state`와 현재 프레임으로 다음 연속 시선 상태를 계산합니다.
5. `run_identity_check=true`, 기준 얼굴 존재, 현재 얼굴 한 명 조건을 만족하면 CompareFaces를 실행합니다.
6. DetectLabels로 휴대폰과 이어폰 후보를 분석합니다.
7. Rule Engine과 Event Engine이 위험도, decision, clip 생성 여부와 이벤트 목록을 만듭니다.

FastAPI는 연속 시선 상태를 메모리나 DB에 저장하지 않습니다. 응답의 `gaze_monitor.state`를 백엔드가 저장한 뒤 다음 요청의 `previous_gaze_state`로 돌려줘야 합니다.

## 2. 디렉터리 구조

```text
anti-cheat/
│
├── app/
│   ├── main.py
│   │   └── FastAPI 애플리케이션 실행 및 API Router 등록
│   │
│   ├── api/
│   │   ├── identity.py
│   │   │   └── 시험 시작 전 여권·신청 정보·얼굴 본인인증 요청 수신
│   │   ├── earphone_detection.py
│   │   │   └── 시험 시작 전 양쪽 귀 이미지 수신 및 이어폰 검사 요청
│   │   └── monitoring.py
│   │       └── 시선 보정 및 시험 중 프레임 모니터링 요청 수신
│   │
│   ├── schemas/
│   │   ├── identity.py
│   │   │   └── 본인인증 응답과 문서 유형 구조 정의
│   │   ├── earphone_detection.py
│   │   │   └── 이어폰 탐지 응답 구조 정의
│   │   └── monitoring.py
│   │       └── 얼굴·시선·동일인·객체·이벤트 및 gaze state 구조 정의
│   │
│   └── core/
│       └── config.py
│           └── AWS·Azure 설정과 얼굴·이어폰·휴대폰·시선 Threshold 검증
│
├── modules/
│   ├── aws_rekognition/
│   │   └── client.py
│   │       └── AWS Rekognition Client 생성 및 공통 제공
│   │
│   ├── azure_document_intelligence/
│   │   ├── client.py
│   │   │   └── Azure Document Intelligence Client 생성
│   │   └── id_document.py
│   │       └── prebuilt-idDocument 모델 호출
│   │
│   ├── identity_verification/
│   │   ├── document_classifier.py
│   │   │   └── 입력 문서 유형 분류
│   │   ├── document_reader.py
│   │   │   └── Azure 응답에서 여권 필드 추출
│   │   ├── field_normalizer.py
│   │   │   └── 이름·생년월일·여권번호 비교용 값 정규화
│   │   ├── applicant_matcher.py
│   │   │   └── 판독 필드와 신청 정보 비교
│   │   ├── face_compare.py
│   │   │   └── CompareFaces 호출 및 결과 해석
│   │   └── service.py
│   │       └── 문서 판독·신청 정보 비교·얼굴 대조 전체 흐름 관리
│   │
│   ├── earphone_detection/
│   │   ├── detector.py
│   │   │   └── DetectLabels로 귀 이미지의 이어폰 후보 탐지
│   │   ├── analyzer.py
│   │   │   └── Confidence 기준으로 이어폰 착용 여부 판단
│   │   └── service.py
│   │       └── 이미지 검증부터 최종 이어폰 판정까지 전체 흐름 관리
│   │
│   ├── object_detection/
│   │   ├── detector.py
│   │   │   └── 시험 중 프레임에 DetectLabels 호출
│   │   └── analyzer.py
│   │       └── 휴대폰 및 이어폰 후보 판정
│   │
│   ├── cheating_detection/
│   │   ├── face_detection.py
│   │   │   └── DetectFaces 호출 및 FaceDetails 반환
│   │   ├── face_monitor.py
│   │   │   └── 얼굴 화면 이탈 및 다중 인원 판단
│   │   ├── gaze_calibration.py
│   │   │   └── 유효 시선 표본의 개인별 중앙값 계산
│   │   ├── gaze_monitor.py
│   │   │   └── EyeDirection과 HeadPose 기반 시선·고개 방향 분석
│   │   ├── gaze_state.py
│   │   │   └── 이전 상태와 현재 프레임으로 다음 연속 이탈 상태 계산
│   │   ├── identity_monitor.py
│   │   │   └── 시험 중 기준 얼굴과 현재 얼굴 비교
│   │   ├── rule_engine.py
│   │   │   └── 탐지 결과 평가 및 Severity·Decision 결정
│   │   ├── event_engine.py
│   │   │   └── Rule 결과를 event_summary와 events로 변환
│   │   └── service.py
│   │       └── FaceDetails 재사용을 포함한 시험 중 프레임 분석 전체 관리
│   │
│   └── common/
│       ├── exceptions.py
│       │   └── 본인인증·모니터링·AWS/Azure 공통 예외 정의
│       └── image_validation.py
│           └── 전달받은 이미지 bytes 공통 검증
│
├── scripts/
│   ├── run_document_reader.py
│   │   └── 로컬 여권 이미지 기반 Azure 문서 판독 테스트
│   ├── run_applicant_matcher.py
│   │   └── 판독 정보와 신청 정보 비교 테스트
│   ├── run_identity_verification.py
│   │   └── 문서 판독·신청 정보·얼굴 대조 통합 테스트
│   ├── run_earphone_detection.py
│   │   └── 로컬 양쪽 귀 이미지 기반 이어폰 탐지 테스트
│   ├── run_gaze_calibration.py
│   │   └── 중앙 응시 이미지 기반 시선 보정 테스트
│   ├── run_gaze_monitor.py
│   │   └── 로컬 이미지 기반 시선·고개 방향 분석 테스트
│   ├── run_gaze_monitor_manual_test.py
│   │   └── 연속 시선 상태 수동 시나리오 테스트
│   └── run_monitoring.py
│       └── 얼굴·시선·동일인·객체·Rule·Event 통합 테스트 및 결과 저장
│
├── data/
│   ├── compare/
│   │   ├── source.jpg
│   │   │   └── 문서 또는 기준 얼굴 테스트 이미지
│   │   ├── target_true.jpg
│   │   │   └── 동일인 얼굴 대조 테스트 이미지
│   │   ├── target_false.png
│   │   │   └── 타인 얼굴 대조 테스트 이미지
│   │   └── no_face.png
│   │       └── 얼굴 미검출 예외 테스트 이미지
│   │
│   ├── earphone/
│   │   ├── left_pass.jpg / right_pass.jpg
│   │   │   └── 이어폰 미착용 테스트 이미지
│   │   └── *_fail.jpg
│   │       └── 이어폰 또는 선이 보이는 탐지 테스트 이미지
│   │
│   ├── gaze/
│   │   ├── gaze_center/
│   │   │   └── 시선 보정용 중앙 응시 이미지 모음
│   │   └── *_img/
│   │       └── 연속 시선·고개 방향 테스트용 프레임 모음
│   │
│   ├── monitoring/
│   │   ├── one_face.jpg
│   │   │   └── 정상 단일 얼굴 테스트 이미지
│   │   ├── no_face.png
│   │   │   └── 얼굴 이탈 테스트 이미지
│   │   ├── multiple_faces.jpg
│   │   │   └── 다중 인원 테스트 이미지
│   │   └── identity_mismatch.jpg
│   │       └── 시험 중 동일인 불일치 테스트 이미지
│   │
│   └── logs/
│       └── exam_{id}/
│           └── 로컬 통합 테스트가 생성한 시험별 JSON 결과
│
├── requirements.txt
│   └── FastAPI 및 AWS·Azure 연동 패키지 목록
├── .env.example
│   └── 서비스 연결 정보와 Threshold 환경변수 예시
├── Dockerfile
├── .gitignore
└── README.md
```

## 3. 개발 환경 설정

권장 환경은 Python 3.11입니다.

```bash
cd anti-cheat
python3.11 -m venv face_api
source face_api/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Conda 환경을 사용하는 경우:

```bash
conda create -n face_api python=3.11
conda activate face_api
python -m pip install -r requirements.txt
```

## 4. 환경변수

`.env.example`을 참고해 `anti-cheat/.env`를 준비합니다. `.env`는 Git에 커밋하지 않습니다.

```env
AWS_REGION=ap-northeast-2
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=

AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT=
AZURE_DOCUMENT_INTELLIGENCE_KEY=

IDENTITY_SIMILARITY_THRESHOLD=80
IDENTITY_SIMILARITY_RETRIEVAL_THRESHOLD=0.0
EARPHONE_CONFIDENCE_THRESHOLD=45.0

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

Threshold는 코드에 직접 작성하지 않고 `app/core/config.py`를 통해 환경변수에서 읽습니다. AWS 자격 증명은 AWS CLI profile, IAM role 또는 컨테이너 실행 환경으로 제공할 수도 있습니다.

## 5. 실행

로컬 개발 서버:

```bash
cd anti-cheat
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

상태 및 OpenAPI 확인:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/openapi.json
```

Docker Compose를 사용하는 경우 저장소 루트에서 실행합니다.

```bash
docker compose up --build anti-cheat
```

기본 포트 매핑을 사용하면 서비스와 Swagger 문서는 각각 `http://localhost:8080`, `http://localhost:8080/docs`에서 확인할 수 있습니다. `ANTI_CHEAT_PORT`를 지정한 경우에는 해당 포트를 사용합니다.

백엔드 `.env`에는 끝 슬래시 없이 다음과 같이 설정합니다.

```env
MONITERING_URL=http://localhost:8000
REQUIRE_MONITORING_SERVICE=true
```

위 값은 FastAPI를 `uvicorn`으로 직접 실행했을 때의 예시입니다. Docker Compose의 기본 포트 매핑을 사용한다면 `MONITERING_URL=http://localhost:8080`으로 설정합니다.

## 6. 로컬 수동 테스트 스크립트

스크립트는 실제 AWS/Azure 호출을 포함할 수 있습니다. 각 스크립트 상단의 이미지 경로와 입력값을 로컬 환경에 맞게 설정한 뒤 실행합니다.

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

| 스크립트 | 검증 대상 |
| --- | --- |
| `run_document_reader.py` | Azure 여권 필드 판독 |
| `run_applicant_matcher.py` | 신청 정보 정규화 및 필드별 비교 |
| `run_identity_verification.py` | Azure 여권 판독 + 신청 정보 비교 + CompareFaces |
| `run_earphone_detection.py` | 양쪽 귀 DetectLabels 및 이어폰 판정 |
| `run_gaze_calibration.py` | 다중 이미지 DetectFaces 및 median center 계산 |
| `run_gaze_monitor.py` | 단일/연속 프레임 시선 판정 |
| `run_gaze_monitor_manual_test.py` | 설정값을 사용한 시선 수동 시나리오 |
| `run_monitoring.py` | 얼굴·시선·state·동일인·객체·rule/event 통합 흐름 |

실제 여권, 얼굴, 귀 이미지와 개인정보가 포함된 출력은 저장소에 추가하지 않습니다. `data/logs` 결과 역시 승인된 예시가 아니라면 커밋하지 않습니다.

## 7. 정적 검증

AWS/Azure를 실제 호출하지 않고 문법, 앱 import, OpenAPI 등록을 확인할 수 있습니다.

```bash
python -m compileall app modules scripts
python -c "from app.main import app; print(sorted(app.openapi()['paths']))"
```

정상 상태에서는 최소 다음 API가 출력되어야 합니다.

```text
/identity/verify
/earphone/detect
/monitoring/gaze-calibration
/monitoring/analyze
```

## 8. 보안 및 데이터 취급

다음 항목은 Git에 커밋하지 않습니다.

- `.env`
- AWS Access Key, Secret Access Key, Session Token
- Azure Document Intelligence endpoint와 key
- 실제 여권 및 신분증 이미지
- 실제 응시자의 얼굴·귀·웹캠 이미지
- 개인정보가 포함된 로그
- `data/logs` 아래의 로컬 실행 결과

자격 증명이 저장소에 노출된 경우 즉시 폐기·재발급하고 팀에 공유합니다.

## 9. 상태 저장 책임

```text
FastAPI gaze-calibration
→ calibration center 반환

Backend
→ calibration DB 저장
→ analyze 요청에 calibration + previous gaze state 전달

FastAPI analyze
→ 현재 frame 분석
→ next gaze state 반환

Backend
→ next gaze state DB 저장
```

FastAPI는 calibration과 연속 gaze state의 source of truth가 아닙니다. 다중 인스턴스와 서버 재시작 환경에서도 동일하게 동작하도록 상태 저장 책임은 백엔드에 있습니다.
