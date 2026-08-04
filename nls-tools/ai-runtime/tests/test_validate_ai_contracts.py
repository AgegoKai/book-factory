from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "nls-tools/ai-runtime/scripts/validate_ai_contracts.py"
SPEC = importlib.util.spec_from_file_location("validate_ai_contracts", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class ContractValidationTest(unittest.TestCase):
    def test_checked_in_contracts_are_valid(self) -> None:
        errors = []
        for manifest in MODULE.COMFY_MANIFESTS:
            errors.extend(MODULE.validate_comfy(ROOT, manifest))
        errors.extend(MODULE.validate_lama(ROOT))
        self.assertEqual([], errors)

    def test_workflow_hash_mismatch_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rel = Path("worker/workflow-manifest.json")
            (root / rel.parent).mkdir(parents=True)
            graph = {"1": {"class_type": "LoadImage", "inputs": {"image": "x.png"}}}
            (root / "worker/flow.json").write_text(json.dumps(graph), encoding="utf-8")
            manifest = {
                "schemaVersion": 2,
                "id": "test-worker",
                "version": "1.0.0",
                "engine": "comfyui",
                "workflow": {"api": "flow.json", "sha256": "0" * 64},
                "contract": {
                    "inputs": {"image": {"binding": {"nodeId": "1", "input": "image"}}},
                    "outputs": {}
                },
                "requirements": {"models": []}
            }
            (root / rel).write_text(json.dumps(manifest), encoding="utf-8")
            errors = MODULE.validate_comfy(root, rel)
            self.assertTrue(any("sha256 does not match" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
