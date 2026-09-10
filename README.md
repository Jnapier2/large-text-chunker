# Large Text Chunker

[![Tests](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml/badge.svg)](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml)

**Turn long documents into readable, ordered bundles without losing track of the source.**

Large Text Chunker splits text at paragraph and sentence boundaries, carries optional context into the next chunk, and verifies that the pieces reconstruct the normalized document. Its manifests make a handoff reviewable: recipients can check the order, source ranges, content hashes, and token-accounting method rather than trust filenames alone.

## What is new in public source 1.11.0

Unicode exports no longer need to be converted manually just because their byte representation contains zeroes. The reader recognizes UTF-8, UTF-16, and UTF-32 byte-order marks, decodes strictly, and checks the entire decoded document for NUL characters. An explicit input-encoding option handles unmarked Unicode files without guessing their byte order.

This is a selective encoding-capability adaptation from the newer 1.19.1 source lineage, not a publication of that entire private package. The public implementation, command path, output manifest, optional tokenizer pin, and existing verification controls remain independent.

## Quick start

Requires Python 3.10 or newer. The default path is offline and uses only the Python standard library.

```powershell
python src/large_text_chunker.py split "notes.txt"
python src/large_text_chunker.py split "notes.txt" --max-chars 12000 --overlap 600
python src/large_text_chunker.py verify "notes_chunks"
```

By default, the bundle is created beside the selected source file, not in the caller's working directory. `--output` selects another destination. Existing output folders are preserved using a numeric suffix. Each bundle contains numbered text files, `index.md`, and `manifest.json`.

## Input encodings

Auto mode checks byte-order marks first, with UTF-32 checked before UTF-16. Unmarked inputs retain the previous UTF-8, Windows-1252, then Latin-1 fallback. Single-byte fallback cannot determine the intended language or encoding; review the resulting characters and select an encoding explicitly when known.

```powershell
python src/large_text_chunker.py split "export.txt" --input-encoding utf-16-le
python src/large_text_chunker.py split "export.txt" --input-encoding cp1252
```

Supported choices are `auto`, `utf-8`, `utf-8-sig`, `utf-16`, `utf-16-le`, `utf-16-be`, `utf-32`, `utf-32-le`, `utf-32-be`, `cp1252`, and `latin-1`. Unmarked UTF-16/32 requires an explicit endian-specific choice. A marked file must agree with an explicit choice. Invalid marked/selected input fails before an output folder is created; it is not repaired with replacement characters or a legacy fallback.

Newlines are normalized to LF. The manifest records the effective decoder, original byte count/hash, and normalized-text hash. Decoded NUL characters and empty documents are rejected. This is text validation, not a malware scanner or a general binary-file classifier.

## Token accounting

Input encoding and token-counting encoding are different settings. `estimate` remains the default and needs no package or network connection. Optional exact counting uses `tiktoken==0.13.0` with `o200k_base`; the tool never installs it automatically.

```powershell
python -m pip install tiktoken==0.13.0
python src/large_text_chunker.py split "notes.txt" --token-count-mode exact
python src/large_text_chunker.py split "notes.txt" --token-count-mode auto
```

`auto` attempts exact counting and reports a fallback when the optional tokenizer cannot initialize. The first exact-mode run may retrieve the tokenizer's official encoding cache. No account, API key, or API request is required. Token counts describe the selected tokenizer, not guaranteed model comprehension or ingestion.

## Evidence and compatibility

Every bundle records original and normalized hashes, ordered raw offsets, source line ranges, overlap lengths, chunk hashes, and source/chunk token counts. Verification checks reconstruction and manifest consistency. Older supported manifests remain verifiable; the source input is not required to reconstruct normalized content from a complete bundle.

The retained July 18, 2026 upload-cap comparison is a dated, nonblocking advisory. It becomes `review_due` after 30 days. This update does not refresh those external limits or guarantee upload eligibility, available context, or successful ingestion.

## Verification and limits

```powershell
python -m unittest discover -s tests -v
```

The suite covers reconstruction, overlap, path/filename rejection, token metadata, malformed manifests, Unicode byte orders, invalid decoding, late NUL characters, legacy inputs, and command-line operation from an unrelated directory. The existing workflow also runs Windows/Ubuntu checks and a separate real-tokenizer integration. Consult its exact commit-specific result; this page is not proof a pending workflow passed.

The splitter still reads documents into memory; streaming, private launchers, and private diagnostics from the newer package are not included in this selective port. Physical-device, Norton, and production acceptance are not claimed. Generated chunks inherit the sensitivity of their source; inspect them before sharing. Hash agreement checks integrity, not whether the content is safe to publish.

## Lineage and rights

Public source 1.11.0 builds on public 1.10.0 and selectively adapts input-decoding behavior from the 1.19.1 source lineage. It preserves one runtime module and the existing test suite rather than copying a second application. See [the changelog](CHANGELOG.md) and the retained [historical archive review](ARCHIVE_VERIFICATION.md).

[Portfolio](https://jerry-napier-portfolio.netlify.app/) · [GitHub profile](https://github.com/Jnapier2)

Copyright © 2026 Gateway Information Group LLC. All rights reserved. Use is governed by [LICENSE.md](LICENSE.md). No third-party code is bundled; optional components retain their own terms in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
