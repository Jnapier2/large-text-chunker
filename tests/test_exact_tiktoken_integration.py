from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import large_text_chunker as chunker  # noqa: E402


@unittest.skipUnless(importlib.util.find_spec("tiktoken"), "optional tiktoken is not installed")
class ExactTiktokenIntegrationTests(unittest.TestCase):
    def test_real_o200k_base_bundle_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source document.txt"
            source.write_text(("Evidence stays linked to its source.\n" * 120), encoding="utf-8")

            output = chunker.write_bundle(
                source,
                root / "exact bundle",
                max_chars=1_000,
                overlap_chars=80,
                token_count_mode="exact",
                tokenizer_encoding="o200k_base",
            )
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["tokenizer"]["method"], "tiktoken-exact")
            self.assertEqual(manifest["tokenizer"]["package_version"], "0.13.0")
            self.assertGreater(manifest["source_token_count"], 0)
            self.assertEqual(
                chunker.verify_bundle(output),
                manifest["normalized_text_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
