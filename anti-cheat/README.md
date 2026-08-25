# anti-cheat
- **담당자**: 김도영

백엔드 연동 확인 후 main에 merge 완료했습니다.
script 디렉토리의 run 파일들은 로컬 환경에서 이미지 파일을 사용해 기능을 테스트할 수 있도록 구성되어 있습니다.

- feat/identity-verification
시험 시작 전 본인 인증 기능
- feat/monitoring
시험 중 모니터링 기능

---
# 1. 구조
```text
anti-cheat/
│
├── app/
│   ├── main.py
│   │   └── FastAPI 애플리케이션 실행 및 API Router 등록
│   │
│   ├── api/
│   │   ├── identity.py
│   │   │   └── 시험 시작 전 본인 인증 요청 수신
│   │   │
│   │   ├── earphone_detection.py
│   │   │   └── 시험 시작 전 귀 이미지 수신 및 이어폰 검사 요청
│   │   │
│   │   └── monitoring.py
│   │       └── 시험 중 프레임 이미지 및 모니터링 요청 수신
│   │
│   ├── schemas/
│   │   ├── identity.py
│   │   │   └── 본인 인증 요청 및 응답 구조 정의
│   │   │
│   │   ├── earphone_detection.py
│   │   │   └── 이어폰 탐지 요청 및 응답 구조 정의
│   │   │
│   │   └── monitoring.py
│   │       └── 얼굴·시선·동일인·객체·이벤트 모니터링 응답 구조 정의
│   │
│   └── core/
│       └── config.py
│           └── 얼굴 유사도, 이어폰, 휴대폰, 시선·고개 방향 및
│               객체 탐지 Threshold 설정
│
├── modules/
│   ├── aws_rekognition/
│   │   └── client.py
│   │       └── AWS Rekognition Client 생성 및 공통 제공
│   │
│   ├── identity_verification/
│   │   ├── service.py
│   │   │   └── 시험 시작 전 본인 인증 전체 흐름 관리
│   │   │
│   │   └── face_compare.py
│   │       └── CompareFaces 호출 및 결과 해석
│   │
│   ├── earphone_detection/
│   │   ├── detector.py
│   │   │   └── AWS Rekognition을 이용해 귀 이미지에서 이어폰 후보 탐지
│   │   │
│   │   ├── analyzer.py
│   │   │   └── 탐지 결과를 분석하여 이어폰 착용 여부 판단
│   │   │
│   │   └── service.py
│   │       └── 귀 이미지 검증부터 최종 응답 생성까지 전체 흐름 관리
│   │
│   ├── object_detection/
│   │   ├── detector.py
│   │   │   └── DetectLabels를 이용해 시험 중 프레임에서
│   │   │       Mobile Phone·Earbuds·Headphones 후보 탐지
│   │   │
│   │   └── analyzer.py
│   │       └── 휴대폰 Confidence 및 이어폰 Confidence·Head Pose 조건을
│   │           적용하여 시험 중 금지 객체 탐지 결과 생성
│   │
│   ├── cheating_detection/
│   │   ├── face_detection.py
│   │   │   └── DetectFaces 호출 및 원본 얼굴 분석 결과 반환
│   │   │
│   │   ├── face_monitor.py
│   │   │   └── 얼굴 화면 이탈 및 다중 인원 판단
│   │   │
│   │   ├── gaze_monitor.py
│   │   │   └── Eye Direction과 Head Pose 기반 시선·고개 방향 분석
│   │   │
│   │   ├── gaze_state.py
│   │   │   └── 시험·응시자별 연속 시선 및 고개 이탈 상태 관리
│   │   │
│   │   ├── identity_monitor.py
│   │   │   └── 시험 중 기준 얼굴과 현재 얼굴 비교
│   │   │
│   │   ├── rule_engine.py
│   │   │   └── 얼굴·시선·고개·동일인·객체 탐지 결과 평가 및
│   │   │       Severity·Decision 결정
│   │   │
│   │   ├── event_engine.py
│   │   │   └── Rule 결과를 event_summary와 events 응답 구조로 변환
│   │   │
│   │   └── service.py
│   │       └── 시험 중 프레임 분석 전체 흐름 관리
│   │           DetectFaces 결과를 얼굴 및 시선 분석에서 재사용하고
│   │           DetectLabels 결과를 시험 중 객체 탐지에 활용
│   │
│   └── common/
│       ├── exceptions.py
│       │   └── 본인 인증, 모니터링, 이어폰 탐지, 시선 상태 및
│       │       AWS Rekognition 공통 예외 정의
│       │
│       └── image_validation.py
│           └── 전달받은 이미지 bytes 공통 검증
│
├── scripts/
│   ├── run_identity_verification.py
│   │   └── 로컬 이미지 기반 본인 인증 테스트
│   │
│   ├── run_earphone_detection.py
│   │   └── 로컬 귀 이미지 기반 이어폰 탐지 테스트
│   │
│   ├── run_gaze_monitor.py
│   │   └── 로컬 이미지 기반 시선·고개 방향 및 연속 상태 단독 테스트
│   │
│   └── run_monitoring.py
│       └── 이미지 폴더 기반 얼굴·시선·고개·객체 탐지
│           전체 모니터링 통합 테스트 및 JSON 결과 저장
│
│
├── requirements.txt
├── .env.example
│   └── AWS 설정 및 얼굴·이어폰·휴대폰·시선·고개 방향 Threshold 예시
│
├── .gitignore
└── README.md
```


---

# 2. 주요 기능

## 시험 시작 전 본인 인증

* 신분증 또는 수험표 이미지 입력
* 시험 시작 전 웹캠 캡처 이미지 입력
* AWS Rekognition CompareFaces 호출
* 두 이미지의 얼굴 유사도 비교
* 설정된 Threshold를 기준으로 본인 여부 판단
* 본인 인증 결과 반환 및 JSON 로그 저장
* 신분증과 사전 입력 정보 비교 → 논의 필요

## 시험 시작 전 이어폰 탐지

* 응시자의 왼쪽 귀 이미지 입력
* 응시자의 오른쪽 귀 이미지 입력
* 입력 이미지 형식 및 크기 검증
* AWS Rekognition DetectLabels 호출
* Earbuds, Headphones 등 이어폰 관련 Label 분석
* 설정된 Threshold를 기준으로 이어폰 탐지 여부 판단
* 왼쪽 귀와 오른쪽 귀 검사 결과 반환
* 한쪽이라도 이어폰이 탐지되면 시험 시작 제한
* 탐지 결과와 재촬영 필요 여부 반환

## 시험 중 모니터링

* 시험 중 프레임 이미지 수신
* AWS Rekognition DetectFaces를 이용한 얼굴 검출
* 얼굴 화면 이탈 감지
* 다중 인원 감지
* Eye Direction과 Head Pose 기반 시선 및 고개 방향 분석
* 시험·응시자별 연속 시선 및 고개 이탈 상태 관리
* 필요한 시점에 기준 얼굴과 현재 얼굴을 비교하여 동일인 여부 확인
* AWS Rekognition DetectLabels를 이용한 시험 중 객체 탐지
* Mobile Phone Label과 설정된 Threshold를 기준으로 휴대폰 탐지
* Head Pose 조건을 만족하는 경우 Earbuds, Headphones Label을 추가 분석하여 시험 중 이어폰 탐지
* 얼굴·시선·고개·동일인·객체 탐지 결과를 Rule Engine에서 평가
* 위험도 Severity 및 Decision 결정
* Event Engine을 이용한 event_summary 및 events 응답 생성
* 모니터링 결과 JSON 로그 저장


---

# 3. 개발 환경 및 구성

## 환경

- Python 3.11
- FastAPI
- Uvicorn
- Boto3
- AWS Rekognition
- python-dotenv
- python-multipart

## 구성
프로젝트의 anti-cheat 디렉토리로 이동합니다.


cd anti-cheat
Python 버전 확인
python3 --version


권장 버전: Python 3.11

가상환경 생성
`python3.11 -m venv face_api`

Python 명령이 python으로 등록되어 있다면 다음과 같이 실행할 수 있습니다.
`python -m venv face_api`

- macOS / Linux 활성화
`source face_api/bin/activate`

- Windows Git Bash 활성화
`source face_api/Scripts/activate`

- Windows PowerShell 활성화
`face_api\Scripts\Activate.ps1`

정상적으로 활성화되면 터미널 앞에 가상환경 이름이 표시됩니다.
(face_api)

가상환경 종료
deactivate

requirements.txt에는 프로젝트 실행에 필요한 Python 패키지와 버전이 기록되어 있습니다.

가상환경이 활성화된 상태에서 실행합니다.
```
pip install --upgrade pip
pip install -r requirements.txt

설치 여부 확인
pip list
```
---

# 4. .env
.env 파일에는 AWS Rekognition API를 호출하기 위한 AWS 자격 증명을 작성합니다.
.env.example 파일을 수정하여 사용하면 됩니다.
또한 로컬에서 실행하기 위해 AWS 자격 증명이 필요하다면 DM주시면 보내드리겠습니다.

**AWS Access Key와 Secret Access Key는 비밀번호와 같은 민감 정보이므로 다음 위치에는 작성하지 않습니다.**
- GitHub 저장소
- README
- .env.example
- Python 코드
- 공유 문서
- 메신저 공개 채널

---

# 5. 로컬 테스트 준비
## 본인 인증
현재는 웹에서 이미지를 전달받는 구조가 완성되지 않았으므로, 로컬 이미지 파일을 사용해 기능을 테스트 합니다.

본인 인증 테스트에는 다음 이미지가 필요합니다.

- 기준 이미지
    - 신분증
    - 여권
    - 수험표 등

- 비교 이미지
    - 시험 시작 전 웹캠 캡처 이미지
    - 기준 이미지와 동일한 사람의 얼굴 이미지
    - 타인의 얼굴 이미지
    - 얼굴이 없는 이미지

**실제 신분증, 여권 및 개인정보가 포함된 이미지는 GitHub에 업로드하지 않습니다.**

예시:
```
anti-cheat/
└── data/
    ├── compare/
    │   ├── source.jpg
    │   ├── same_person.jpg
    │   ├── different_person.jpg
    │   └── no_face.jpg
    │       
    └── logs/
```    
이미지 확장자 형식은 jpg, jpeg, png 등이 가능합니다.

로컬 테스트 이미지 경로는 run_identity_verification.py의 설정과 일치해야 합니다.

### 실행
1. 가상환경을 활성화합니다.
`source face_api/bin/activate`

2. anti-cheat 디렉토리에서 실행합니다.
`python scripts/run_identity_verification.py`

### 실행 결과
상적으로 실행되면 다음 항목을 확인할 수 있습니다.

- AWS Rekognition 연결 여부
- 기준 이미지와 비교 이미지의 얼굴 검출 여부
- 얼굴 유사도(Similarity)
- 본인 인증 성공 여부
- 예외 처리 결과
    - 얼굴이 없는 이미지
    - 얼굴이 검출되지 않는 이미지
    - 입력 이미지 오류

## 시험 시작 전 이어폰 탐지
현재는 웹에서 귀 이미지를 전달받는 구조가 완성되지 않았으므로, 로컬 이미지 파일을 사용해 기능을 테스트합니다.

이어폰 탐지 테스트에는 다음 이미지가 필요합니다.

- 왼쪽 귀 이미지
    - 이어폰을 착용하지 않은 이미지
    - 유선 이어폰을 착용한 이미지
    - 무선 이어폰을 착용한 이미지
    - 귀가 제대로 보이지 않는 이미지
- 오른쪽 귀 이미지
    - 이어폰을 착용하지 않은 이미지
    - 유선 이어폰을 착용한 이미지
    - 무선 이어폰을 착용한 이미지
    - 귀가 제대로 보이지 않는 이미지

실제 응시자의 얼굴 및 개인정보가 포함된 이미지는 GitHub에 업로드하지 않습니다.

예시:
```
anti-cheat/
└── data/
    ├── earphone/
    │   ├── left_ear.jpg
    │   └── right_ear.jpg
    │
    └── logs/
```

이미지 확장자 형식은 jpg, jpeg, png 등이 가능합니다.

로컬 테스트 이미지 경로는 run_earphone_detection.py의 설정과 일치해야 합니다.

### 실행
1. 가상환경을 활성화합니다.
`source face_api/bin/activate`

2. anti-cheat 디렉토리에서 실행합니다.
`python scripts/run_earphone_detection.py`

### 실행 결과

정상적으로 실행되면 다음 항목을 확인할 수 있습니다.

- 왼쪽 귀 이미지 검증 결과
- 오른쪽 귀 이미지 검증 결과
- AWS Rekognition DetectLabels 호출 결과
- 탐지된 이어폰 관련 Label
- 탐지 confidence
- 적용된 Threshold
- 왼쪽 귀 이어폰 탐지 여부
- 오른쪽 귀 이어폰 탐지 여부
- 재촬영 필요 여부
- 최종 시험 시작 가능 여부

## 시험 모니터링
현재는 웹에서 이미지를 전달받는 구조가 완성되지 않았으므로, 로컬 이미지 파일을 사용해 기능을 테스트 합니다.

시험 모니터링 테스트에는 다음 이미지가 필요합니다.

- 정상 이미지
    - 응시자 1명의 얼굴이 화면 안에 정상적으로 보이는 이미지
- 얼굴 이탈 이미지
- 얼굴이 화면 밖으로 일부 또는 전체 이탈한 이미지
- 얼굴이 검출되지 않는 이미지
- 다중 인원 이미지
- 2명 이상의 얼굴이 검출되는 이미지
- 중간 본인 인증 이미지
    - 시험 시작 전 기준 얼굴 이미지와 동일한 사람의 이미지
    - 기준 얼굴 이미지와 다른 사람의 이미지

**실제 응시자의 얼굴 이미지 및 개인정보가 포함된 이미지는 GitHub에 업로드하지 않습니다.**

예시:
```
anti-cheat/
└── data/
    ├── compare/
    │   └── source.jpg
    │
    ├── monitoring/
    │   ├── normal.jpg
    │   ├── face_out_of_frame.jpg
    │   ├── multiple_faces.jpg
    │   ├── same_person.jpg
    │   └── different_person.jpg
    │
    └── logs/
        └── exam_001/
```
이미지 확장자 형식은 jpg, jpeg, png 등이 가능합니다.

로컬 테스트 이미지 경로는 run_monitoring.py의 설정과 일치해야 합니다.
중간 본인 인증을 함께 테스트하는 경우에는 시험 시작 전 본인 인증에 사용한 기준 얼굴 이미지가 필요합니다.

모니터링 결과 로그를 저장하려면 다음과 같이 시험별 로그 디렉토리가 미리 존재해야 합니다.
현재 로컬 테스트에서는 모니터링 이벤트 JSON 저장을 확인하기 위해 data/logs/{exam_id} 디렉토리를 사용합니다.

이 디렉토리 구조는 로컬 테스트를 위한 임시 저장 방식이며, 실제 웹 서비스에서는 AI 서버가 모니터링 요청을 분석한 뒤 결과를 JSON으로 반환합니다.

### 실행
1. 가상환경을 활성화합니다.
`source face_api/bin/activate`

2. anti-cheat 디렉토리에서 실행합니다.
`python scripts/run_monitoring.py`

### 실행 결과
- 얼굴 검출 결과
- 얼굴 수
- 얼굴 화면 이탈 여부
- 다중 인원 여부
- 중간 본인 인증 결과
- Rule Engine 위험도
- Decision 결과
- 이벤트 생성 여부
- 이벤트 JSON 로그 저장 여부

---

# 6. 보안 주의 사항
다음 정보는 어떠한 경우에도 GitHub에 커밋하지 않습니다.
- AWS Access Key ID
- AWS Secret Access Key
- AWS Session Token
- .env
- ~/.aws/credentials
- 실제 신분증 및 여권 이미지
- 실제 응시자 웹캠 이미지
- 개인정보가 포함된 로그
- 운영 서버 자격 증명

`AWS 키가 실수로 GitHub에 올라간 경우 바로 공유 부탁드립니다.`
