# Copyright © 2026 Gateway Information Group LLC. All rights reserved.
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


class InputEncodingTests(unittest.TestCase):
    """Synthetic fixtures for the public encoding port; no private document data."""

    TEXT = "Client café — 東京 😀\r\nSecond line.\rThird line.\n\n" * 60

    def test_marked_utf_encodings_preserve_text_and_original_bytes(self) -> None:
        import codecs
        variants = (
            (codecs.BOM_UTF8, "utf-8", "utf-8-sig"),
            (codecs.BOM_UTF16_LE, "utf-16-le", "utf-16"),
            (codecs.BOM_UTF16_BE, "utf-16-be", "utf-16"),
            (codecs.BOM_UTF32_LE, "utf-32-le", "utf-32"),
            (codecs.BOM_UTF32_BE, "utf-32-be", "utf-32"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.txt"
            for bom, source_encoding, expected_encoding in variants:
                with self.subTest(encoding=source_encoding):
                    data = bom + self.TEXT.encode(source_encoding)
                    path.write_bytes(data)
                    text, detected, raw = chunker.read_text_file(path)
                    self.assertEqual(text, self.TEXT.replace("\r\n", "\n").replace("\r", "\n"))
                    self.assertEqual(detected, expected_encoding)
                    self.assertEqual(raw, data)
                    self.assertFalse(text.startswith("\ufeff"))

    def test_unmarked_unicode_can_be_selected_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.txt"
            for encoding in ("utf-16-le", "utf-16-be", "utf-32-le", "utf-32-be"):
                with self.subTest(encoding=encoding):
                    path.write_bytes(self.TEXT.encode(encoding))
                    text, detected, _ = chunker.read_text_file(path, encoding)
                    self.assertEqual(detected, encoding)
                    self.assertEqual(text, self.TEXT.replace("\r\n", "\n").replace("\r", "\n"))

    def test_unmarked_nul_text_is_not_guessed_as_unicode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unmarked.txt"
            path.write_bytes("plain text".encode("utf-16-le"))
            with self.assertRaisesRegex(ValueError, "NUL"):
                chunker.read_text_file(path)

    def test_bom_and_explicit_encoding_must_agree(self) -> None:
        import codecs
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unicode.txt"
            path.write_bytes(codecs.BOM_UTF16_BE + self.TEXT.encode("utf-16-be"))
            for encoding in ("utf-8", "utf-16-le", "latin-1"):
                with self.subTest(encoding=encoding):
                    with self.assertRaisesRegex(ValueError, "conflicts"):
                        chunker.read_text_file(path, encoding)
            self.assertEqual(chunker.read_text_file(path, "utf-16-be")[1], "utf-16")

    def test_malformed_marked_input_never_uses_legacy_fallback(self) -> None:
        import codecs
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.txt"
            for data in (codecs.BOM_UTF8 + b"\xff", codecs.BOM_UTF16_LE + b"a", codecs.BOM_UTF32_BE + b"abc"):
                with self.subTest(data=data):
                    path.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, "does not decode"):
                        chunker.read_text_file(path)

    def test_explicit_decode_error_is_not_lossy_or_content_leaking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.txt"
            path.write_bytes(b"sensitive fixture \xff")
            with self.assertRaises(ValueError) as raised:
                chunker.read_text_file(path, "utf-8")
            self.assertNotIn("sensitive fixture", str(raised.exception))
            self.assertNotIn(str(path), str(raised.exception))
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                chunker.read_text_file(path, "not-a-codec")

    def test_nul_after_legacy_sample_boundary_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "late_nul.txt"
            path.write_bytes(b"x" * 9000 + b"\x00")
            with self.assertRaisesRegex(ValueError, "binary"):
                chunker.read_text_file(path)

    def test_unicode_nul_character_remains_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "nul.txt"
            path.write_bytes("ordinary\x00text".encode("utf-16"))
            with self.assertRaisesRegex(ValueError, "NUL"):
                chunker.read_text_file(path)

    def test_legacy_single_byte_fallback_is_preserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.txt"
            for text, encoding in (("café €", "cp1252"), ("café\x81", "latin-1")):
                with self.subTest(encoding=encoding):
                    path.write_bytes(text.encode(encoding))
                    result, detected, _ = chunker.read_text_file(path)
                    self.assertEqual(result, text)
                    self.assertEqual(detected, encoding)

    def test_marked_unicode_bundle_verifies_hashes_and_overlap(self) -> None:
        import codecs
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "unicode.txt"
            for bom, encoding in ((codecs.BOM_UTF16_LE, "utf-16-le"), (codecs.BOM_UTF32_BE, "utf-32-be")):
                with self.subTest(encoding=encoding):
                    original = bom + self.TEXT.encode(encoding)
                    path.write_bytes(original)
                    output = chunker.write_bundle(path, root / "bundle", max_chars=1000, overlap_chars=120)
                    m = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
                    expected = self.TEXT.replace("\r\n", "\n").replace("\r", "\n")
                    self.assertEqual(m["source_bytes_sha256"], chunker.sha256_bytes(original))
                    self.assertEqual(m["source_size_bytes"], len(original))
                    self.assertEqual(chunker.verify_bundle(output), chunker.sha256_text(expected))
                    self.assertNotIn(str(root), json.dumps(m))
                    self.assertGreater(m["chunk_count"], 1)

    def test_rejected_encoding_creates_no_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "invalid.txt"
            path.write_bytes(b"not utf-8: \xff")
            with contextlib.redirect_stdout(io.StringIO()) as log:
                code = chunker.main(["split", str(path), "--output", str(root / "bundle"), "--input-encoding", "utf-8"])
            self.assertEqual(code, 2)
            self.assertIn("ERROR:", log.getvalue())
            self.assertFalse((root / "bundle").exists())

    def test_cli_explicit_encoding_works_from_unrelated_cwd(self) -> None:
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cwd = root / "unrelated"; cwd.mkdir()
            path = root / "source export.txt"
            path.write_bytes(self.TEXT.encode("utf-16-be"))
            command = [sys.executable, str(ROOT / "src" / "large_text_chunker.py"), "split", str(path),
                       "--input-encoding", "utf-16-be", "--max-chars", "1000"]
            result = subprocess.run(command, cwd=cwd, text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            output = root / "source export_chunks"
            self.assertTrue((output / "manifest.json").is_file())
            self.assertEqual(list(cwd.iterdir()), [])
            verify = subprocess.run([sys.executable, str(ROOT / "src" / "large_text_chunker.py"), "verify", str(output)],
                                    cwd=cwd, text=True, capture_output=True, timeout=15)
            self.assertEqual(verify.returncode, 0, verify.stderr + verify.stdout)


class DeepReviewRegressionTests(unittest.TestCase):
    """Reproduced integrity and failure-boundary defects, not live user data."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source.txt"
        self.source.write_text("abcdef\n" * 800, encoding="utf-8")

    def bundle(self) -> tuple[Path, dict]:
        out = chunker.write_bundle(self.source, self.root / "bundle", max_chars=1000, overlap_chars=40)
        return out, json.loads((out / "manifest.json").read_text(encoding="utf-8"))

    def save_manifest(self, out: Path, manifest: dict) -> None:
        (out / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def test_unmarked_generic_unicode_requires_explicit_byte_order(self) -> None:
        for encoding in ("utf-16", "utf-32"):
            with self.subTest(encoding=encoding):
                self.source.write_bytes("ABC".encode(encoding + "-le"))
                with self.assertRaisesRegex(ValueError, "explicit"):
                    chunker.read_text_file(self.source, encoding)
                with self.assertRaisesRegex(ValueError, "explicit"):
                    chunker.write_bundle(self.source, self.root / "rejected", input_encoding=encoding)
                self.assertFalse((self.root / "rejected").exists())

    def test_newline_belongs_to_terminating_line(self) -> None:
        offsets = [1, 3]
        self.assertEqual([chunker.line_number_at(i, offsets) for i in range(5)], [1, 1, 2, 2, 3])

    def test_new_bundle_ranges_match_actual_characters(self) -> None:
        out, manifest = self.bundle()
        self.assertEqual(manifest["line_numbering"], chunker.LINE_NUMBERING)
        text, _, _ = chunker.read_text_file(self.source)
        for record in manifest["records"]:
            self.assertEqual(record["start_line"], 1 + text[:record["raw_start"]].count("\n"))
            self.assertEqual(record["end_line"], 1 + text[:record["raw_end"] - 1].count("\n"))
        self.assertEqual(chunker.verify_bundle(out), chunker.sha256_text(text))

    def test_legacy_line_convention_remains_verifiable(self) -> None:
        import bisect
        out, manifest = self.bundle()
        text, _, _ = chunker.read_text_file(self.source)
        newlines = [i for i, char in enumerate(text) if char == "\n"]
        manifest.pop("line_numbering")
        for record in manifest["records"]:
            record["start_line"] = bisect.bisect_right(newlines, record["raw_start"]) + 1
            record["end_line"] = bisect.bisect_right(newlines, record["raw_end"] - 1) + 1
        for version in ("1.0.0", "1.10.0", "1.11.0"):
            with self.subTest(version=version):
                manifest["tool_version"] = version
                self.save_manifest(out, manifest)
                self.assertEqual(chunker.verify_bundle(out), chunker.sha256_text(text))

    def test_tampered_source_ranges_rejected(self) -> None:
        out, manifest = self.bundle()
        manifest["records"][0]["end_line"] += 100
        self.save_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "line range"):
            chunker.verify_bundle(out)

    def test_missing_new_line_convention_rejected(self) -> None:
        out, manifest = self.bundle()
        manifest.pop("line_numbering")
        self.save_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "line-numbering"):
            chunker.verify_bundle(out)

    def test_tampered_overlap_rejected_even_with_updated_hash(self) -> None:
        out, manifest = self.bundle()
        record = manifest["records"][1]
        path = out / record["filename"]
        original = path.read_text(encoding="utf-8")
        prefix = record["overlap_prefix_characters"]
        changed = "X" * prefix + original[prefix:]
        path.write_text(changed, encoding="utf-8")
        record["output_sha256"] = chunker.sha256_text(changed)
        self.save_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "Overlap context"):
            chunker.verify_bundle(out)

    def test_missing_requested_overlap_rejected(self) -> None:
        out, manifest = self.bundle()
        record = manifest["records"][1]
        path = out / record["filename"]
        original = path.read_text(encoding="utf-8")
        changed = original[record["overlap_prefix_characters"]:]
        path.write_text(changed, encoding="utf-8")
        record.update(overlap_prefix_characters=0, output_characters=len(changed),
                      output_sha256=chunker.sha256_text(changed),
                      estimated_tokens=chunker.estimated_tokens(changed),
                      token_count=chunker.estimated_tokens(changed))
        self.save_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "Overlap context"):
            chunker.verify_bundle(out)

    def test_duplicate_keys_rejected_at_root_and_nested_levels(self) -> None:
        out, manifest = self.bundle()
        original = json.dumps(manifest)
        for key in ("chunk_count", "raw_start", "exact"):
            with self.subTest(key=key):
                mutated = original.replace(f'"{key}":', f'"{key}": null, "{key}":', 1)
                (out / "manifest.json").write_text(mutated, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "duplicate JSON"):
                    chunker.verify_bundle(out)

    def test_nonfinite_json_rejected(self) -> None:
        out, manifest = self.bundle()
        for invalid in ("NaN", "Infinity", "-Infinity"):
            with self.subTest(invalid=invalid):
                text = json.dumps(manifest)[:-1] + ', "unused": ' + invalid + '}'
                (out / "manifest.json").write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "non-finite"):
                    chunker.verify_bundle(out)

    def test_excessive_json_nesting_returns_clean_cli_error(self) -> None:
        out = self.root / "nested"; out.mkdir()
        (out / "manifest.json").write_text("[" * 1500 + "0" + "]" * 1500, encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = chunker.main(["verify", str(out)])
        self.assertEqual(code, 2)
        self.assertNotIn("Traceback", output.getvalue())

    def test_manifest_size_limit_is_enforced_on_actual_read(self) -> None:
        out, _ = self.bundle()
        (out / "manifest.json").write_bytes(b" " * (chunker.MAX_MANIFEST_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "safety limit"):
            chunker.verify_bundle(out)

    def test_current_token_metadata_cannot_be_silently_removed(self) -> None:
        out, manifest = self.bundle()
        manifest.pop("tokenizer")
        self.save_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "tokenizer metadata"):
            chunker.verify_bundle(out)

    def test_estimate_mode_cannot_claim_exact_token_accounting(self) -> None:
        out, manifest = self.bundle()
        manifest["tokenizer"].update(method="tiktoken-exact", exact=True)
        self.save_manifest(out, manifest)
        with self.assertRaisesRegex(ValueError, "estimate mode"):
            chunker.verify_bundle(out)

    def test_failed_write_retains_incomplete_marker_and_source(self) -> None:
        original = self.source.read_bytes()
        real_write = chunker.atomic_write
        def fail_on_chunk(path: Path, content: str) -> None:
            if path.name.startswith("chunk_"):
                raise OSError("fixture disk failure")
            real_write(path, content)
        with mock.patch.object(chunker, "atomic_write", side_effect=fail_on_chunk):
            with self.assertRaises(OSError):
                chunker.write_bundle(self.source, self.root / "failed")
        self.assertEqual(self.source.read_bytes(), original)
        self.assertTrue((self.root / "failed" / chunker.INCOMPLETE_MARKER).is_file())
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            chunker.verify_bundle(self.root / "failed")

    def test_failed_verification_does_not_mark_bundle_complete(self) -> None:
        with mock.patch.object(chunker, "_verify_bundle_contents", side_effect=ValueError("fixture failure")):
            with self.assertRaises(ValueError):
                chunker.write_bundle(self.source, self.root / "failed")
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            chunker.verify_bundle(self.root / "failed")

    def test_success_clears_only_its_incomplete_marker(self) -> None:
        out, _ = self.bundle()
        self.assertFalse((out / chunker.INCOMPLETE_MARKER).exists())
        self.assertEqual(list(out.glob(".chunker-*.tmp")), [])
        chunker.verify_bundle(out)

    def test_atomic_write_failure_preserves_target_and_removes_own_temp(self) -> None:
        target = self.root / "target.txt"; target.write_text("preserve", encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=OSError("fixture replace failure")):
            with self.assertRaises(OSError):
                chunker.atomic_write(target, "replacement")
        self.assertEqual(target.read_text(encoding="utf-8"), "preserve")
        self.assertEqual(list(self.root.glob(".chunker-*.tmp")), [])

    def test_predictable_legacy_temp_file_is_not_touched(self) -> None:
        sentinel = self.root / ".target.txt.tmp"
        sentinel.write_text("user data", encoding="utf-8")
        chunker.atomic_write(self.root / "target.txt", "new")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "user data")

    def test_concurrent_output_collision_uses_next_exclusive_slot(self) -> None:
        original = Path.mkdir
        base = self.root / "bundle"
        raced = False
        def mkdir(path: Path, *args, **kwargs):
            nonlocal raced
            if path == base and not raced:
                raced = True
                original(path)
                (path / "user.txt").write_text("preserve", encoding="utf-8")
                raise FileExistsError("fixture concurrent creation")
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, "mkdir", new=mkdir):
            output = chunker.unique_output_dir(base)
        self.assertEqual(output.name, "bundle_2")
        self.assertEqual((base / "user.txt").read_text(encoding="utf-8"), "preserve")

    def test_output_collision_retry_has_a_limit(self) -> None:
        with mock.patch.object(chunker, "MAX_OUTPUT_COLLISIONS", 3):
            with mock.patch.object(Path, "mkdir", side_effect=FileExistsError("fixture")) as calls:
                with self.assertRaisesRegex(ValueError, "collision limit"):
                    chunker.unique_output_dir(self.root / "blocked")
            self.assertEqual(calls.call_count, 3)

    def test_linked_output_parent_is_rejected_without_writing(self) -> None:
        target = self.root / "external"; target.mkdir()
        link = self.root / "link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("OS does not allow creating symbolic links in this test environment")
        with self.assertRaisesRegex(ValueError, "links or reparse"):
            chunker.write_bundle(self.source, link / "bundle")
        self.assertEqual(list(target.iterdir()), [])

    def test_reparse_output_parent_is_rejected(self) -> None:
        parent = self.root / "linked"; parent.mkdir()
        with mock.patch.object(chunker, "_is_reparse_point", return_value=True):
            with self.assertRaisesRegex(ValueError, "reparse"):
                chunker.unique_output_dir(parent / "bundle")
        self.assertEqual(list(parent.iterdir()), [])

    def test_nonregular_input_rejected_before_reading(self) -> None:
        with mock.patch.object(Path, "read_bytes") as read:
            with self.assertRaisesRegex(ValueError, "regular"):
                chunker.read_text_file(self.root)
        read.assert_not_called()

    def test_seeded_unicode_round_trips_preserve_text(self) -> None:
        import random
        randomizer = random.Random(14711)
        for case in range(30):
            text = "".join(randomizer.choices("abcXYZ .!?\n\ré東京😀", k=3000 + case * 21))
            self.source.write_bytes(text.encode("utf-16" if case % 2 else "utf-8"))
            out = chunker.write_bundle(self.source, self.root / "random", max_chars=1000,
                                       overlap_chars=randomizer.choice([0, 1, 40, 999]))
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            self.assertEqual(chunker.verify_bundle(out), chunker.sha256_text(normalized))


if __name__ == "__main__":
    unittest.main()
