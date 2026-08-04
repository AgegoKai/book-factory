FROM pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime@sha256:1f57418aedd9a4d0d3a59646619e1d4f82cacc33817247cead4f749e1f452d4b

ARG COMFYUI_COMMIT=5087f1d497c5b615fbb5d1ff03fcc1df308bd025
ARG KJNODES_COMMIT=e27a505b3ba6ce42687fe00500deda103d9d6071
ARG SAM2_COMMIT=e75eabcc12efd4aa9b5c6f72274d759973d36d4d
ARG COMFYUI_REPOSITORY=https://github.com/Comfy-Org/ComfyUI.git
ARG COMFYUI_REPOSITORY_MIRROR=
ARG KJNODES_REPOSITORY=https://github.com/kijai/ComfyUI-KJNodes.git
ARG KJNODES_REPOSITORY_MIRROR=
ARG SAM2_REPOSITORY=https://github.com/neverbiasu/ComfyUI-SAM2.git
ARG SAM2_REPOSITORY_MIRROR=

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_BREAK_SYSTEM_PACKAGES=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/workspace/cache/huggingface

LABEL org.opencontainers.image.title="NJS SAM2 point segmentation worker" \
      io.njs.ai.comfyui.commit="${COMFYUI_COMMIT}" \
      io.njs.ai.kjnodes.commit="${KJNODES_COMMIT}" \
      io.njs.ai.sam2-node.commit="${SAM2_COMMIT}" \
      io.njs.ai.workflow.version="1.0.0"

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates git libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

COPY docker-sam2/fetch-git-source.sh /usr/local/bin/fetch-git-source
RUN chmod +x /usr/local/bin/fetch-git-source \
    && fetch-git-source /workspace/ComfyUI "${COMFYUI_COMMIT}" "${COMFYUI_REPOSITORY}" "${COMFYUI_REPOSITORY_MIRROR}" \
    && cd /workspace/ComfyUI \
    && pip install -r requirements.txt

RUN fetch-git-source /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes "${KJNODES_COMMIT}" "${KJNODES_REPOSITORY}" "${KJNODES_REPOSITORY_MIRROR}" \
    && cd /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes \
    && pip install -r requirements.txt

RUN fetch-git-source /workspace/ComfyUI/custom_nodes/comfyui-sam2 "${SAM2_COMMIT}" "${SAM2_REPOSITORY}" "${SAM2_REPOSITORY_MIRROR}" \
    && cd /workspace/ComfyUI/custom_nodes/comfyui-sam2 \
    && pip install -r requirements.txt \
    && pip install \
        "huggingface-hub==1.24.0" \
        "kornia==0.8.3" \
        "numpy==2.5.1" \
        "opencv-python-headless==5.0.0.93" \
        "safetensors==0.8.0" \
        "timm==1.0.28" \
        "transformers==5.14.1"

RUN pip uninstall --yes spin \
    && pip check

# Local click-selection and professional edge-matting patches.
COPY comfyui_sam2_node.py /workspace/ComfyUI/custom_nodes/comfyui-sam2/node.py
COPY comfyui_sam2_init.py /workspace/ComfyUI/custom_nodes/comfyui-sam2/__init__.py
COPY kjnodes_curve_nodes.py /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes/nodes/curve_nodes.py
COPY kjnodes_point_editor_canvas.js /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes/web/js/editors/point_editor_canvas.js
COPY kjnodes_editor_base.js /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes/web/js/editors/editor_base.js

RUN mkdir -p /opt/default-workflows /workspace/cache/huggingface \
    && python -m py_compile /workspace/ComfyUI/custom_nodes/comfyui-sam2/node.py

COPY ["RemoveBg_by_SAM2.json", "/opt/default-workflows/RemoveBg by SAM2.json"]
COPY docker-sam2/workflow-manifest.json /opt/default-workflows/sam2-point-segmentation.manifest.json
COPY ["examples/SAM2_bear_edge_test.png", "/opt/default-input/SAM2_bear_edge_test.png"]
COPY docker-sam2/entrypoint.sh /usr/local/bin/sam2-entrypoint
COPY docker-sam2/healthcheck.py /usr/local/bin/worker-healthcheck
RUN chmod +x /usr/local/bin/sam2-entrypoint /usr/local/bin/worker-healthcheck

WORKDIR /workspace/ComfyUI
EXPOSE 8188

ENTRYPOINT ["/usr/local/bin/sam2-entrypoint"]
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-pinned-memory", "--disable-async-offload"]
