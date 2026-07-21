FROM pytorch/pytorch:2.10.0-cuda13.0-cudnn9-runtime@sha256:1f57418aedd9a4d0d3a59646619e1d4f82cacc33817247cead4f749e1f452d4b

ARG COMFYUI_COMMIT=5087f1d497c5b615fbb5d1ff03fcc1df308bd025
ARG KJNODES_COMMIT=e27a505b3ba6ce42687fe00500deda103d9d6071
ARG SAM2_COMMIT=e75eabcc12efd4aa9b5c6f72274d759973d36d4d

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

RUN git clone https://github.com/kijai/ComfyUI-KJNodes.git ComfyUI/custom_nodes/ComfyUI-KJNodes \
    && cd ComfyUI/custom_nodes/ComfyUI-KJNodes \
    && git checkout "${KJNODES_COMMIT}" \
    && pip install -r requirements.txt

RUN git clone https://github.com/neverbiasu/ComfyUI-SAM2.git ComfyUI/custom_nodes/comfyui-sam2 \
    && cd ComfyUI/custom_nodes/comfyui-sam2 \
    && git checkout "${SAM2_COMMIT}" \
    && pip install -r requirements.txt \
    && pip install "numpy>=2,<2.8"

# Local click-selection and professional edge-matting patches.
COPY comfyui_sam2_node.py /workspace/ComfyUI/custom_nodes/comfyui-sam2/node.py
COPY comfyui_sam2_init.py /workspace/ComfyUI/custom_nodes/comfyui-sam2/__init__.py
COPY kjnodes_curve_nodes.py /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes/nodes/curve_nodes.py
COPY kjnodes_point_editor_canvas.js /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes/web/js/editors/point_editor_canvas.js
COPY kjnodes_editor_base.js /workspace/ComfyUI/custom_nodes/ComfyUI-KJNodes/web/js/editors/editor_base.js

RUN mkdir -p /opt/default-workflows /workspace/cache/huggingface \
    && python -m py_compile /workspace/ComfyUI/custom_nodes/comfyui-sam2/node.py

COPY ["RemoveBg_by_SAM2.json", "/opt/default-workflows/RemoveBg by SAM2.json"]
COPY ["examples/SAM2_bear_edge_test.png", "/opt/default-input/SAM2_bear_edge_test.png"]
COPY docker-sam2/entrypoint.sh /usr/local/bin/sam2-entrypoint
RUN chmod +x /usr/local/bin/sam2-entrypoint

WORKDIR /workspace/ComfyUI
EXPOSE 8188

ENTRYPOINT ["/usr/local/bin/sam2-entrypoint"]
CMD ["python", "main.py", "--listen", "0.0.0.0", "--port", "8188", "--disable-pinned-memory", "--disable-async-offload"]
