FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 NODE_ENV=production
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs npm chromium fonts-liberation \
    libnss3 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt whatsapp/package.json ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
    && PUPPETEER_SKIP_DOWNLOAD=true npm install --prefix whatsapp \
    && useradd --uid 10001 --create-home platform
COPY --chown=platform:platform . .
USER platform
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log", "--no-proxy-headers"]