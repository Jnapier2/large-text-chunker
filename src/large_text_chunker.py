#!/usr/bin/env python3
"""Split large text files into ordered, verifiable context-sized chunks.

Copyright 2026 Gateway Information Group LLC. All Rights Reserved.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence

VERSION = "1.0.0"
DEFAULT_MAX_CHARS = 12_000
DEFAULT_OVERLAP_CHARS = 600
MIN_MAX_CHARS = 1_000
MANIFEST_SCHEMA = "large-text-chunker-manifest-v1"
MAX_MANIFEST_BYTES = 2_000_000
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_FORBIDDEN_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')
WINDOWS_RESERVED_BASENAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)


@dataclass(frozen=True)
class ChunkRecord:
    number: int
    filename: str
    raw_start: int
    raw_end: int
    raw_characters: int
    overlap_prefix_characters: int
    output_characters: int
    start_line: int
    end_line: int
    raw_sha256: str
    output_sha256: str
    estimated_tokens: int


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def estimated_tokens(value: str) -> int:
    """Return a deliberately conservative, dependency-free token estimate."""
    return math.ceil(len(value.encode("utf-8")) / 3)


def read_text_file(path: Path) -> tuple[str, str, bytes]:
    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        raise ValueError("Input appears to be binary; provide a text export instead.")
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        encoding = "latin-1"
        text = raw.decode(encoding)
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    return normalized, encoding, raw


def split_long_unit(
    unit: str, absolute_start: int, max_chars: int
) -> Iterable[tuple[int, int, str]]:
    sentence_pattern = re.compile(r".*?(?:(?<=[.!?])\s+|\n+|$)", re.DOTALL)
    pieces = [
        (absolute_start + match.start(), absolute_start + match.end(), match.group(0))
        for match in sentence_pattern.finditer(unit)
        if match.group(0)
    ]
    if not pieces:
        pieces = [(absolute_start, absolute_start + len(unit), unit)]

    buffer = ""
    buffer_start: int | None = None
    buffer_end: int | None = None
    for start, end, piece in pieces:
        if len(piece) > max_chars:
            if buffer:
                yield buffer_start if buffer_start is not None else start, buffer_end or start, buffer
                buffer = ""
                buffer_start = None
                buffer_end = None
            for offset in range(0, len(piece), max_chars):
                part = piece[offset : offset + max_chars]
                yield start + offset, start + offset + len(part), part
            continue

        if buffer and len(buffer) + len(piece) > max_chars:
            yield buffer_start if buffer_start is not None else start, buffer_end or start, buffer
            buffer = piece
            buffer_start = start
            buffer_end = end
        else:
            if buffer_start is None:
                buffer_start = start
            buffer += piece
            buffer_end = end

    if buffer:
        yield buffer_start if buffer_start is not None else absolute_start, buffer_end or absolute_start, buffer


def split_to_units(text: str, max_chars: int) -> Iterable[tuple[int, int, str]]:
    paragraph_pattern = re.compile(r".*?(?:\n\s*\n|$)", re.DOTALL)
    for match in paragraph_pattern.finditer(text):
        unit = match.group(0)
        if not unit:
            continue
        if len(unit) <= max_chars:
            yield match.start(), match.end(), unit
        else:
            yield from split_long_unit(unit, match.start(), max_chars)


def build_chunks(text: str, max_chars: int) -> list[tuple[int, int, str]]:
    if max_chars < MIN_MAX_CHARS:
        raise ValueError(f"max_chars must be at least {MIN_MAX_CHARS}")
    if not text:
        raise ValueError("Input is empty; no chunks can be created.")

    chunks: list[tuple[int, int, str]] = []
    current = ""
    current_start: int | None = None
    current_end: int | None = None
    for start, end, unit in split_to_units(text, max_chars):
        if current and len(current) + len(unit) > max_chars:
            chunks.append((current_start or 0, current_end or 0, current))
            current = ""
            current_start = None
            current_end = None
        if current_start is None:
            current_start = start
        current += unit
        current_end = end

    if current:
        chunks.append((current_start or 0, current_end or len(text), current))
    if "".join(chunk[2] for chunk in chunks) != text:
        raise RuntimeError("Internal reconstruction check failed before writing output.")
    return chunks


def unique_output_dir(base: Path) -> Path:
    candidate = base
    counter = 2
    while candidate.exists():
        candidate = base.with_name(f"{base.name}_{counter}")
        counter += 1
    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def line_number_at(offset: int, newline_offsets: list[int]) -> int:
    return bisect.bisect_right(newline_offsets, max(0, offset)) + 1


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def _required_int(
    mapping: dict[str, Any],
    field: str,
    *,
    label: str,
    minimum: int = 0,
) -> int:
    value = mapping.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label} {field} must be an integer of at least {minimum}")
    return value


def _required_sha256(mapping: dict[str, Any], field: str, *, label: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} {field} must be a lowercase SHA-256 digest")
    return value


def _simple_chunk_filename(value: Any, *, record_number: int) -> str:
    if not isinstance(value, str) or not value or len(value) > 255 or value in {".", ".."}:
        raise ValueError(f"Record {record_number} filename must be a simple relative filename")
    if any(
        ord(character) < 32 or character in WINDOWS_FORBIDDEN_FILENAME_CHARACTERS
        for character in value
    ):
        raise ValueError(
            f"Record {record_number} filename must be a simple relative filename; "
            "Windows-forbidden characters are not allowed"
        )
    if value.endswith((".", " ")):
        raise ValueError(f"Record {record_number} filename may not end in a dot or space")
    windows_basename = value.split(".", 1)[0].upper()
    if windows_basename in WINDOWS_RESERVED_BASENAMES:
        raise ValueError(f"Record {record_number} filename uses a reserved Windows device name")
    for path_type in (PurePosixPath, PureWindowsPath):
        parsed = path_type(value)
        if parsed.is_absolute() or parsed.drive or len(parsed.parts) != 1:
            raise ValueError(f"Record {record_number} filename must be a simple relative filename")
    return value


def _is_reparse_point(info: os.stat_result) -> bool:
    attributes = getattr(info, "st_file_attributes", 0)
    marker = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(marker and attributes & marker)


def _checked_regular_file(bundle: Path, filename: str, *, label: str) -> Path:
    candidate = bundle / filename
    try:
        info = os.lstat(candidate)
    except OSError as exc:
        raise ValueError(f"{label} is unavailable: {filename}") from exc
    if stat.S_ISLNK(info.st_mode) or _is_reparse_point(info):
        raise ValueError(f"{label} may not be a link or reparse point: {filename}")
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"{label} is not a regular file: {filename}")
    resolved = candidate.resolve(strict=True)
    try:
        resolved.relative_to(bundle)
    except ValueError as exc:
        raise ValueError(f"{label} resolves outside the bundle: {filename}") from exc
    return resolved


def write_bundle(
    source: Path,
    output: Path | None = None,
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    overlap_chars: int = DEFAULT_OVERLAP_CHARS,
) -> Path:
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    source = source.resolve(strict=True)
    text, encoding, raw_bytes = read_text_file(source)
    raw_chunks = build_chunks(text, max_chars)
    base = output.resolve() if output else source.parent / f"{source.stem}_chunks"
    output_dir = unique_output_dir(base)
    newline_offsets = [match.start() for match in re.finditer("\n", text)]

    records: list[ChunkRecord] = []
    previous_raw = ""
    for index, (start, end, raw_chunk) in enumerate(raw_chunks, start=1):
        prefix = previous_raw[-overlap_chars:] if overlap_chars else ""
        rendered = prefix + raw_chunk
        filename = f"chunk_{index:03d}_of_{len(raw_chunks):03d}.txt"
        atomic_write(output_dir / filename, rendered)
        records.append(
            ChunkRecord(
                number=index,
                filename=filename,
                raw_start=start,
                raw_end=end,
                raw_characters=len(raw_chunk),
                overlap_prefix_characters=len(prefix),
                output_characters=len(rendered),
                start_line=line_number_at(start, newline_offsets),
                end_line=line_number_at(max(start, end - 1), newline_offsets),
                raw_sha256=sha256_text(raw_chunk),
                output_sha256=sha256_text(rendered),
                estimated_tokens=estimated_tokens(rendered),
            )
        )
        previous_raw = raw_chunk

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "tool_version": VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_name": source.name,
        "source_encoding": encoding,
        "source_bytes_sha256": sha256_bytes(raw_bytes),
        "normalized_text_sha256": sha256_text(text),
        "normalized_newlines": True,
        "max_characters_per_raw_chunk": max_chars,
        "requested_overlap_characters": overlap_chars,
        "chunk_count": len(records),
        "records": [asdict(record) for record in records],
    }
    atomic_write(output_dir / "manifest.json", json.dumps(manifest, indent=2) + "\n")

    index = [
        "# Chunk index",
        "",
        f"Source: `{source.name}`",
        f"Chunks: {len(records)}",
        f"Normalized text SHA-256: `{manifest['normalized_text_sha256']}`",
        "",
        "Each file begins with the context overlap from the preceding raw chunk. The manifest records the exact prefix length so the normalized source can be reconstructed and verified.",
        "",
        "| # | File | Source lines | Raw chars | Overlap | Estimated tokens |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for record in records:
        index.append(
            f"| {record.number} | `{record.filename}` | {record.start_line}-{record.end_line} | "
            f"{record.raw_characters} | {record.overlap_prefix_characters} | {record.estimated_tokens} |"
        )
    index.extend(["", "Run `python src/large_text_chunker.py verify <bundle>` before sharing the bundle.", ""])
    atomic_write(output_dir / "index.md", "\n".join(index))
    verify_bundle(output_dir)
    return output_dir


def verify_bundle(bundle: Path) -> str:
    bundle = bundle.resolve(strict=True)
    if not bundle.is_dir():
        raise ValueError("Bundle path is not a directory")
    manifest_path = _checked_regular_file(bundle, "manifest.json", label="Manifest")
    if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise ValueError(f"Manifest exceeds the {MAX_MANIFEST_BYTES}-byte safety limit")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("Manifest root must be a JSON object")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError("Unsupported or missing manifest schema")

    for field in ("tool_version", "created_utc", "source_name", "source_encoding"):
        value = manifest.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Manifest {field} must be a non-empty string")
    if not isinstance(manifest.get("normalized_newlines"), bool):
        raise ValueError("Manifest normalized_newlines must be a boolean")
    _required_sha256(manifest, "source_bytes_sha256", label="Manifest")
    normalized_text_sha256 = _required_sha256(manifest, "normalized_text_sha256", label="Manifest")
    max_characters = _required_int(
        manifest,
        "max_characters_per_raw_chunk",
        label="Manifest",
        minimum=MIN_MAX_CHARS,
    )
    requested_overlap = _required_int(
        manifest,
        "requested_overlap_characters",
        label="Manifest",
    )
    if requested_overlap >= max_characters:
        raise ValueError("Manifest requested overlap must be smaller than the raw chunk limit")
    chunk_count = _required_int(manifest, "chunk_count", label="Manifest", minimum=1)
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("Manifest records must be a JSON array")
    if len(records) != chunk_count:
        raise ValueError("Manifest chunk_count does not match the number of records")

    reconstructed: list[str] = []
    filenames: set[str] = set()
    expected_raw_start = 0
    for index, record_value in enumerate(records, start=1):
        if not isinstance(record_value, dict):
            raise ValueError(f"Record {index} must be a JSON object")
        record: dict[str, Any] = record_value
        number = _required_int(record, "number", label=f"Record {index}", minimum=1)
        if number != index:
            raise ValueError(f"Record {index} number must match its sequence position")
        filename = _simple_chunk_filename(record.get("filename"), record_number=index)
        filename_key = filename.casefold()
        if filename_key in filenames:
            raise ValueError(f"Record {index} repeats chunk filename: {filename}")
        filenames.add(filename_key)

        raw_start = _required_int(record, "raw_start", label=f"Record {index}")
        raw_end = _required_int(record, "raw_end", label=f"Record {index}", minimum=1)
        raw_characters = _required_int(record, "raw_characters", label=f"Record {index}", minimum=1)
        prefix_length = _required_int(record, "overlap_prefix_characters", label=f"Record {index}")
        output_characters = _required_int(record, "output_characters", label=f"Record {index}", minimum=1)
        start_line = _required_int(record, "start_line", label=f"Record {index}", minimum=1)
        end_line = _required_int(record, "end_line", label=f"Record {index}", minimum=1)
        _required_int(record, "estimated_tokens", label=f"Record {index}", minimum=1)
        output_sha256 = _required_sha256(record, "output_sha256", label=f"Record {index}")
        raw_sha256 = _required_sha256(record, "raw_sha256", label=f"Record {index}")

        if raw_start != expected_raw_start or raw_end <= raw_start:
            raise ValueError(f"Record {index} raw offsets are not contiguous and increasing")
        if raw_characters != raw_end - raw_start or raw_characters > max_characters:
            raise ValueError(f"Record {index} raw character count is inconsistent")
        if prefix_length > requested_overlap or output_characters != raw_characters + prefix_length:
            raise ValueError(f"Record {index} overlap or output character count is inconsistent")
        if index == 1 and prefix_length != 0:
            raise ValueError("Record 1 may not declare an overlap prefix")
        if end_line < start_line:
            raise ValueError(f"Record {index} line range is invalid")

        chunk_path = _checked_regular_file(bundle, filename, label=f"Record {index} chunk")
        with chunk_path.open("r", encoding="utf-8", newline="") as handle:
            content = handle.read()
        if sha256_text(content) != output_sha256:
            raise ValueError(f"Output hash mismatch: {filename}")
        if len(content) != output_characters:
            raise ValueError(f"Output character count mismatch: {filename}")
        if prefix_length > len(content):
            raise ValueError(f"Record {index} overlap prefix exceeds its chunk length")
        raw_content = content[prefix_length:]
        if len(raw_content) != raw_characters:
            raise ValueError(f"Raw character count mismatch: {filename}")
        if sha256_text(raw_content) != raw_sha256:
            raise ValueError(f"Raw content hash mismatch: {filename}")
        reconstructed.append(raw_content)
        expected_raw_start = raw_end

    reconstructed_hash = sha256_text("".join(reconstructed))
    if reconstructed_hash != normalized_text_sha256:
        raise ValueError("Reconstructed source hash does not match the manifest")
    return reconstructed_hash


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Split large text into ordered, overlap-aware, verifiable chunks."
    )
    parser.add_argument("--version", action="version", version=VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)
    split_parser = subparsers.add_parser("split", help="Create a new chunk bundle")
    split_parser.add_argument("source", type=Path)
    split_parser.add_argument("--output", type=Path)
    split_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    split_parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP_CHARS)
    verify_parser = subparsers.add_parser("verify", help="Verify and reconstruct a bundle in memory")
    verify_parser.add_argument("bundle", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "split":
            destination = write_bundle(
                args.source,
                args.output,
                max_chars=args.max_chars,
                overlap_chars=args.overlap,
            )
            print(f"Created and verified: {destination}")
        else:
            digest = verify_bundle(args.bundle)
            print(f"PASS: normalized source SHA-256 {digest}")
        return 0
    except (KeyError, OSError, OverflowError, TypeError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
