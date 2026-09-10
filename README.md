# Large Text Chunker

[![Tests](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml/badge.svg)](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml)

**Make long documents easier to share, review, and verify—without losing their context.**

Large Text Chunker turns a text document into an ordered collection of readable segments. It favors paragraph and sentence boundaries, carries optional context into the next segment, and checks that the pieces reconstruct the normalized document. A reviewable index connects each segment to its source lines.

The distinctive design choice is to check the relationships between the pieces, not just their filenames: repeated context must match the preceding text, source ranges must agree with reconstructed content, and ambiguous manifest fields are rejected. An interrupted job is marked incomplete rather than presented as a finished handoff.

## Public source 1.11.1

This update supports Unicode text exports with UTF-8, UTF-16, and UTF-32 byte-order marks, adds explicit encoding selection, and strengthens bundle verification and failure handling. The standard-library default runs locally without an account, credentials, or network requests.

## Quick start

Requires Python 3.10 or newer.

```powershell
python src/large_text_chunker.py split "notes.txt"
python src/large_text_chunker.py split "notes.txt" --max-chars 12000 --overlap 600
python src/large_text_chunker.py verify "notes_chunks"
```

The default output is beside the selected source file, not in the caller's working directory. `--output` selects another destination. Existing outputs are preserved with a numeric suffix; output paths containing links or reparse points are rejected. Each finished bundle contains numbered text files, `index.md`, and `manifest.json`.

`--max-chars` limits each raw segment. Optional overlap is additional context, so a rendered file may be larger by up to `--overlap` characters. A successful split prints `Created and verified`; a successful verification prints `PASS` with the normalized-text hash. Errors return exit code 2.

## Read text accurately

Auto mode recognizes byte-order marks before trying the previous UTF-8, Windows-1252, and Latin-1 fallback. Unmarked Unicode files require a known endian-specific encoding; the tool does not guess their byte order.

```powershell
python src/large_text_chunker.py split "export.txt" --input-encoding utf-16-le
python src/large_text_chunker.py split "export.txt" --input-encoding cp1252
```

Supported choices: `auto`, `utf-8`, `utf-8-sig`, `utf-16`, `utf-16-le`, `utf-16-be`, `utf-32`, `utf-32-le`, `utf-32-be`, `cp1252`, and `latin-1`. Generic `utf-16` and `utf-32` require a byte-order mark. Conflicting selections, malformed marked/selected input, decoded NUL characters, and empty documents are rejected. Decoder errors do not include the document's contents.

Newlines are normalized to LF. The original-byte hash and effective decoder are recorded separately from the normalized-text hash. Legacy single-byte fallback cannot establish the intended encoding; review the characters or select the known encoding explicitly.

## Verify the handoff

Verification checks contiguous raw offsets, output and raw-segment hashes, exact repeated context, source line ranges, token-metadata consistency, and reconstruction of the normalized text. Duplicate JSON fields, non-finite values, oversized manifests, and unsafe chunk paths are rejected. It reads chunk content only up to the declared length plus a detection character, bounded further by the observed file size.

New bundles use inclusive source-character line ranges: a newline belongs to the line it terminates. Supported older public bundles retain their recorded line-numbering convention. Original-byte hashes are recorded provenance; the original file is not reconstructed byte-for-byte after newline/encoding normalization. Exact-token counts are not recomputed by the offline verifier.

An `.incomplete` marker means creation or verification did not finish. Keep the source and recreate the bundle; do not remove the marker merely to force a pass. Partial outputs are preserved rather than recursively deleted. Existing user files are not cleaned up automatically.

## Optional token accounting

`estimate` is the default: a UTF-8-byte heuristic, not a guaranteed upper bound. Input encoding and tokenizer encoding are separate settings. Optional exact counting uses separately installed `tiktoken==0.13.0` with `o200k_base`; nothing is installed automatically.

```powershell
python -m pip install tiktoken==0.13.0
python src/large_text_chunker.py split "notes.txt" --token-count-mode exact
python src/large_text_chunker.py split "notes.txt" --token-count-mode auto
```

`auto` reports a fallback when the optional tokenizer cannot initialize. Its first exact run may retrieve the official encoding cache. Token counts describe that tokenizer, not guaranteed ingestion or comprehension. The retained July 18, 2026 upload-cap comparison is a dated advisory that becomes `review_due` after 30 days; this update does not revalidate those external limits.

## Tests and practical boundaries

```powershell
python -m unittest discover -s tests -v
```

Tests exercise Unicode and legacy inputs, byte-order conflicts, reconstruction, source ranges, overlap corruption, duplicate manifest fields, interrupted writes, output collisions, path rejection, and command-line use from unrelated directories. The existing workflow runs Windows/Ubuntu tests and a separate real-tokenizer check; use its exact commit-specific results as evidence.

This source edition reads documents and reconstructed text into memory; it is not a streaming processor or a hostile-writer filesystem sandbox. Physical-device, Norton, and production acceptance are not claimed. Generated chunks and filenames inherit the source's sensitivity: verification is an integrity check, not automatic sanitization or permission to publish. See [security guidance](SECURITY.md).

The public edition maintains one runtime module and stable commands. Its version and qualification are separate from other editions. [Changelog](CHANGELOG.md) · [Historical archive review](ARCHIVE_VERIFICATION.md)

[Portfolio](https://jerry-napier-portfolio.netlify.app/) · [GitHub profile](https://github.com/Jnapier2)

Copyright © 2026 Gateway Information Group LLC. All rights reserved. [LICENSE.md](LICENSE.md) governs use; public visibility does not grant an open-source license. Optional dependencies retain their terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
