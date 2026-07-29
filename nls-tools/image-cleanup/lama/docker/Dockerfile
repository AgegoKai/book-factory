FROM pytorch/pytorch@sha256:1f57418aedd9a4d0d3a59646619e1d4f82cacc33817247cead4f749e1f452d4b

ARG IOPAINT_VERSION=1.6.0

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/data/models/huggingface \
    HF_HUB_DISABLE_XET=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# PyTorch z obrazu bazowego obsługuje RTX 50xx (CUDA 13.0). IOPaint dostarcza
# panel z pędzlem i uruchamia właściwy model LaMa.
RUN python -m pip install --upgrade pip \
    && python -m pip install "iopaint==${IOPAINT_VERSION}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

COPY docker/entrypoint.sh /usr/local/bin/lama-cleanup
RUN chmod +x /usr/local/bin/lama-cleanup \
    && mkdir -p /data/models /data/input /data/output

EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/lama-cleanup"]
