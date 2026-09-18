#!/usr/bin/env python3
"""Split large text files into ordered, verifiable context-sized chunks.

Copyright © 2026 Gateway Information Group LLC. All rights reserved.
"""

from __future__ import annotations

import argparse
import bisect
import codecs
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Sequence

VERSION = "1.11.1"
# Input decoding is separate from the optional token-counting encoding.
INPUT_ENCODINGS = (
    "auto", "utf-8", "utf-8-sig", "utf-16", "utf-16-le", "utf-16-be",
    "utf-32", "utf-32-le", "utf-32-be", "cp1252", "latin-1",
)
DEFAULT_MAX_CHARS = 12_000
DEFAULT_OVERLAP_CHARS = 600
DEFAULT_TOKEN_COUNT_MODE = "estimate"
DEFAULT_TOKENIZER_ENCODING = "o200k_base"
OPTIONAL_TIKTOKEN_VERSION = "0.13.0"
CHATGPT_UPLOAD_POLICY_REVIEWED_UTC = "2026-07-18T05:52:18Z"
CHATGPT_UPLOAD_POLICY_FRESHNESS_DAYS = 30
CHATGPT_FILE_SIZE_CAP_BYTES = 512 * 1024 * 1024
CHATGPT_TEXT_TOKEN_CAP = 2_000_000
MIN_MAX_CHARS = 1_000
MANIFEST_SCHEMA = "large-text-chunker-manifest-v1"
MAX_MANIFEST_BYTES = 2_000_000
MAX_OUTPUT_COLLISIONS = 1000
INCOMPLETE_MARKER = ".incomplete"
LINE_NUMBERING = "inclusive-character-lines-v2"
LEGACY_LINE_VERSIONS = {"1.0.0", "1.10.0", "1.11.0"}
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
    token_count: int
    token_count_method: str
    tokenizer_encoding: str


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def estimated_tokens(value: str) -> int:
    """Return a dependency-free estimate, not a guaranteed token upper bound."""
    return math.ceil(len(value.encode("utf-8")) / 3)


def _load_tiktoken_encoding(encoding_name: str) -> tuple[Any, str]:
    """Load the optional tokenizer without installing packages or hiding failures."""
    import tiktoken  # type: ignore[import-not-found]
    from importlib.metadata import version as package_version

    return tiktoken.get_encoding(encoding_name), package_version("tiktoken")


class TokenCounter:
    """Count tokens exactly when requested, with an explicit offline fallback."""

    def __init__(self, requested_mode: str, encoding_name: str) -> None:
        mode = str(requested_mode or DEFAULT_TOKEN_COUNT_MODE).strip().lower()
        if mode not in {"auto", "exact", "estimate"}:
            raise ValueError("token_count_mode must be one of: auto, exact, estimate")

        encoding = str(encoding_name or DEFAULT_TOKENIZER_ENCODING).strip()
        if not encoding or len(encoding) > 64 or re.fullmatch(r"[A-Za-z0-9_.-]+", encoding) is None:
            raise ValueError(
                "tokenizer_encoding must use letters, numbers, dots, dashes, or underscores"
            )

        self.requested_mode = mode
        self.encoding_name = encoding
        self.method = "estimated-utf8-bytes-div-3"
        self.package_version: str | None = None
        self.warning: str | None = None
        self.fallback_reason: str | None = None
        self._encoding: Any = None

        if mode == "estimate":
            return

        try:
            self._encoding, self.package_version = _load_tiktoken_encoding(encoding)
            self.method = "tiktoken-exact"
        except Exception as exc:
            self.fallback_reason = type(exc).__name__
            guidance = (
                f"Optional tiktoken=={OPTIONAL_TIKTOKEN_VERSION} could not initialize "
                f"the {encoding} encoding ({self.fallback_reason})."
            )
            if mode == "exact":
                raise RuntimeError(
                    f"{guidance} Install it explicitly with "
                    f"'python -m pip install tiktoken=={OPTIONAL_TIKTOKEN_VERSION}' and retry."
                ) from None
            self.warning = f"{guidance} Using the offline estimate instead."

    @property
    def exact(self) -> bool:
        return self.method == "tiktoken-exact" and self._encoding is not None

    def count(self, text: str) -> int:
        if not text:
            return 0
        if self.exact:
            return len(self._encoding.encode_ordinary(text))
        return estimated_tokens(text)

    def snapshot(self) -> dict[str, Any]:
        return {
            "requested_mode": self.requested_mode,
            "method": self.method,
            "exact": self.exact,
            "encoding": self.encoding_name,
            "package": "tiktoken" if self.exact else None,
            "package_version": self.package_version,
            "recommended_optional_version": OPTIONAL_TIKTOKEN_VERSION,
            "warning": self.warning,
            "fallback_reason": self.fallback_reason,
            "automatic_install": False,
        }


def chatgpt_upload_advisory(
    source_size_bytes: int,
    source_token_count: int,
    counter: TokenCounter,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a dated, nonblocking comparison with reviewed upload limits."""
    reviewed = datetime.fromisoformat(CHATGPT_UPLOAD_POLICY_REVIEWED_UTC.replace("Z", "+00:00"))
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("Upload-advisory time must include a timezone")
    age_days = max(0, (current.astimezone(timezone.utc) - reviewed).days)
    status = "current" if age_days <= CHATGPT_UPLOAD_POLICY_FRESHNESS_DAYS else "review_due"
    within_size = source_size_bytes <= CHATGPT_FILE_SIZE_CAP_BYTES
    within_tokens = source_token_count <= CHATGPT_TEXT_TOKEN_CAP
    if within_size and within_tokens:
        assessment = "within_reviewed_caps" if counter.exact else "estimated_within_reviewed_caps"
    else:
        assessment = "exceeds_reviewed_cap" if counter.exact else "estimated_exceeds_reviewed_cap"

    return {
        "status": status,
        "advisory_only": True,
        "reviewed_utc": CHATGPT_UPLOAD_POLICY_REVIEWED_UTC,
        "age_days": age_days,
        "freshness_days": CHATGPT_UPLOAD_POLICY_FRESHNESS_DAYS,
        "documented_file_size_cap_bytes": CHATGPT_FILE_SIZE_CAP_BYTES,
        "documented_text_document_token_cap": CHATGPT_TEXT_TOKEN_CAP,
        "source_size_bytes": source_size_bytes,
        "source_token_count": source_token_count,
        "token_count_method": counter.method,
        "tokenizer_encoding": counter.encoding_name,
        "within_size_cap": within_size,
        "within_token_cap": within_tokens,
        "assessment": assessment,
        "note": (
            "Reviewed upload caps do not guarantee plan eligibility, successful ingestion, "
            "or that all content enters active model context."
        ),
    }


def read_text_file(
    path: Path, input_encoding: str = "auto"
) -> tuple[str, str, bytes]:
    """Decode text once, honor byte-order marks, and reject decoded NULs.

    Auto mode retains the public edition's UTF-8/legacy fallback for unmarked
    files. Unmarked UTF-16/32 must be selected explicitly; no heuristic guesses
    or replacement characters are used to make invalid input appear valid.
    """
    if input_encoding not in INPUT_ENCODINGS:
        raise ValueError("Unsupported input encoding; use a documented encoding name.")
    if not path.is_file():
        raise ValueError("Input must be a regular text file")
    raw = path.read_bytes()
    # UTF-32 LE starts with the UTF-16 LE marker: longest markers go first.
    markers = (
        (codecs.BOM_UTF32_LE, "utf-32", {"utf-32", "utf-32-le"}),
        (codecs.BOM_UTF32_BE, "utf-32", {"utf-32", "utf-32-be"}),
        (codecs.BOM_UTF8, "utf-8-sig", {"utf-8", "utf-8-sig"}),
        (codecs.BOM_UTF16_LE, "utf-16", {"utf-16", "utf-16-le"}),
        (codecs.BOM_UTF16_BE, "utf-16", {"utf-16", "utf-16-be"}),
    )
    marked_encoding = None
    for marker, encoding, compatible in markers:
        if raw.startswith(marker):
            if input_encoding != "auto" and input_encoding not in compatible:
                raise ValueError("Selected input encoding conflicts with the byte-order mark.")
            marked_encoding = encoding
            break
    if marked_encoding is None and input_encoding in {"utf-16", "utf-32"}:
        raise ValueError("Unmarked UTF-16/32 requires an explicit little- or big-endian encoding.")
    if marked_encoding is not None or input_encoding != "auto":
        encoding = marked_encoding or input_encoding
        try:
            text = raw.decode(encoding, errors="strict")
        except UnicodeError:
            # Do not disclose input bytes or fall back after an explicit choice.
            raise ValueError("Input does not decode using its selected or marked encoding.") from None
    else:
        for encoding in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                text = raw.decode(encoding, errors="strict")
                break
            except UnicodeDecodeError:
                continue
    # Check the whole decoded document, not a raw byte prefix. Unicode byte
    # encodings legitimately contain zero bytes, but a NUL character is rejected.
    if "\x00" in text:
        raise ValueError("Decoded input contains NUL characters and may be binary.")
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
    # Preserve source-adjacent/explicit output semantics, but never silently
    # follow a linked output destination. This is not a hostile-writer sandbox.
    base = base.absolute()
    for component in (base, *base.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or _is_reparse_point(info):
            raise ValueError("Output destination may not contain links or reparse points")
    for counter in range(1, MAX_OUTPUT_COLLISIONS + 1):
        candidate = base if counter == 1 else base.with_name(f"{base.name}_{counter}")
        try:
            candidate.mkdir(parents=True, exist_ok=False)
            return candidate
        except FileExistsError:
            # Exclusive creation, not a separate existence check, owns the slot.
            continue
    raise ValueError("Output naming collision limit reached; choose another destination")


def line_number_at(offset: int, newline_offsets: list[int]) -> int:
    # The newline character itself belongs to the line it terminates.
    return bisect.bisect_left(newline_offsets, max(0, offset)) + 1


def atomic_write(path: Path, content: str) -> None:
    # Random exclusive temporary files cannot follow an old predictable .tmp
    # symlink. Only this invocation's temporary file is removed on failure.
    descriptor, name = tempfile.mkstemp(prefix=".chunker-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Manifest contains a duplicate JSON field")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise ValueError("Manifest contains a non-finite JSON value")


def _finite_json_float(value: str) -> float:
    """Reject overflowed numeric literals as well as named JSON constants."""
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Manifest contains a non-finite JSON value")
    return result


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


def _required_text(mapping: dict[str, Any], field: str, *, label: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} {field} must be a non-empty string")
    return value


def _validate_token_metadata(manifest: dict[str, Any]) -> tuple[str, str, int] | None:
    """Validate additive v1.10 token metadata while retaining v1.0 bundle support."""
    tokenizer_value = manifest.get("tokenizer")
    if tokenizer_value is None:
        if manifest.get("tool_version") != "1.0.0":
            raise ValueError("Manifest tokenizer metadata is required for this version")
        return None
    if not isinstance(tokenizer_value, dict):
        raise ValueError("Manifest tokenizer must be a JSON object")
    tokenizer: dict[str, Any] = tokenizer_value

    requested_mode = _required_text(tokenizer, "requested_mode", label="Manifest tokenizer")
    if requested_mode not in {"auto", "exact", "estimate"}:
        raise ValueError("Manifest tokenizer requested_mode is unsupported")
    method = _required_text(tokenizer, "method", label="Manifest tokenizer")
    if method not in {"estimated-utf8-bytes-div-3", "tiktoken-exact"}:
        raise ValueError("Manifest tokenizer method is unsupported")
    encoding = _required_text(tokenizer, "encoding", label="Manifest tokenizer")
    if len(encoding) > 64 or re.fullmatch(r"[A-Za-z0-9_.-]+", encoding) is None:
        raise ValueError("Manifest tokenizer encoding is invalid")
    exact = tokenizer.get("exact")
    if not isinstance(exact, bool) or exact != (method == "tiktoken-exact"):
        raise ValueError("Manifest tokenizer exact flag does not match its method")
    if requested_mode == "exact" and not exact:
        raise ValueError("Manifest exact token mode may not record an estimated fallback")
    if requested_mode == "estimate" and exact:
        raise ValueError("Manifest estimate mode may not claim exact token accounting")
    if tokenizer.get("automatic_install") is not False:
        raise ValueError("Manifest tokenizer must explicitly disable automatic installation")
    for field in ("package", "package_version", "warning", "fallback_reason"):
        value = tokenizer.get(field)
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError(f"Manifest tokenizer {field} must be null or a non-empty string")
    if exact and (
        tokenizer.get("package") != "tiktoken"
        or not isinstance(tokenizer.get("package_version"), str)
    ):
        raise ValueError("Manifest exact token mode must identify its tiktoken version")

    source_size_bytes = _required_int(manifest, "source_size_bytes", label="Manifest", minimum=1)
    source_token_count = _required_int(manifest, "source_token_count", label="Manifest", minimum=1)
    advisory_value = manifest.get("chatgpt_upload_advisory")
    if not isinstance(advisory_value, dict):
        raise ValueError("Manifest chatgpt_upload_advisory must be a JSON object")
    advisory: dict[str, Any] = advisory_value
    if advisory.get("status") not in {"current", "review_due"}:
        raise ValueError("Manifest upload advisory status is invalid")
    if advisory.get("advisory_only") is not True:
        raise ValueError("Manifest upload guidance must be advisory only")
    reviewed_utc = _required_text(advisory, "reviewed_utc", label="Manifest upload advisory")
    try:
        reviewed = datetime.fromisoformat(reviewed_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Manifest upload advisory reviewed_utc is invalid") from exc
    if reviewed.tzinfo is None:
        raise ValueError("Manifest upload advisory reviewed_utc must include a timezone")
    age_days = _required_int(advisory, "age_days", label="Manifest upload advisory")
    freshness_days = _required_int(
        advisory, "freshness_days", label="Manifest upload advisory", minimum=1
    )
    expected_status = "current" if age_days <= freshness_days else "review_due"
    if advisory.get("status") != expected_status:
        raise ValueError("Manifest upload advisory status conflicts with its recorded age")
    size_cap = _required_int(
        advisory, "documented_file_size_cap_bytes", label="Manifest upload advisory", minimum=1
    )
    token_cap = _required_int(
        advisory,
        "documented_text_document_token_cap",
        label="Manifest upload advisory",
        minimum=1,
    )
    advisory_source_size = _required_int(
        advisory, "source_size_bytes", label="Manifest upload advisory", minimum=1
    )
    if advisory_source_size != source_size_bytes:
        raise ValueError("Manifest upload advisory source size conflicts with the manifest")
    advisory_source_tokens = _required_int(
        advisory, "source_token_count", label="Manifest upload advisory", minimum=1
    )
    if advisory_source_tokens != source_token_count:
        raise ValueError("Manifest upload advisory token count conflicts with the manifest")
    if _required_text(advisory, "token_count_method", label="Manifest upload advisory") != method:
        raise ValueError("Manifest upload advisory token method conflicts with the tokenizer")
    if _required_text(advisory, "tokenizer_encoding", label="Manifest upload advisory") != encoding:
        raise ValueError("Manifest upload advisory encoding conflicts with the tokenizer")
    for field, expected in (
        ("within_size_cap", source_size_bytes <= size_cap),
        ("within_token_cap", source_token_count <= token_cap),
    ):
        value = advisory.get(field)
        if not isinstance(value, bool) or value != expected:
            raise ValueError(f"Manifest upload advisory {field} is inconsistent")
    expected_assessment = (
        "within_reviewed_caps" if exact else "estimated_within_reviewed_caps"
    )
    if not (source_size_bytes <= size_cap and source_token_count <= token_cap):
        expected_assessment = "exceeds_reviewed_cap" if exact else "estimated_exceeds_reviewed_cap"
    assessment = _required_text(advisory, "assessment", label="Manifest upload advisory")
    if assessment != expected_assessment:
        raise ValueError("Manifest upload advisory assessment is inconsistent")
    _required_text(advisory, "note", label="Manifest upload advisory")
    return method, encoding, source_token_count


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
    token_count_mode: str = DEFAULT_TOKEN_COUNT_MODE,
    tokenizer_encoding: str = DEFAULT_TOKENIZER_ENCODING,
    input_encoding: str = "auto",
) -> Path:
    if overlap_chars < 0:
        raise ValueError("overlap_chars cannot be negative")
    if overlap_chars >= max_chars:
        raise ValueError("overlap_chars must be smaller than max_chars")

    source = source.resolve(strict=True)
    text, encoding, raw_bytes = read_text_file(source, input_encoding)
    raw_chunks = build_chunks(text, max_chars)
    token_counter = TokenCounter(token_count_mode, tokenizer_encoding)
    source_token_count = token_counter.count(text)
    upload_advisory = chatgpt_upload_advisory(
        len(raw_bytes), source_token_count, token_counter
    )
    base = output.absolute() if output else source.parent / f"{source.stem}_chunks"
    output_dir = unique_output_dir(base)
    # Failed/interrupted writes remain visible but cannot be mistaken for a
    # verified bundle. Never recursively clean a folder that may contain user data.
    marker = output_dir / INCOMPLETE_MARKER
    atomic_write(marker, "Incomplete bundle: creation or verification did not finish.\n")
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
                token_count=token_counter.count(rendered),
                token_count_method=token_counter.method,
                tokenizer_encoding=token_counter.encoding_name,
            )
        )
        previous_raw = raw_chunk

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "tool_version": VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_name": source.name,
        "source_encoding": encoding,
        "source_size_bytes": len(raw_bytes),
        "source_bytes_sha256": sha256_bytes(raw_bytes),
        "normalized_text_sha256": sha256_text(text),
        "normalized_newlines": True,
        "line_numbering": LINE_NUMBERING,
        "source_token_count": source_token_count,
        "tokenizer": token_counter.snapshot(),
        "chatgpt_upload_advisory": upload_advisory,
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
        f"Token accounting: `{token_counter.method}` with `{token_counter.encoding_name}` "
        f"({source_token_count} source tokens)",
        f"Upload-cap advisory: `{upload_advisory['assessment']}`; policy review "
        f"`{upload_advisory['status']}` as of `{upload_advisory['reviewed_utc']}`",
        "",
        "Each file begins with the context overlap from the preceding raw chunk. "
        "The manifest records the exact prefix length so the normalized source can be "
        "reconstructed and verified.",
        "",
        "| # | File | Source lines | Raw chars | Overlap | Tokens | Method |",
        "|---:|---|---:|---:|---:|---:|---|",
    ]
    for record in records:
        index.append(
            f"| {record.number} | `{record.filename}` | {record.start_line}-{record.end_line} | "
            f"{record.raw_characters} | {record.overlap_prefix_characters} | {record.token_count} | "
            f"`{record.token_count_method}` |"
        )
    index.extend(
        [
            "",
            "Run `python src/large_text_chunker.py verify <bundle>` before sharing the bundle.",
            "",
        ]
    )
    atomic_write(output_dir / "index.md", "\n".join(index))
    _verify_bundle_contents(output_dir)
    marker.unlink()
    return output_dir


def verify_bundle(bundle: Path) -> str:
    """Verify a completed bundle without loading the optional tokenizer."""
    if os.path.lexists(bundle / INCOMPLETE_MARKER):
        raise ValueError("Incomplete bundle: recreate it from the preserved source")
    return _verify_bundle_contents(bundle)


def _verify_bundle_contents(bundle: Path) -> str:
    bundle = bundle.resolve(strict=True)
    if not bundle.is_dir():
        raise ValueError("Bundle path is not a directory")
    manifest_path = _checked_regular_file(bundle, "manifest.json", label="Manifest")
    with manifest_path.open("rb") as handle:
        manifest_bytes = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(manifest_bytes) > MAX_MANIFEST_BYTES:
        raise ValueError(f"Manifest exceeds the {MAX_MANIFEST_BYTES}-byte safety limit")
    try:
        manifest = json.loads(
            manifest_bytes.decode("utf-8"),
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
            parse_float=_finite_json_float,
        )
    except (UnicodeError, RecursionError, json.JSONDecodeError):
        raise ValueError("Manifest is not a supported UTF-8 JSON document") from None
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
    token_metadata = _validate_token_metadata(manifest)
    line_numbering = manifest.get("line_numbering")
    legacy_lines = line_numbering is None and manifest["tool_version"] in LEGACY_LINE_VERSIONS
    if not legacy_lines and line_numbering != LINE_NUMBERING:
        raise ValueError("Unsupported or missing line-numbering convention")
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
        recorded_estimate = _required_int(
            record, "estimated_tokens", label=f"Record {index}", minimum=1
        )
        record_token_count: int | None = None
        if token_metadata is not None:
            token_method, tokenizer_encoding, _ = token_metadata
            record_token_count = _required_int(
                record, "token_count", label=f"Record {index}", minimum=1
            )
            recorded_method = _required_text(
                record, "token_count_method", label=f"Record {index}"
            )
            if recorded_method != token_method:
                raise ValueError(f"Record {index} token method conflicts with the manifest")
            recorded_encoding = _required_text(
                record, "tokenizer_encoding", label=f"Record {index}"
            )
            if recorded_encoding != tokenizer_encoding:
                raise ValueError(f"Record {index} tokenizer encoding conflicts with the manifest")
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
            content = handle.read(min(output_characters, os.fstat(handle.fileno()).st_size) + 1)
        if sha256_text(content) != output_sha256:
            raise ValueError(f"Output hash mismatch: {filename}")
        if len(content) != output_characters:
            raise ValueError(f"Output character count mismatch: {filename}")
        calculated_estimate = estimated_tokens(content)
        if recorded_estimate != calculated_estimate:
            raise ValueError(f"Estimated token count mismatch: {filename}")
        if (
            token_metadata is not None
            and token_metadata[0] == "estimated-utf8-bytes-div-3"
            and record_token_count != calculated_estimate
        ):
            raise ValueError(f"Token count mismatch: {filename}")
        if prefix_length > len(content):
            raise ValueError(f"Record {index} overlap prefix exceeds its chunk length")
        raw_content = content[prefix_length:]
        if len(raw_content) != raw_characters:
            raise ValueError(f"Raw character count mismatch: {filename}")
        if sha256_text(raw_content) != raw_sha256:
            raise ValueError(f"Raw content hash mismatch: {filename}")
        previous_raw = reconstructed[-1] if reconstructed else ""
        expected_prefix = previous_raw[-requested_overlap:] if requested_overlap else ""
        if prefix_length != len(expected_prefix) or content[:prefix_length] != expected_prefix:
            raise ValueError(f"Overlap context mismatch: {filename}")
        reconstructed.append(raw_content)
        expected_raw_start = raw_end

    reconstructed_text = "".join(reconstructed)
    newline_offsets = [match.start() for match in re.finditer("\n", reconstructed_text)]
    for record in records:
        if legacy_lines:
            # Old public bundles used the following-line convention at a newline.
            start = bisect.bisect_right(newline_offsets, record["raw_start"]) + 1
            end = bisect.bisect_right(newline_offsets, record["raw_end"] - 1) + 1
        else:
            start = line_number_at(record["raw_start"], newline_offsets)
            end = line_number_at(record["raw_end"] - 1, newline_offsets)
        if (record["start_line"], record["end_line"]) != (start, end):
            raise ValueError("Source line range does not match reconstructed content")
    reconstructed_hash = sha256_text(reconstructed_text)
    if reconstructed_hash != normalized_text_sha256:
        raise ValueError("Reconstructed source hash does not match the manifest")
    if (
        token_metadata is not None
        and token_metadata[0] == "estimated-utf8-bytes-div-3"
        and token_metadata[2] != estimated_tokens(reconstructed_text)
    ):
        raise ValueError("Manifest source token count does not match the reconstructed source")
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
    split_parser.add_argument(
        "--input-encoding", choices=INPUT_ENCODINGS, default="auto",
        help="Text-file encoding; auto honors UTF byte-order marks before legacy fallback",
    )
    split_parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    split_parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP_CHARS)
    split_parser.add_argument(
        "--token-count-mode",
        choices=("estimate", "exact", "auto"),
        default=DEFAULT_TOKEN_COUNT_MODE,
        help="Token reporting mode; auto falls back to the offline estimate",
    )
    split_parser.add_argument(
        "--tokenizer-encoding",
        default=DEFAULT_TOKENIZER_ENCODING,
        help="Optional tiktoken encoding used by exact or auto mode",
    )
    verify_parser = subparsers.add_parser(
        "verify", help="Verify and reconstruct a bundle in memory"
    )
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
                token_count_mode=args.token_count_mode,
                tokenizer_encoding=args.tokenizer_encoding,
                input_encoding=args.input_encoding,
            )
            print(f"Created and verified: {destination}")
            manifest = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
            tokenizer = manifest["tokenizer"]
            advisory = manifest["chatgpt_upload_advisory"]
            print(
                f"Token accounting: {tokenizer['method']} "
                f"({manifest['source_token_count']} source tokens)"
            )
            if tokenizer.get("warning"):
                print(f"WARNING: {tokenizer['warning']}")
            print(
                f"Upload-cap advisory: {advisory['assessment']} "
                f"(policy review {advisory['status']})"
            )
        else:
            digest = verify_bundle(args.bundle)
            print(f"PASS: normalized source SHA-256 {digest}")
        return 0
    except (
        KeyError,
        OSError,
        OverflowError,
        TypeError,
        ValueError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
