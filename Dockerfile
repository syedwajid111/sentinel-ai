# Sentinel AI — container for Hugging Face Spaces (Docker SDK) or any Docker host
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Karachi \
    SENTINEL_CLOUD=1 \
    YOLO_CONFIG_DIR=/tmp/Ultralytics \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false

# OpenCV runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 tzdata \
    && rm -rf /var/lib/apt/lists/*

# Hugging Face runs containers as user 1000
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
RUN mkdir -p data/snapshots data/recordings models && chown -R user:user /home/user/app

USER user
EXPOSE 7860
CMD ["streamlit", "run", "app.py", \
     "--server.port=7860", "--server.address=0.0.0.0", \
     "--server.headless=true", "--server.maxUploadSize=200", \
     "--server.enableXsrfProtection=false", "--server.enableCORS=false"]
