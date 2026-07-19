from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import large_text_chunker as chunker  # noqa: E402


class ChunkingTests(unittest.TestCase):
    def test_build_chunks_preserves_normalized_text_exactly(self) -> None:
        text = ("First paragraph.\n\n" * 90) + ("A long sentence with words. " * 100)
        chunks = chunker.build_chunks(text, 1_000)
        self.assertGreater(len(chunks), 1)
        self.assertEqual(text, "".join(part for _, _, part in chunks))
        self.assertTrue(all(len(part) <= 1_000 for _, _, part in chunks))

    def test_bundle_round_trip_with_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source document.txt"
            source.write_text(("alpha beta gamma\r\n\r\n" * 150), encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=120)
            digest = chunker.verify_bundle(output)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(digest, manifest["normalized_text_sha256"])
            self.assertEqual(manifest["source_name"], source.name)
            self.assertNotIn(str(root), json.dumps(manifest))
            self.assertGreater(manifest["chunk_count"], 1)

    def test_modified_chunk_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("line\n" * 600, encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=50)
            first = next(output.glob("chunk_*.txt"))
            first.write_text(first.read_text(encoding="utf-8") + "changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                chunker.verify_bundle(output)

    def test_binary_input_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "binary.dat"
            path.write_bytes(b"abc\x00def")
            with self.assertRaisesRegex(ValueError, "binary"):
                chunker.read_text_file(path)


if __name__ == "__main__":
    unittest.main()
