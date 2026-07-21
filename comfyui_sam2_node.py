import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import copy
import json
import torch
import torch.nn.functional as F
import numpy as np
from PIL import Image
import logging
from torch.hub import download_url_to_file
from urllib.parse import urlparse
import folder_paths
import comfy.model_management
from sam2.build_sam import build_sam2
from sam2.sam2_image_predictor import SAM2ImagePredictor
from local_groundingdino.datasets import transforms as T
from local_groundingdino.util.utils import (
    clean_state_dict as local_groundingdino_clean_state_dict,
)
from local_groundingdino.util.slconfig import SLConfig as local_groundingdino_SLConfig
from local_groundingdino.models import build_model as local_groundingdino_build_model
import glob
import folder_paths
from hydra import initialize
from hydra.core.global_hydra import GlobalHydra

logger = logging.getLogger("ComfyUI-SAM2")

sam_model_dir_name = "sam2"
sam_model_list = {
    "sam2_hiera_tiny": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_tiny.pt"
    },
    "sam2_hiera_small.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_small.pt"
    },
    "sam2_hiera_base_plus.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_base_plus.pt"
    },
    "sam2_hiera_large.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/072824/sam2_hiera_large.pt"
    },
    "sam2_1_hiera_tiny.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_tiny.pt"
    },
    "sam2_1_hiera_small.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_small.pt"
    },
    "sam2_1_hiera_base_plus.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_base_plus.pt"
    },
    "sam2_1_hiera_large.pt": {
        "model_url": "https://dl.fbaipublicfiles.com/segment_anything_2/092824/sam2.1_hiera_large.pt"
    },
}

groundingdino_model_dir_name = "grounding-dino"
groundingdino_model_list = {
    "GroundingDINO_SwinT_OGC (694MB)": {
        "config_url": "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/GroundingDINO_SwinT_OGC.cfg.py",
        "model_url": "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swint_ogc.pth",
    },
    "GroundingDINO_SwinB (938MB)": {
        "config_url": "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/GroundingDINO_SwinB.cfg.py",
        "model_url": "https://huggingface.co/ShilongLiu/GroundingDINO/resolve/main/groundingdino_swinb_cogcoor.pth",
    },
}


def get_bert_base_uncased_model_path():
    comfy_bert_model_base = os.path.join(folder_paths.models_dir, "bert-base-uncased")
    if glob.glob(
        os.path.join(comfy_bert_model_base, "**/model.safetensors"), recursive=True
    ):
        print("grounding-dino is using models/bert-base-uncased")
        return comfy_bert_model_base
    return "bert-base-uncased"


def list_files(dirpath, extensions=[]):
    return [
        f
        for f in os.listdir(dirpath)
        if os.path.isfile(os.path.join(dirpath, f)) and f.split(".")[-1] in extensions
    ]


def list_sam_model():
    return list(sam_model_list.keys())


def load_sam_model(model_name):
    sam2_checkpoint_path = get_local_filepath(
        sam_model_list[model_name]["model_url"], sam_model_dir_name
    )
    model_file_name = os.path.basename(sam2_checkpoint_path)
    model_file_name = model_file_name.replace("2.1", "2_1")
    model_type = model_file_name.split(".")[0]

    if GlobalHydra().is_initialized():
        GlobalHydra.instance().clear()

    config_path = "sam2_configs"
    initialize(config_path=config_path)
    model_cfg = f"{model_type}.yaml"

    sam_device = comfy.model_management.get_torch_device()
    sam = build_sam2(model_cfg, sam2_checkpoint_path, device=sam_device)
    sam.model_name = model_file_name
    return sam


def get_local_filepath(url, dirname, local_file_name=None):
    if not local_file_name:
        parsed_url = urlparse(url)
        local_file_name = os.path.basename(parsed_url.path)

    destination = folder_paths.get_full_path(dirname, local_file_name)
    if destination:
        logger.warn(f"using extra model: {destination}")
        return destination

    folder = os.path.join(folder_paths.models_dir, dirname)
    if not os.path.exists(folder):
        os.makedirs(folder)

    destination = os.path.join(folder, local_file_name)
    if not os.path.exists(destination):
        logger.warn(f"downloading {url} to {destination}")
        download_url_to_file(url, destination)
    return destination


def load_groundingdino_model(model_name):
    dino_model_args = local_groundingdino_SLConfig.fromfile(
        get_local_filepath(
            groundingdino_model_list[model_name]["config_url"],
            groundingdino_model_dir_name,
        ),
    )

    if dino_model_args.text_encoder_type == "bert-base-uncased":
        dino_model_args.text_encoder_type = get_bert_base_uncased_model_path()

    dino = local_groundingdino_build_model(dino_model_args)
    checkpoint = torch.load(
        get_local_filepath(
            groundingdino_model_list[model_name]["model_url"],
            groundingdino_model_dir_name,
        ),
        map_location="cpu",
        mmap=True,
        weights_only=True,
    )
    dino.load_state_dict(
        local_groundingdino_clean_state_dict(checkpoint["model"]),
        strict=False,
        assign=True,
    )
    device = comfy.model_management.get_torch_device()
    dino.to(device=device)
    dino.eval()
    return dino


def list_groundingdino_model():
    return list(groundingdino_model_list.keys())


def groundingdino_predict(dino_model, image, prompt, threshold):
    def load_dino_image(image_pil):
        transform = T.Compose(
            [
                T.RandomResize([800], max_size=1333),
                T.ToTensor(),
                T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
            ]
        )
        image, _ = transform(image_pil, None)  # 3, h, w
        return image

    def get_grounding_output(model, image, caption, box_threshold):
        caption = caption.lower()
        caption = caption.strip()
        if not caption.endswith("."):
            caption = caption + "."
        device = comfy.model_management.get_torch_device()
        image = image.to(device)
        with torch.no_grad():
            outputs = model(image[None], captions=[caption])
        logits = outputs["pred_logits"].sigmoid()[0]  # (nq, 256)
        boxes = outputs["pred_boxes"][0]  # (nq, 4)
        # filter output
        logits_filt = logits.clone()
        boxes_filt = boxes.clone()
        filt_mask = logits_filt.max(dim=1)[0] > box_threshold
        logits_filt = logits_filt[filt_mask]  # num_filt, 256
        boxes_filt = boxes_filt[filt_mask]  # num_filt, 4
        return boxes_filt.cpu()

    dino_image = load_dino_image(image.convert("RGB"))
    boxes_filt = get_grounding_output(dino_model, dino_image, prompt, threshold)
    H, W = image.size[1], image.size[0]
    for i in range(boxes_filt.size(0)):
        boxes_filt[i] = boxes_filt[i] * torch.Tensor([W, H, W, H])
        boxes_filt[i][:2] -= boxes_filt[i][2:] / 2
        boxes_filt[i][2:] += boxes_filt[i][:2]
    return boxes_filt


def create_pil_output(image_np, masks, boxes_filt):
    output_masks, output_images = [], []
    boxes_filt = boxes_filt.numpy().astype(int) if boxes_filt is not None else None
    for mask in masks:
        output_masks.append(Image.fromarray(np.any(mask, axis=0)))
        image_np_copy = copy.deepcopy(image_np)
        image_np_copy[~np.any(mask, axis=0)] = np.array([0, 0, 0, 0])
        output_images.append(Image.fromarray(image_np_copy))
    return output_images, output_masks


def create_tensor_output(image_np, masks, boxes_filt):
    output_masks, output_images = [], []
    boxes_filt = boxes_filt.numpy().astype(int) if boxes_filt is not None else None
    for mask in masks:
        image_np_copy = copy.deepcopy(image_np)
        image_np_copy[~np.any(mask, axis=0)] = np.array([0, 0, 0, 0])
        output_image, output_mask = split_image_mask(Image.fromarray(image_np_copy))
        output_masks.append(output_mask)
        output_images.append(output_image)
    return (output_images, output_masks)


def split_image_mask(image):
    image_rgb = image.convert("RGB")
    image_rgb = np.array(image_rgb).astype(np.float32) / 255.0
    image_rgb = torch.from_numpy(image_rgb)[None,]
    if "A" in image.getbands():
        mask = np.array(image.getchannel("A")).astype(np.float32) / 255.0
        mask = torch.from_numpy(mask)[None,]
    else:
        mask = torch.zeros((64, 64), dtype=torch.float32, device="cpu")
    return (image_rgb, mask)


def sam_segment(sam_model, image, boxes):
    if boxes.shape[0] == 0:
        return None
    predictor = SAM2ImagePredictor(sam_model)
    image_np = np.array(image)
    image_np_rgb = image_np[..., :3]
    predictor.set_image(image_np_rgb)
    sam_device = comfy.model_management.get_torch_device()
    masks, scores, _ = predictor.predict(
        point_coords=None, point_labels=None, box=boxes, multimask_output=False
    )
    print("scores: ", scores)
    print("masks shape before any modification:", masks.shape)
    if masks.ndim == 3:
        masks = np.expand_dims(masks, axis=0)
    print("masks shape after ensuring 4D:", masks.shape)
    masks = np.transpose(masks, (1, 0, 2, 3))
    return create_tensor_output(image_np, masks, boxes)


class SAM2ModelLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_name": (list_sam_model(),),
            }
        }

    CATEGORY = "segment_anything2"
    FUNCTION = "main"
    RETURN_TYPES = ("SAM2_MODEL",)

    def main(self, model_name):
        sam_model = load_sam_model(model_name)
        return (sam_model,)


class GroundingDinoModelLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model_name": (list_groundingdino_model(),),
            }
        }

    CATEGORY = "segment_anything2"
    FUNCTION = "main"
    RETURN_TYPES = ("GROUNDING_DINO_MODEL",)

    def main(self, model_name):
        dino_model = load_groundingdino_model(model_name)
        return (dino_model,)


class GroundingDinoSAM2Segment:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sam_model": ("SAM2_MODEL", {}),
                "grounding_dino_model": ("GROUNDING_DINO_MODEL", {}),
                "image": ("IMAGE", {}),
                "prompt": ("STRING", {}),
                "threshold": (
                    "FLOAT",
                    {"default": 0.3, "min": 0, "max": 1.0, "step": 0.01},
                ),
            }
        }

    CATEGORY = "segment_anything2"
    FUNCTION = "main"
    RETURN_TYPES = ("IMAGE", "MASK")

    def main(self, grounding_dino_model, sam_model, image, prompt, threshold):
        res_images = []
        res_masks = []
        for item in image:
            item = Image.fromarray(
                np.clip(255.0 * item.cpu().numpy(), 0, 255).astype(np.uint8)
            ).convert("RGBA")
            boxes = groundingdino_predict(grounding_dino_model, item, prompt, threshold)
            if boxes.shape[0] == 0:
                break
            (images, masks) = sam_segment(sam_model, item, boxes)
            res_images.extend(images)
            res_masks.extend(masks)
        if len(res_images) == 0:
            _, height, width, _ = image.size()
            empty_mask = torch.zeros(
                (1, height, width), dtype=torch.uint8, device="cpu"
            )
            return (empty_mask, empty_mask)
        return (torch.cat(res_images, dim=0), torch.cat(res_masks, dim=0))


def _parse_point_coordinates(value):
    if value is None:
        return []
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return []
        value = json.loads(value.replace("'", '"'))
    if isinstance(value, dict):
        value = [value]
    return [(float(point["x"]), float(point["y"])) for point in value]


def _gaussian_blur_mask(mask, sigma):
    """Blur a 2D mask without requiring OpenCV or SciPy."""
    if sigma <= 0:
        return mask
    radius = max(1, int(np.ceil(float(sigma) * 2.0)))
    axis = torch.arange(-radius, radius + 1, dtype=mask.dtype, device=mask.device)
    kernel = torch.exp(-(axis * axis) / (2.0 * float(sigma) ** 2))
    kernel = kernel / kernel.sum()
    value = mask[None, None]
    value = F.pad(value, (radius, radius, 0, 0), mode="replicate")
    value = F.conv2d(value, kernel.view(1, 1, 1, -1))
    value = F.pad(value, (0, 0, radius, radius), mode="replicate")
    value = F.conv2d(value, kernel.view(1, 1, -1, 1))
    return value[0, 0].clamp_(0.0, 1.0)


def _refine_mask(mask, close_holes_px, shrink_px, feather_px):
    """Remove background halo and create a clean antialiased alpha edge."""
    refined = mask.float().clamp(0.0, 1.0)
    close_holes_px = max(0, int(close_holes_px))
    if close_holes_px:
        value = refined[None, None]
        kernel_size = (close_holes_px * 2) + 1
        value = F.max_pool2d(
            value,
            kernel_size=kernel_size,
            stride=1,
            padding=close_holes_px,
        )
        refined = 1.0 - F.max_pool2d(
            1.0 - value,
            kernel_size=kernel_size,
            stride=1,
            padding=close_holes_px,
        )[0, 0]
    shrink_px = max(0, int(shrink_px))
    if shrink_px:
        value = refined[None, None]
        kernel_size = (shrink_px * 2) + 1
        refined = 1.0 - F.max_pool2d(
            1.0 - value,
            kernel_size=kernel_size,
            stride=1,
            padding=shrink_px,
        )[0, 0]
    return _gaussian_blur_mask(refined, float(feather_px))


def _decontaminate_edge_rgb(image, alpha, radius):
    """Extend clean foreground colours through the alpha fringe.

    PNG stores straight RGB even under transparent pixels. Filling a small gutter
    around the subject prevents black/coloured halos after compositing or resizing.
    """
    radius = max(0, int(radius))
    rgb = image[..., :3].detach().cpu().float().permute(2, 0, 1)[None].clone()
    if radius == 0:
        return rgb[0].permute(1, 2, 0)

    alpha4 = alpha.detach().cpu().float()[None, None]
    known = (alpha4 >= 0.995).to(rgb.dtype)
    if not bool(known.any()):
        return rgb[0].permute(1, 2, 0)

    # Only calculate a narrow, useful transparent gutter around the cutout.
    active = F.max_pool2d(
        (alpha4 > 0.001).to(rgb.dtype),
        kernel_size=(radius * 2) + 1,
        stride=1,
        padding=radius,
    ) > 0

    for _ in range(radius):
        weight_sum = F.avg_pool2d(known, 3, stride=1, padding=1) * 9.0
        colour_sum = F.avg_pool2d(rgb * known, 3, stride=1, padding=1) * 9.0
        can_fill = (known < 0.5) & (weight_sum > 0.0) & active
        if not bool(can_fill.any()):
            break
        neighbour_colour = colour_sum / weight_sum.clamp_min(1e-6)
        rgb = torch.where(can_fill.expand_as(rgb), neighbour_colour, rgb)
        known = torch.where(can_fill, torch.ones_like(known), known)

    return rgb[0].permute(1, 2, 0).clamp_(0.0, 1.0)


def _remove_sampled_background_from_edge(mask, image, negative_points, tolerance):
    """Remove mask pixels near the edge that match red-click background colours."""
    tolerance = max(0.0, float(tolerance))
    if tolerance == 0.0 or not negative_points:
        return mask

    rgb = image[..., :3].detach().cpu().float()
    height, width = mask.shape
    samples = []
    for x, y in negative_points:
        px = min(width - 1, max(0, int(round(x))))
        py = min(height - 1, max(0, int(round(y))))
        x0, x1 = max(0, px - 2), min(width, px + 3)
        y0, y1 = max(0, py - 2), min(height, py + 3)
        samples.append(rgb[y0:y1, x0:x1].mean(dim=(0, 1)))
    if not samples:
        return mask

    background_colours = torch.stack(samples)
    colour_distance = torch.sqrt(
        ((rgb[:, :, None, :] - background_colours[None, None, :, :]) ** 2).sum(dim=-1)
    ).amin(dim=-1)

    # Restrict colour removal to the silhouette edge so a similarly coloured
    # detail in the middle of the subject is never removed.
    edge_depth = min(24, max(1, min(height, width) // 8))
    value = mask.float()[None, None]
    interior = 1.0 - F.max_pool2d(
        1.0 - value,
        kernel_size=(edge_depth * 2) + 1,
        stride=1,
        padding=edge_depth,
    )[0, 0]
    edge_zone = (mask > 0.5) & (interior < 0.5)
    cleaned = mask.clone()
    cleaned[edge_zone & (colour_distance <= tolerance)] = 0.0
    return cleaned


class SAM2PointSegment:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "sam_model": ("SAM2_MODEL", {}),
                "image": ("IMAGE", {}),
                "positive_coords": ("STRING", {"forceInput": True}),
                "close_holes_px": (
                    "INT",
                    {"default": 5, "min": 0, "max": 30, "step": 1},
                ),
                "background_tolerance": (
                    "FLOAT",
                    {"default": 0.1, "min": 0.0, "max": 0.5, "step": 0.01},
                ),
                "edge_shrink_px": (
                    "INT",
                    {"default": 3, "min": 0, "max": 20, "step": 1},
                ),
                "edge_feather_px": (
                    "FLOAT",
                    {"default": 1.2, "min": 0.0, "max": 10.0, "step": 0.1},
                ),
                "decontaminate_px": (
                    "INT",
                    {"default": 10, "min": 0, "max": 40, "step": 1},
                ),
            },
            "optional": {
                "negative_coords": ("STRING", {"forceInput": True}),
            },
        }

    CATEGORY = "segment_anything2"
    FUNCTION = "main"
    RETURN_TYPES = ("IMAGE", "MASK")
    RETURN_NAMES = ("cutout_preview", "mask")
    DESCRIPTION = (
        "Segments an object from Points Editor clicks. Green points select the "
        "object; red points exclude background. Edge refinement removes dark halos."
    )

    def main(
        self,
        sam_model,
        image,
        positive_coords,
        close_holes_px=5,
        background_tolerance=0.1,
        edge_shrink_px=3,
        edge_feather_px=1.2,
        decontaminate_px=10,
        negative_coords=None,
    ):
        positive = _parse_point_coordinates(positive_coords)
        negative = _parse_point_coordinates(negative_coords)
        if not positive:
            raise ValueError(
                "No positive point. In Points Editor use Shift + left click on the object."
            )

        coords = np.asarray(positive + negative, dtype=np.float32)
        labels = np.asarray(
            ([1] * len(positive)) + ([0] * len(negative)), dtype=np.int32
        )
        predictor = SAM2ImagePredictor(sam_model)
        masks_out = []
        previews_out = []

        try:
            for item in image:
                image_np = np.clip(
                    item.detach().cpu().numpy() * 255.0, 0, 255
                ).astype(np.uint8)
                image_np = image_np[..., :3]
                predictor.set_image(image_np)
                masks, scores, _ = predictor.predict(
                    point_coords=coords,
                    point_labels=labels,
                    # SAM2 recommends three candidates only for an ambiguous
                    # single click. With several clicks, one consolidated mask
                    # avoids selecting an isolated part such as a bow or arm.
                    multimask_output=(len(coords) == 1),
                )
                best_index = int(np.argmax(scores))
                mask_np = masks[best_index].astype(np.float32)
                mask_tensor = _refine_mask(
                    torch.from_numpy(mask_np), close_holes_px, 0, 0.0
                ).cpu()
                mask_tensor = _remove_sampled_background_from_edge(
                    mask_tensor,
                    item,
                    negative,
                    background_tolerance,
                )
                mask_tensor = _refine_mask(
                    mask_tensor,
                    0,
                    edge_shrink_px,
                    edge_feather_px,
                ).cpu()
                masks_out.append(mask_tensor)
                previews_out.append(
                    _decontaminate_edge_rgb(item, mask_tensor, decontaminate_px)
                )
        finally:
            predictor.reset_predictor()

        return (torch.stack(previews_out), torch.stack(masks_out))


class InvertMask:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "mask": ("MASK",),
            }
        }

    CATEGORY = "segment_anything2"
    FUNCTION = "main"
    RETURN_TYPES = ("MASK",)

    def main(self, mask):
        out = 1.0 - mask
        return (out,)


class IsMaskEmptyNode:
    @classmethod
    def INPUT_TYPES(s):
        return {
            "required": {
                "mask": ("MASK",),
            },
        }

    RETURN_TYPES = ["NUMBER"]
    RETURN_NAMES = ["boolean_number"]

    FUNCTION = "main"
    CATEGORY = "segment_anything2"

    def main(self, mask):
        return (torch.all(mask == 0).int().item(),)
