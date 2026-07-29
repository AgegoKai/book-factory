FROM pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime@sha256:1f57418aedd9a4d0d3a59646619e1d4f82cacc33817247cead4f749e1f452d4b

ARG COMFYUI_COMMIT=5087f1d497c5b615fbb5d1ff03fcc1df308bd025
ARG RMBG_NODE_COMMIT=615c1146d649bf7d720817a540e0b358466f0558

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/workspace/cache/huggingface

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

RUN git clone https://github.com/Comfy-Org/ComfyUI.git \
    && cd ComfyUI \
    && git checkout "${COMFYUI_COMMIT}" \
    && pip install -r requirements.txt

RUN git clone https://github.com/1038lab/ComfyUI-RMBG.git ComfyUI/custom_nodes/ComfyUI-RMBG \
    && cd ComfyUI/custom_nodes/ComfyUI-RMBG \
    && git checkout "${RMBG_NODE_COMMIT}" \
    && pip install \
        "huggingface-hub>=0.24" \
        "transformers>=4.49,<5" \
        "opencv-python-headless>=4.10" \
        "timm>=1.0" \
        "kornia>=0.7" \
        safetensors

ENV HF_HUB_DISABLE_XET=1 \
    HF_HUB_DOWNLOAD_TIMEOUT=900

RUN mkdir -p /opt/default-workflows /opt/default-input /workspace/cache/huggingface

COPY ["workflows/RemoveBg_by_RMBG2.json", "/opt/default-workflows/RemoveBg by RMBG-2.0.json"]
COPY ["workflows/RemoveBg_by_RMBG2_API.json", "/opt/default-workflows/RemoveBg by RMBG-2.0 API.json"]
COPY ["examples/RMBG2_bear_edge_test.png", "/opt/default-input/RMBG2_bear_edge_test.png"]
COPY docker/entrypoint.sh /usr/local/bin/rmbg-entrypoint
RUN chmod +x /usr/local/bin/rmbg-entrypoint

WORKDIR /workspace/ComfyUI
EXPOSE 8189

ENTRYPOINT ["/usr/local/bin/rmbg-entrypoint"]
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8189", "--disable-pinned-memory", "--disable-async-offload"]
