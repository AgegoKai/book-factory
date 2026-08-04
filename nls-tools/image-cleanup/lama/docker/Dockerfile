FROM pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime@sha256:1f57418aedd9a4d0d3a59646619e1d4f82cacc33817247cead4f749e1f452d4b

ARG IOPAINT_VERSION=1.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/root/.cache/huggingface \
    HF_HUB_DISABLE_XET=1

LABEL org.opencontainers.image.title="NJS LaMa cleanup worker" \
      io.njs.ai.iopaint.version="${IOPAINT_VERSION}" \
      io.njs.ai.worker.version="1.1.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY docker/requirements.constraints.txt /tmp/requirements.constraints.txt
RUN python -m pip install --upgrade "pip==26.1.2" \
    && python -m pip install \
        --constraint /tmp/requirements.constraints.txt \
        "iopaint==${IOPAINT_VERSION}" \
    && python -m pip check \
    && rm -f /tmp/requirements.constraints.txt

COPY docker/entrypoint.sh /usr/local/bin/lama-cleanup
COPY docker/healthcheck.py /usr/local/bin/worker-healthcheck
COPY worker-manifest.json /opt/njs-ai/lama-worker.manifest.json
RUN chmod +x /usr/local/bin/lama-cleanup /usr/local/bin/worker-healthcheck \
    && mkdir -p /data/models /data/input /data/output /root/.cache /root/.config

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/lama-cleanup"]
