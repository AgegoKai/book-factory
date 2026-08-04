#!/usr/bin/env python3
"""Prepare immutable model artifacts from a checksum-verified manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Iterable


ACCEPTED_VALUES = {"1", "true", "yes", "accepted"}
CHUNK_SIZE = 8 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def is_valid(path: Path, expected_size: int, expected_sha256: str) -> bool:
    return (
        path.is_file()
        and path.stat().st_size == expected_size
        and sha256_file(path) == expected_sha256
    )


def require_license_acceptance(manifest: dict) -> None:
    license_info = manifest.get("license") or {}
    variable = license_info.get("acceptanceEnvironment")
    if not variable:
        return
    if os.environ.get(variable, "").strip().lower() in ACCEPTED_VALUES:
        return
    message = license_info.get("acceptanceMessage") or (
        f"Set {variable}=1 only after reviewing the model license."
    )
    raise RuntimeError(f"{message}\nRequired environment variable: {variable}")


def copy_verified(source: Path, destination: Path, size: int, digest: str) -> bool:
    if not is_valid(source, size, digest):
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.copying")
    shutil.copy2(source, temporary)
    if not is_valid(temporary, size, digest):
        temporary.unlink(missing_ok=True)
        raise RuntimeError(f"Checksum changed while copying {source}")
    os.replace(temporary, destination)
    return True


def quarantine_invalid(path: Path) -> None:
    if not path.exists():
        return
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    quarantine = path.with_name(f"{path.name}.invalid-{timestamp}")
    path.replace(quarantine)
    print(f"quarantined={quarantine}")


def download_with_resume(url: str, partial: Path, attempts: int = 4) -> None:
    if not url.lower().startswith("https://"):
        raise RuntimeError(f"Only HTTPS model sources are allowed: {url}")
    partial.parent.mkdir(parents=True, exist_ok=True)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            headers = {"User-Agent": "njs-ai-model-preparer/1.0"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=60) as response:
                status = getattr(response, "status", 200)
                append = offset > 0 and status == 206
                mode = "ab" if append else "wb"
                with partial.open(mode) as target:
                    shutil.copyfileobj(response, target, length=CHUNK_SIZE)
            return
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            print(f"download_retry={attempt}/{attempts} url={url} error={exc}", file=sys.stderr)
            time.sleep(min(2**attempt, 15))
    raise RuntimeError(f"Unable to download {url}: {last_error}")


def mirror_candidates(mirror: str | None, mirror_path: str | None) -> Iterable[Path | str]:
    if not mirror or not mirror_path:
        return []
    if mirror.lower().startswith("https://"):
        return [f"{mirror.rstrip('/')}/{mirror_path.lstrip('/')}"]
    return [Path(mirror).expanduser() / Path(mirror_path)]


def prepare_artifact(
    artifact: dict,
    *,
    models_root: Path,
    cache_root: Path,
    mirror: str | None,
    import_roots: list[Path],
) -> None:
    relative_path = Path(artifact["relativePath"])
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise RuntimeError(f"Unsafe relativePath in manifest: {relative_path}")
    expected_size = int(artifact["sizeBytes"])
    expected_sha256 = str(artifact["sha256"]).lower()
    destination = models_root / relative_path
    if is_valid(destination, expected_size, expected_sha256):
        print(f"ready={destination}")
        return

    quarantine_invalid(destination)
    cache_path = cache_root / expected_sha256[:2] / expected_sha256 / relative_path.name
    local_candidates: list[Path] = [cache_path]
    for import_root in import_roots:
        for import_path in artifact.get("importRelativePaths", []):
            relative_import_path = Path(import_path)
            if relative_import_path.is_absolute() or ".." in relative_import_path.parts:
                raise RuntimeError(f"Unsafe importRelativePath in manifest: {relative_import_path}")
            local_candidates.append(import_root / relative_import_path)
    for candidate in mirror_candidates(mirror, artifact.get("mirrorPath")):
        if isinstance(candidate, Path):
            local_candidates.append(candidate)

    for source in local_candidates:
        if copy_verified(source, destination, expected_size, expected_sha256):
            if source != cache_path:
                copy_verified(source, cache_path, expected_size, expected_sha256)
            print(f"prepared={destination} source={source}")
            return

    urls: list[str] = []
    urls.extend(value for value in mirror_candidates(mirror, artifact.get("mirrorPath")) if isinstance(value, str))
    urls.extend(artifact.get("urls", []))
    partial = cache_path.with_name(f"{cache_path.name}.partial")
    errors: list[str] = []
    for url in urls:
        try:
            download_with_resume(url, partial)
            if not is_valid(partial, expected_size, expected_sha256):
                actual_size = partial.stat().st_size if partial.exists() else 0
                actual_hash = sha256_file(partial) if partial.exists() else "missing"
                errors.append(f"{url}: size={actual_size}, sha256={actual_hash}")
                partial.unlink(missing_ok=True)
                continue
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            os.replace(partial, cache_path)
            if not copy_verified(cache_path, destination, expected_size, expected_sha256):
                raise RuntimeError(f"Verified cache copy failed for {destination}")
            print(f"prepared={destination} source={url}")
            return
        except Exception as exc:  # continue to the next pinned source
            errors.append(f"{url}: {exc}")
    raise RuntimeError(
        f"No verified source produced {destination}. "
        + " | ".join(errors)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--models-root", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--mirror", default=os.environ.get("NJS_AI_MODEL_MIRROR", ""))
    parser.add_argument(
        "--import-root",
        action="append",
        default=[],
        type=Path,
        help="Optional root containing existing artifacts at importRelativePaths",
    )
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("schemaVersion") != 1:
        raise RuntimeError(f"Unsupported manifest schema in {args.manifest}")
    require_license_acceptance(manifest)
    for artifact in manifest.get("artifacts", []):
        prepare_artifact(
            artifact,
            models_root=args.models_root.expanduser(),
            cache_root=args.cache_root.expanduser(),
            mirror=args.mirror or None,
            import_roots=[path.expanduser() for path in args.import_root],
        )
    print(f"manifest_ready={manifest['id']} version={manifest['version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
