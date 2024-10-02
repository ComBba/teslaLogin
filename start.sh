#!/bin/bash

# .env.local 파일에서 환경 변수 로드
if [ -f .env.local ]; then
    export $(grep -v '^#' .env.local | xargs)
else
    echo ".env.local 파일이 존재하지 않습니다."
    exit 1
fi

# 가상 환경 활성화
if [ -d venv ]; then
    source venv/bin/activate
else
    python3 -m venv venv
    source venv/bin/activate
fi

# 필요한 패키지 설치
pip install -r requirements.txt

# Flask 애플리케이션 실행
flask run --host=0.0.0.0 --port=3003
