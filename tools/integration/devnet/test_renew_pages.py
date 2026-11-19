"""Guardrails for the operator-only CON-59 renewal procedure."""
from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.integration.devnet import renew_pages as renew


class RenewPagesTest(unittest.TestCase):
    def test_source_must_be_clean_and_commit_must_be_full_sha(self):
        with patch.object(renew, "command", return_value=" M apps/marketplace-web/src/devnet/app.ts"):
            with self.assertRaisesRegex(ValueError, "SOURCE_TREE_DIRTY"):
                renew.require_clean_source()
        with patch.object(renew, "command", side_effect=["", "shortsha"]):
            with self.assertRaisesRegex(ValueError, "SOURCE_COMMIT_INVALID"):
                renew.require_clean_source()
        with patch.object(renew, "command", side_effect=["", "a" * 40]):
            self.assertEqual(renew.require_clean_source(), "a" * 40)

    def test_existing_artifact_rejected_before_build_or_rpc(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "existing"
            artifact.mkdir()
            wrangler = root / "wrangler"
            wrangler.write_text("fixture")
            with patch.object(renew, "command") as command:
                with self.assertRaisesRegex(ValueError, "ARTIFACT_OR_WRANGLER_INVALID"):
                    renew.prepare(artifact, wrangler)
                command.assert_not_called()

if __name__ == "__main__":
    unittest.main()
