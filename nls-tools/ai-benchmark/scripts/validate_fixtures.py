#!/usr/bin/env python3
"""Verify fixture provenance, portable paths and all recorded checksums."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path, PurePosixPath


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "fixtures/fixtures.json"
ALLOWED_LICENSES = {"CC0", "Public domain"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_portable(value: str) -> Path:
    posix = PurePosixPath(value)
    if posix.is_absolute() or ".." in posix.parts or "\\" in value:
        raise ValueError(f"non-portable fixture path: {value!r}")
    path = ROOT.joinpath(*posix.parts)
    if not path.is_file():
        raise ValueError(f"missing fixture: {value}")
    return path


def main() -> int:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    errors: list[str] = []
    for source in data.get("sources", []):
        if source.get("license") not in ALLOWED_LICENSES:
            errors.append(f"{source.get('id')}: disallowed license {source.get('license')!r}")
        if not str(source.get("descriptionUrl", "")).startswith("https://commons.wikimedia.org/"):
            errors.append(f"{source.get('id')}: missing Commons provenance URL")
        try:
            original = resolve_portable(source["original"])
            if digest(original) != source.get("sourceSha256"):
                errors.append(f"{source.get('id')}: original checksum mismatch")
            normalized = resolve_portable(source["normalized"])
            if digest(normalized) != source.get("normalizedSha256"):
                errors.append(f"{source.get('id')}: normalized checksum mismatch")
        except (KeyError, ValueError) as exc:
            errors.append(f"{source.get('id')}: {exc}")
    for case in data.get("cases", []):
        for key in ("input", "mask", "goldenMask", "expected"):
            if key not in case:
                continue
            try:
                path = resolve_portable(case[key])
                if digest(path) != case.get(f"{key}Sha256"):
                    errors.append(f"{case.get('id')}: {key} checksum mismatch")
            except ValueError as exc:
                errors.append(f"{case.get('id')}: {exc}")
    tasks = {case.get("task") for case in data.get("cases", [])}
    if tasks != {"remove-background", "retouch"}:
        errors.append("fixture set must cover remove-background and retouch")
    if not any(case.get("goldenMask") for case in data.get("cases", [])):
        errors.append("at least one golden mask is required")
    if errors:
        print("Fixture validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print(f"Fixtures valid: {len(data['sources'])} sources, {len(data['cases'])} cases")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
