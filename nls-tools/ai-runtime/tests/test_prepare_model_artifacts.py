from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "prepare_model_artifacts.py"
SPEC = importlib.util.spec_from_file_location("prepare_model_artifacts", SCRIPT)
assert SPEC and SPEC.loader
preparer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preparer)


class ModelPreparerTests(unittest.TestCase):
    def test_reuses_verified_import_and_populates_cache(self) -> None:
        content = b"immutable-model-fixture"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            import_root = root / "import"
            imported = import_root / "worker" / "model.bin"
            imported.parent.mkdir(parents=True)
            imported.write_bytes(content)
            artifact = {
                "relativePath": "worker/model.bin",
                "sizeBytes": len(content),
                "sha256": digest,
                "importRelativePaths": ["worker/model.bin"],
                "urls": [],
            }

            preparer.prepare_artifact(
                artifact,
                models_root=root / "models",
                cache_root=root / "cache",
                mirror=None,
                import_roots=[import_root],
            )

            destination = root / "models" / "worker" / "model.bin"
            cache = root / "cache" / digest[:2] / digest / "model.bin"
            self.assertEqual(content, destination.read_bytes())
            self.assertEqual(content, cache.read_bytes())

    def test_quarantines_invalid_destination_before_recovery(self) -> None:
        content = b"expected"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root / "models" / "worker" / "model.bin"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"corrupt")
            source = root / "verified.bin"
            source.write_bytes(content)

            preparer.prepare_artifact(
                {
                    "relativePath": "worker/model.bin",
                    "sizeBytes": len(content),
                    "sha256": digest,
                "importRelativePaths": ["verified.bin"],
                    "urls": [],
                },
                models_root=root / "models",
                cache_root=root / "cache",
                mirror=None,
                import_roots=[root],
            )

            self.assertEqual(content, destination.read_bytes())
            self.assertEqual(1, len(list(destination.parent.glob("model.bin.invalid-*"))))

    def test_requires_explicit_license_acceptance(self) -> None:
        manifest = {
            "license": {
                "acceptanceEnvironment": "NJS_TEST_LICENSE_ACCEPTED",
                "acceptanceMessage": "Review test license.",
            }
        }
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Review test license"):
                preparer.require_license_acceptance(manifest)
        with patch.dict(os.environ, {"NJS_TEST_LICENSE_ACCEPTED": "1"}, clear=True):
            preparer.require_license_acceptance(manifest)

    def test_uses_next_pinned_url_after_checksum_mismatch(self) -> None:
        content = b"verified-download"
        digest = hashlib.sha256(content).hexdigest()
        calls: list[str] = []

        def fake_download(url: str, partial: Path, attempts: int = 4) -> None:
            del attempts
            calls.append(url)
            partial.parent.mkdir(parents=True, exist_ok=True)
            partial.write_bytes(b"wrong" if url.endswith("bad.bin") else content)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(preparer, "download_with_resume", side_effect=fake_download):
                preparer.prepare_artifact(
                    {
                        "relativePath": "worker/model.bin",
                        "sizeBytes": len(content),
                        "sha256": digest,
                        "urls": [
                            "https://models.example/bad.bin",
                            "https://backup.example/good.bin",
                        ],
                    },
                    models_root=root / "models",
                    cache_root=root / "cache",
                    mirror=None,
                    import_roots=[],
                )

            self.assertEqual(
                ["https://models.example/bad.bin", "https://backup.example/good.bin"],
                calls,
            )
            self.assertEqual(content, (root / "models" / "worker" / "model.bin").read_bytes())


if __name__ == "__main__":
    unittest.main()
