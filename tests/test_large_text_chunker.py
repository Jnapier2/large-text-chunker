from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import large_text_chunker as chunker  # noqa: E402


class ChunkingTests(unittest.TestCase):
    class FakeEncoding:
        def encode_ordinary(self, text: str) -> list[str]:
            return text.split()

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
            normalized_text, _, _ = chunker.read_text_file(source)
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000, overlap_chars=120)
            digest = chunker.verify_bundle(output)
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(digest, manifest["normalized_text_sha256"])
            self.assertEqual(manifest["source_name"], source.name)
            self.assertNotIn(str(root), json.dumps(manifest))
            self.assertGreater(manifest["chunk_count"], 1)
            self.assertEqual(manifest["tokenizer"]["method"], "estimated-utf8-bytes-div-3")
            self.assertEqual(
                manifest["source_token_count"],
                chunker.estimated_tokens(normalized_text),
            )
            self.assertTrue(manifest["chatgpt_upload_advisory"]["advisory_only"])
            self.assertTrue(
                all(
                    record["token_count"] == record["estimated_tokens"]
                    for record in manifest["records"]
                )
            )

    def test_exact_token_counter_uses_optional_encoder(self) -> None:
        with mock.patch.object(
            chunker,
            "_load_tiktoken_encoding",
            return_value=(self.FakeEncoding(), "0.13.0"),
        ):
            counter = chunker.TokenCounter("exact", "o200k_base")

        self.assertTrue(counter.exact)
        self.assertEqual(counter.count("one two three"), 3)
        self.assertEqual(counter.snapshot()["package_version"], "0.13.0")

    def test_exact_mode_fails_cleanly_when_optional_package_is_unavailable(self) -> None:
        with mock.patch.object(
            chunker,
            "_load_tiktoken_encoding",
            side_effect=ModuleNotFoundError("private local detail"),
        ):
            with self.assertRaisesRegex(RuntimeError, "Install it explicitly") as raised:
                chunker.TokenCounter("exact", "o200k_base")

        self.assertNotIn("private local detail", str(raised.exception))

    def test_auto_mode_falls_back_without_exposing_internal_error_text(self) -> None:
        with mock.patch.object(
            chunker,
            "_load_tiktoken_encoding",
            side_effect=RuntimeError("C:\\Users\\example\\private-cache"),
        ):
            counter = chunker.TokenCounter("auto", "o200k_base")

        self.assertFalse(counter.exact)
        self.assertEqual(counter.fallback_reason, "RuntimeError")
        self.assertEqual(counter.count("hello"), chunker.estimated_tokens("hello"))
        self.assertNotIn("private-cache", json.dumps(counter.snapshot()))

    def test_cli_auto_mode_reports_fallback_and_creates_verified_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            destination = root / "bundle"
            source.write_text(("one two three\n" * 100), encoding="utf-8")
            captured = io.StringIO()
            with mock.patch.object(
                chunker,
                "_load_tiktoken_encoding",
                side_effect=ModuleNotFoundError("private local detail"),
            ):
                with contextlib.redirect_stdout(captured):
                    exit_code = chunker.main(
                        [
                            "split",
                            str(source),
                            "--output",
                            str(destination),
                            "--token-count-mode",
                            "auto",
                        ]
                    )

            output = captured.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("Created and verified", output)
            self.assertIn("WARNING:", output)
            self.assertNotIn("private local detail", output)
            self.assertTrue((destination / "manifest.json").is_file())

    def test_upload_advisory_expires_without_blocking_chunking(self) -> None:
        counter = chunker.TokenCounter("estimate", "o200k_base")
        reviewed = datetime.fromisoformat(
            chunker.CHATGPT_UPLOAD_POLICY_REVIEWED_UTC.replace("Z", "+00:00")
        )
        current = chunker.chatgpt_upload_advisory(100, 20, counter, now=reviewed)
        stale = chunker.chatgpt_upload_advisory(
            100,
            20,
            counter,
            now=reviewed + timedelta(days=chunker.CHATGPT_UPLOAD_POLICY_FRESHNESS_DAYS + 1),
        )

        self.assertEqual(current["status"], "current")
        self.assertEqual(stale["status"], "review_due")
        self.assertTrue(stale["advisory_only"])

    def test_exact_bundle_records_source_and_chunk_token_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text(("one two three four\n" * 100), encoding="utf-8")
            with mock.patch.object(
                chunker,
                "_load_tiktoken_encoding",
                return_value=(self.FakeEncoding(), "0.13.0"),
            ):
                output = chunker.write_bundle(
                    source,
                    root / "bundle",
                    max_chars=1_000,
                    token_count_mode="exact",
                )
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(manifest["tokenizer"]["method"], "tiktoken-exact")
            self.assertEqual(manifest["source_token_count"], 400)
            self.assertTrue(all(record["token_count"] > 0 for record in manifest["records"]))
            self.assertEqual(chunker.verify_bundle(output), manifest["normalized_text_sha256"])

    def test_legacy_manifest_without_token_metadata_remains_verifiable(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text(("line\n" * 600), encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["tool_version"] = "1.0.0"
            for field in (
                "source_size_bytes",
                "source_token_count",
                "tokenizer",
                "chatgpt_upload_advisory",
            ):
                manifest.pop(field)
            for record in manifest["records"]:
                record.pop("token_count")
                record.pop("token_count_method")
                record.pop("tokenizer_encoding")
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            self.assertEqual(chunker.verify_bundle(output), manifest["normalized_text_sha256"])

    def test_tampered_estimated_token_count_fails_verification(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.txt"
            source.write_text(("line\n" * 600), encoding="utf-8")
            output = chunker.write_bundle(source, root / "bundle", max_chars=1_000)
            manifest_path = output / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["records"][0]["estimated_tokens"] += 1
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "Estimated token count mismatch"):
                chunker.verify_bundle(output)

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
