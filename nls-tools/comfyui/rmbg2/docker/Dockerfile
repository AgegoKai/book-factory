FROM pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime@sha256:1f57418aedd9a4d0d3a59646619e1d4f82cacc33817247cead4f749e1f452d4b

ARG COMFYUI_COMMIT=5087f1d497c5b615fbb5d1ff03fcc1df308bd025
ARG RMBG_NODE_COMMIT=615c1146d649bf7d720817a540e0b358466f0558
ARG COMFYUI_REPOSITORY=https://github.com/Comfy-Org/ComfyUI.git
ARG COMFYUI_REPOSITORY_MIRROR=
ARG RMBG_REPOSITORY=https://github.com/1038lab/ComfyUI-RMBG.git
ARG RMBG_REPOSITORY_MIRROR=

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/workspace/cache/huggingface

LABEL org.opencontainers.image.title="NJS RMBG-2.0 background removal worker" \
      io.njs.ai.comfyui.commit="${COMFYUI_COMMIT}" \
      io.njs.ai.rmbg-node.commit="${RMBG_NODE_COMMIT}" \
      io.njs.ai.workflow.version="1.0.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY docker/fetch-git-source.sh /usr/local/bin/fetch-git-source
RUN chmod +x /usr/local/bin/fetch-git-source \
    && fetch-git-source /workspace/ComfyUI "${COMFYUI_COMMIT}" "${COMFYUI_REPOSITORY}" "${COMFYUI_REPOSITORY_MIRROR}" \
    && cd /workspace/ComfyUI \
    && pip install -r requirements.txt

RUN fetch-git-source /workspace/ComfyUI/custom_nodes/ComfyUI-RMBG "${RMBG_NODE_COMMIT}" "${RMBG_REPOSITORY}" "${RMBG_REPOSITORY_MIRROR}" \
    && cd /workspace/ComfyUI/custom_nodes/ComfyUI-RMBG \
    && pip install \
        "huggingface-hub==0.36.2" \
        "kornia==0.8.3" \
        "numpy==2.4.1" \
        "opencv-python-headless==5.0.0.93" \
        "safetensors==0.8.0" \
        "timm==1.0.28" \
        "transformers==4.57.6"

RUN pip uninstall --yes spin \
    && pip check

ENV HF_HUB_DISABLE_XET=1 \
    HF_HUB_DOWNLOAD_TIMEOUT=900

RUN mkdir -p /opt/default-workflows /opt/default-input /workspace/cache/huggingface

COPY ["workflows/RemoveBg_by_RMBG2.json", "/opt/default-workflows/RemoveBg by RMBG-2.0.json"]
COPY ["workflows/RemoveBg_by_RMBG2_API.json", "/opt/default-workflows/RemoveBg by RMBG-2.0 API.json"]
COPY workflows/workflow-manifest.json /opt/default-workflows/rmbg2-remove-background.manifest.json
COPY ["examples/RMBG2_bear_edge_test.png", "/opt/default-input/RMBG2_bear_edge_test.png"]
COPY docker/entrypoint.sh /usr/local/bin/rmbg-entrypoint
COPY docker/healthcheck.py /usr/local/bin/worker-healthcheck
RUN chmod +x /usr/local/bin/rmbg-entrypoint /usr/local/bin/worker-healthcheck

WORKDIR /workspace/ComfyUI
EXPOSE 8189

ENTRYPOINT ["/usr/local/bin/rmbg-entrypoint"]
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8189", "--disable-pinned-memory", "--disable-async-offload"]
