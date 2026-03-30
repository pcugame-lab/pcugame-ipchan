FROM python:3.12-slim

WORKDIR /app

# 의존성 먼저 설치 (레이어 캐시 활용)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 복사
COPY app/ app/

# non-root 사용자 생성
RUN groupadd -g 1000 labipbot \
    && useradd -u 1000 -g 1000 -m -s /bin/bash labipbot \
    && mkdir -p data logs \
    && chown -R labipbot:labipbot /app

USER labipbot

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD pgrep -f "python -m app.main" || exit 1

CMD ["python", "-m", "app.main"]
