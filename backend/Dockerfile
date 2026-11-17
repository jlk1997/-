FROM python:3.11-slim

WORKDIR /app

# 国内网络构建时默认走清华源；海外可 build-arg PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10

RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
      sed -i \
        -e 's|deb.debian.org|mirrors.tencentyun.com|g' \
        -e 's|security.debian.org|mirrors.tencentyun.com|g' \
        /etc/apt/sources.list.d/debian.sources; \
    fi \
    && apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg libsndfile1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/backend/requirements.txt
COPY backend/requirements-stems.txt /app/backend/requirements-stems.txt

RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --retries 10 --timeout 600 \
    -i "${PIP_INDEX_URL}" -r /app/backend/requirements.txt

ARG INSTALL_DEMUCS=false
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu
RUN if [ "$INSTALL_DEMUCS" = "true" ]; then \
      pip install --no-cache-dir --retries 10 --timeout 600 torch --index-url "${TORCH_INDEX_URL}" && \
      pip install --no-cache-dir --retries 10 --timeout 600 \
      -i "${PIP_INDEX_URL}" --extra-index-url "${TORCH_INDEX_URL}" \
      -r /app/backend/requirements-stems.txt; \
    fi

ARG INSTALL_PLAYWRIGHT=false
COPY backend/requirements-farm.txt /app/backend/requirements-farm.txt
RUN if [ "$INSTALL_PLAYWRIGHT" = "true" ]; then \
      pip install --no-cache-dir --retries 10 --timeout 600 \
      -i "${PIP_INDEX_URL}" -r /app/backend/requirements-farm.txt && \
      playwright install --with-deps chromium; \
    fi

COPY backend /app/backend
COPY src /app/src
COPY docs/legal /app/docs/legal
COPY packages/dsp-playbooks /app/packages/dsp-playbooks
COPY apps/browser-farm /app/apps/browser-farm

ENV PYTHONPATH=/app:/app/backend
WORKDIR /app/backend

EXPOSE 8000
