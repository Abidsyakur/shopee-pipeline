FROM apache/airflow:2.9.1-python3.8

USER root

RUN apt-get update && apt-get install -y \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libgtk-3-0 \
    libnss3 \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdrm2 \
    libxkbcommon0 \
    libxshmfence1 \
    libxinerama1 \
    libxcursor1 \
    fonts-liberation \
    wget \
    curl \
    unzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER airflow

COPY requirements.txt .

# Fix 1: playwright==1.44.0 supaya kompatibel dengan Python 3.8
RUN pip install --no-cache-dir -r requirements.txt

# Install browser Chromium untuk Playwright
RUN playwright install chromium