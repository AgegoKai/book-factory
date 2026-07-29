#!/usr/bin/env python3
"""Mały klient API dla lokalnego workflow RMBG-2.0 w ComfyUI."""

from __future__ import annotations

import argparse
import json
import mimetypes
import re
import time
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_WORKFLOW = SCRIPT_DIR.parent / "workflows" / "RemoveBg_by_RMBG2_API.json"


def request_bytes(
    url: str,
    *,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 30,
) -> bytes:
    headers = {"Accept": "application/json, image/png"}
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.read()
    except HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} dla {url}: {details}") from exc
    except URLError as exc:
        raise RuntimeError(f"Nie można połączyć się z {url}: {exc.reason}") from exc


def request_json(
    url: str,
    *,
    payload: dict | None = None,
    content_type: str = "application/json",
    timeout: float = 30,
) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    return json.loads(
        request_bytes(url, data=data, content_type=content_type if data is not None else None, timeout=timeout)
    )


def upload_image(server: str, image_path: Path) -> dict:
    boundary = f"----RMBGClient{uuid.uuid4().hex}"
    mime = mimetypes.guess_type(image_path.name)[0] or "application/octet-stream"
    image = image_path.read_bytes()
    body = b"".join(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="image"; filename="{image_path.name}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            image,
            b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="overwrite"\r\n\r\ntrue\r\n',
            f"--{boundary}--\r\n".encode(),
        ]
    )
    response = request_bytes(
        f"{server}/upload/image",
        data=body,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=120,
    )
    return json.loads(response)


def wait_for_result(server: str, process_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        history = request_json(f"{server}/history/{process_id}", timeout=15)
        if process_id in history:
            result = history[process_id]
            status = result.get("status", {})
            if status.get("status_str") != "success":
                raise RuntimeError(f"Proces zakończył się błędem: {json.dumps(status, ensure_ascii=False)}")
            return result
        time.sleep(1)
    raise TimeoutError(f"Proces {process_id} nie zakończył się w ciągu {timeout:.0f} s")


def download_output(server: str, image: dict, output_dir: Path) -> Path:
    query = urlencode(
        {
            "filename": image["filename"],
            "subfolder": image.get("subfolder", ""),
            "type": image.get("type", "output"),
        }
    )
    destination = output_dir / image["filename"]
    destination.write_bytes(request_bytes(f"{server}/view?{query}", timeout=120))
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description="Usuń tło przez lokalne API RMBG-2.0/ComfyUI.")
    parser.add_argument("image", type=Path, help="Ścieżka zdjęcia wejściowego")
    parser.add_argument("--server", default="http://127.0.0.1:8189", help="Adres ComfyUI")
    parser.add_argument("--workflow", type=Path, default=DEFAULT_WORKFLOW, help="Workflow w formacie API")
    parser.add_argument("--output-dir", type=Path, default=Path("api-results"), help="Katalog wyników")
    parser.add_argument("--timeout", type=float, default=600, help="Maksymalny czas oczekiwania w sekundach")
    args = parser.parse_args()

    image_path = args.image.expanduser().resolve()
    if not image_path.is_file():
        parser.error(f"Nie znaleziono zdjęcia: {image_path}")

    server = args.server.rstrip("/")
    request_json(f"{server}/system_stats", timeout=10)

    uploaded = upload_image(server, image_path)
    workflow = json.loads(args.workflow.read_text(encoding="utf-8"))
    uploaded_name = "/".join(filter(None, [uploaded.get("subfolder", ""), uploaded["name"]]))
    workflow["1"]["inputs"]["image"] = uploaded_name

    safe_name = re.sub(r"[^a-zA-Z0-9_-]+", "_", image_path.stem).strip("_") or "image"
    workflow["3"]["inputs"]["filename_prefix"] = f"RMBG2/{safe_name}_cutout"
    workflow["4"]["inputs"]["filename_prefix"] = f"RMBG2/{safe_name}_alpha_mask"

    queued = request_json(f"{server}/prompt", payload={"prompt": workflow}, timeout=30)
    process_id = queued["prompt_id"]
    print(f"processID={process_id}")
    print("status=processing")

    result = wait_for_result(server, process_id, args.timeout)
    output_dir = args.output_dir.expanduser().resolve() / process_id
    output_dir.mkdir(parents=True, exist_ok=True)

    cutout = download_output(server, result["outputs"]["3"]["images"][0], output_dir)
    alpha_mask = download_output(server, result["outputs"]["4"]["images"][0], output_dir)

    print("status=completed")
    print(f"cutout={cutout}")
    print(f"alpha_mask={alpha_mask}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
