#!/usr/bin/env python3
"""Download license-safe Commons fixtures and build deterministic golden cases."""

from __future__ import annotations

import hashlib
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFilter


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SOURCE_SPEC = ROOT / "fixtures/fixture-sources.json"
SOURCE_DIR = ROOT / "fixtures/source"
GENERATED_DIR = ROOT / "fixtures/generated"
MANIFEST = ROOT / "fixtures/fixtures.json"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
ALLOWED_LICENSES = {"CC0", "Public domain"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def request_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "njs-ai-benchmark/1.0 (Shortcut #1678)"})
    return json.loads(download(request, timeout=90))


def download(request: Request, *, timeout: float) -> bytes:
    for attempt in range(5):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code != 429 or attempt == 4:
                raise
            delay = min(30, int(exc.headers.get("Retry-After", "5")) + (attempt * 5))
            print(f"Wikimedia rate limit; retry in {delay}s", file=sys.stderr)
            time.sleep(delay)
    raise AssertionError("unreachable")


def clean(value: str | None) -> str:
    without_tags = re.sub(r"<[^>]+>", "", (value or "").replace("<br />", " "))
    return html.unescape(without_tags).strip()


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def commons_info(title: str) -> dict:
    query = urlencode({
        "action": "query",
        "format": "json",
        "prop": "imageinfo",
        "iiprop": "url|size|sha1|extmetadata",
        "titles": title,
    })
    pages = request_json(f"{COMMONS_API}?{query}")["query"]["pages"]
    page = next(iter(pages.values()))
    if "missing" in page or not page.get("imageinfo"):
        raise RuntimeError(f"Wikimedia Commons file not found: {title}")
    return page["imageinfo"][0]


def normalize(source: Path, destination: Path, max_edge: int = 1600) -> Image.Image:
    with Image.open(source) as opened:
        image = opened.convert("RGBA" if "A" in opened.getbands() else "RGB")
    scale = min(1.0, max_edge / max(image.size))
    if scale < 1.0:
        image = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    destination.parent.mkdir(parents=True, exist_ok=True)
    image.save(destination, format="PNG", optimize=True)
    return image


def deep_points(mask: Image.Image) -> list[dict[str, int]]:
    """Choose robust positive prompts away from holes and antialiased edges."""
    binary = mask.point(lambda value: 255 if value > 180 else 0)
    result = []
    for left, right in ((0.08, 0.40), (0.34, 0.68), (0.62, 0.94)):
        x0, x1 = round(binary.width * left), round(binary.width * right)
        crop = binary.crop((x0, 0, x1, binary.height)).resize(
            (max(1, (x1 - x0) // 8), max(1, binary.height // 8)), Image.Resampling.NEAREST
        )
        last = crop
        for _ in range(40):
            eroded = last.filter(ImageFilter.MinFilter(5))
            if eroded.getbbox() is None:
                break
            last = eroded
        bbox = last.getbbox() or crop.getbbox()
        if bbox:
            x = x0 + round(((bbox[0] + bbox[2]) / 2) * 8)
            y = round(((bbox[1] + bbox[3]) / 2) * 8)
            result.append({"x": min(mask.width - 1, x), "y": min(mask.height - 1, y)})
    return result or [{"x": mask.width // 2, "y": mask.height // 2}]


def make_alpha_case(image: Image.Image, fixture_id: str) -> dict | None:
    if image.mode != "RGBA" or image.getchannel("A").getextrema() == (255, 255):
        return None
    canvas = Image.new("RGB", image.size, "#eef0f3")
    canvas.paste(image.convert("RGB"), mask=image.getchannel("A"))
    input_path = GENERATED_DIR / f"{fixture_id}-composite.png"
    mask_path = GENERATED_DIR / f"{fixture_id}-golden-mask.png"
    canvas.save(input_path, optimize=True)
    image.getchannel("A").save(mask_path, optimize=True)
    return {
        "id": f"{fixture_id}-remove-bg",
        "task": "remove-background",
        "input": relative(input_path),
        "goldenMask": relative(mask_path),
        "sam2Points": deep_points(image.getchannel("A")),
        "sam2NegativePoints": [{"x": 2, "y": 2}],
    }


def make_retouch_cases(clean_image: Image.Image, fixture_id: str) -> list[dict]:
    rgb = clean_image.convert("RGB")
    cases = []
    expected_path = GENERATED_DIR / f"{fixture_id}-retouch-expected.png"
    rgb.save(expected_path, optimize=True)
    specs = (
        ("thin", max(3, min(rgb.size) // 220), "Crop", 96),
        ("thick", max(18, min(rgb.size) // 28), "Crop", 128),
        ("full", max(24, min(rgb.size) // 18), "Original", 0),
    )
    for kind, width, strategy, margin in specs:
        damaged = rgb.copy()
        mask = Image.new("L", rgb.size, 0)
        draw_image = ImageDraw.Draw(damaged)
        draw_mask = ImageDraw.Draw(mask)
        if kind == "thin":
            points = [(rgb.width * 0.25, rgb.height * 0.35), (rgb.width * 0.48, rgb.height * 0.50), (rgb.width * 0.72, rgb.height * 0.43)]
            draw_image.line(points, fill=(45, 30, 18), width=width, joint="curve")
            draw_mask.line(points, fill=255, width=width + 8, joint="curve")
        else:
            cx, cy = rgb.width * (0.58 if kind == "thick" else 0.42), rgb.height * 0.50
            radius = width * (1.6 if kind == "full" else 1.0)
            box = (cx - radius, cy - radius * 0.7, cx + radius, cy + radius * 0.7)
            draw_image.ellipse(box, fill=(72, 45, 28))
            expand = 8
            draw_mask.ellipse((box[0]-expand, box[1]-expand, box[2]+expand, box[3]+expand), fill=255)
        input_path = GENERATED_DIR / f"{fixture_id}-retouch-{kind}-input.png"
        mask_path = GENERATED_DIR / f"{fixture_id}-retouch-{kind}-mask.png"
        damaged.save(input_path, optimize=True)
        mask.save(mask_path, optimize=True)
        cases.append({
            "id": f"{fixture_id}-retouch-{kind}", "task": "retouch", "maskKind": kind,
            "input": relative(input_path), "mask": relative(mask_path),
            "expected": relative(expected_path), "hdStrategy": strategy, "roiMargin": margin,
        })
    return cases


def main() -> int:
    spec = json.loads(SOURCE_SPEC.read_text(encoding="utf-8"))
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    sources, cases = [], []
    normalized: dict[str, Image.Image] = {}
    for item in spec["sources"]:
        info = commons_info(item["commonsTitle"])
        metadata = info.get("extmetadata", {})
        license_name = clean(metadata.get("LicenseShortName", {}).get("value"))
        if license_name not in ALLOWED_LICENSES:
            raise RuntimeError(f"Refusing {item['commonsTitle']}: license is {license_name!r}")
        suffix = Path(urlparse(info["url"]).path).suffix.lower() or ".img"
        raw_path = SOURCE_DIR / f"{item['id']}-original{suffix}"
        if not raw_path.exists():
            request = Request(info["url"], headers={"User-Agent": "njs-ai-benchmark/1.0"})
            raw_path.write_bytes(download(request, timeout=180))
            time.sleep(2)
        normalized_path = SOURCE_DIR / f"{item['id']}.png"
        image = normalize(raw_path, normalized_path)
        normalized[item["id"]] = image
        sources.append({
            **item,
            "descriptionUrl": clean(metadata.get("DescriptionUrl", {}).get("value")) or f"https://commons.wikimedia.org/wiki/{item['commonsTitle'].replace(' ', '_')}",
            "downloadUrl": info["url"], "author": clean(metadata.get("Artist", {}).get("value")),
            "license": license_name, "licenseUrl": clean(metadata.get("LicenseUrl", {}).get("value")),
            "original": relative(raw_path), "sourceSha256": sha256(raw_path), "normalizedSha256": sha256(normalized_path),
            "normalized": relative(normalized_path), "width": image.width, "height": image.height,
        })
        alpha_case = make_alpha_case(image, item["id"])
        if alpha_case:
            cases.append(alpha_case)
    for item in sources:
        if item["id"] == "worn-shoe-alpha":
            continue
        image = normalized[item["id"]]
        cases.append({
            "id": f"{item['id']}-remove-bg", "task": "remove-background",
            "categories": item["categories"], "input": item["normalized"],
            "sam2Points": next(source["sam2Points"] for source in spec["sources"] if source["id"] == item["id"]),
            "sam2NegativePoints": [{"x": 2, "y": 2}],
        })
    cases.extend(make_retouch_cases(normalized["white-ceramic-cup"], "white-ceramic-cup"))
    for case in cases:
        for key in ("input", "mask", "goldenMask", "expected"):
            if key in case:
                case[f"{key}Sha256"] = sha256(ROOT / case[key])
    output = {"schemaVersion": 1, "storage": "repository-local; never production", "sources": sources, "cases": cases}
    MANIFEST.write_text(json.dumps(output, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Prepared {len(sources)} sources and {len(cases)} benchmark cases in {ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
