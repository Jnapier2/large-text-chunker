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
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

VERSION = "1.0.0"
DEFAULT_MAX_CHARS = 12_000
DEFAULT_OVERLAP_CHARS = 600
MIN_MAX_CHARS = 1_000


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
    encodings = ("utf-8-sig", "utf-8", "cp1252", "latin-1")
    last_error: UnicodeDecodeError | None = None
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
            normalized = text.replace("\r\n", "\n").replace("\r", "\n")
            return normalized, encoding, raw
        except UnicodeDecodeError as exc:
            last_error = exc
    raise ValueError(f"Unable to decode input as text: {last_error}")


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
        "schema": "large-text-chunker-manifest-v1",
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
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema") != "large-text-chunker-manifest-v1":
        raise ValueError("Unsupported or missing manifest schema")

    reconstructed: list[str] = []
    for record in manifest.get("records", []):
        content = (bundle / record["filename"]).read_text(encoding="utf-8")
        if sha256_text(content) != record["output_sha256"]:
            raise ValueError(f"Output hash mismatch: {record['filename']}")
        prefix_length = int(record["overlap_prefix_characters"])
        raw_content = content[prefix_length:]
        if sha256_text(raw_content) != record["raw_sha256"]:
            raise ValueError(f"Raw content hash mismatch: {record['filename']}")
        reconstructed.append(raw_content)

    reconstructed_hash = sha256_text("".join(reconstructed))
    if reconstructed_hash != manifest.get("normalized_text_sha256"):
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
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
