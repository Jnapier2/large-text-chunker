from __future__ import annotations

import contextlib
import io
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

    def test_manifest_path_escape_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("line\n" * 600, encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=50)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["records"][0]["filename"] = "../outside.txt"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "simple relative filename"):
                chunker.verify_bundle(output)

    def test_malformed_manifest_returns_a_clean_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("line\n" * 600, encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=50)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["records"][0] = {}
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            captured = io.StringIO()
            with contextlib.redirect_stdout(captured):
                exit_code = chunker.main(["verify", str(output)])

            self.assertEqual(exit_code, 2)
            self.assertIn("ERROR: Record 1", captured.getvalue())
            self.assertNotIn("Traceback", captured.getvalue())

    def test_manifest_chunk_count_must_match_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("line\n" * 600, encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=50)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["chunk_count"] += 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "chunk_count"):
                chunker.verify_bundle(output)

    def test_manifest_rejects_windows_filename_aliases(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text("line\n" * 600, encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=50)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

            for filename in (
                "chunk_001_of_003.txt:review",
                "chunk_001_of_003.txt.",
                "chunk_001_of_003.txt ",
                "CON.txt",
            ):
                with self.subTest(filename=filename):
                    manifest["records"][0]["filename"] = filename
                    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "filename"):
                        chunker.verify_bundle(output)


if __name__ == "__main__":
    unittest.main()
