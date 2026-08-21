# 부정행위 탐지 서버를 어디서든 똑같이 조립하기 위한 설명서.
#
# 이 파일이 하는 일을 순서대로 읽으면:
#   파이썬 깔린 상자를 가져와서 → 필요한 패키지를 설치하고
#   → 우리 코드를 넣고 → 서버를 켠다.
# Cloud Run 이든 다른 어디든, 이 설명서대로 조립하면 같은 서버가 나온다.
#
# 로컬에 Docker 가 없어도 된다. 배포할 때 구글이 서버에서 대신 조립한다:
#   gcloud run deploy ktest-anti-cheat --source anti-cheat/

# slim: 필요 최소한만 든 가벼운 파이썬. AWS Rekognition은 API 호출만 하므로
# 무거운 컴퓨터비전 라이브러리(opencv 등)가 없어 컴파일러가 든 이미지가 필요 없다.
FROM python:3.13-slim

# 파이썬이 로그를 모아 뒀다 내보내지 않고 바로 찍게 한다.
# 이게 없으면 서버가 죽었을 때 마지막 로그가 사라져 원인을 못 찾는다
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# 패키지 목록을 코드보다 먼저 복사하는 이유:
# Docker 는 바뀐 줄부터만 다시 조립한다. 코드는 자주 바뀌지만 패키지 목록은
# 가끔 바뀌므로, 이 순서면 코드만 고쳤을 때 패키지 재설치(수 분)를 건너뛴다
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 서버 코드. app이 modules를 가져다 쓰므로 둘 다 넣는다.
# 서버 실행에 필요 없는 것(테스트·스크립트)은 .dockerignore가 걸러 준다 —
# 특히 .env(AWS 키)는 절대 상자에 넣지 않는다
COPY app ./app
COPY modules ./modules

# Cloud Run 은 PORT 환경변수로 몇 번 문에서 손님을 받을지 알려 준다.
# 로컬에서 직접 돌릴 때는 그 값이 없으므로 8080 을 기본값으로 쓴다.
# (셸 형식을 쓰는 이유: ${PORT} 환경변수 치환이 exec 형식에서는 안 된다)
CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}
