from .node import (
    SAM2ModelLoader,
    GroundingDinoModelLoader,
    GroundingDinoSAM2Segment,
    SAM2PointSegment,
    InvertMask,
    IsMaskEmptyNode,
)

NODE_CLASS_MAPPINGS = {
    "SAM2ModelLoader (segment anything2)": SAM2ModelLoader,
    "GroundingDinoModelLoader (segment anything2)": GroundingDinoModelLoader,
    "GroundingDinoSAM2Segment (segment anything2)": GroundingDinoSAM2Segment,
    "SAM2PointSegment (segment anything2)": SAM2PointSegment,
    "InvertMask (segment anything)": InvertMask,
    "IsMaskEmpty": IsMaskEmptyNode,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SAM2ModelLoader": "SAM2 Model Loader",
    "GroundingDinoModelLoader": "Grounding Dino Model Loader",
    "GroundingDinoSAM2Segment": "Grounding Dino SAM2 Segment",
    "SAM2PointSegment (segment anything2)": "SAM2 Point Segment (click selection)",
    "InvertMask": "Invert Mask",
    "IsMaskEmpty": "Is Mask Empty",
}
