# Large Text Chunker

[![Tests](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml/badge.svg)](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml)

Large Text Chunker prepares documents for systems with input-size limits without giving up traceability. It splits text at readable boundaries, preserves configurable context, records integrity metadata, and verifies exact reconstruction of the normalized source.

Context overlap and source integrity are handled separately. Overlap keeps chunks readable for downstream tools; retained raw boundaries let verification remove that added context and reconstruct the normalized source exactly.

## Release lineage

- **Current public source authority:** `1.0.0`.
- **Recovered successor package:** `ChatGPT_Text_Chunker_v1.10.0_20260718_0111_CDT.zip`.
- **Recorded and verified SHA-256:** `20a428ae390b0443ef08acc5bbcc562124f0f748be74be25b6d9e547916d8ebf`.
- **Package verification:** ZIP integrity, safe-path review, non-self manifest hashes, Python compilation, preflight, self-test, and estimate-mode dry-run passed on August 2, 2026.
- **Promotion status:** exact bytes are recovered, but the repository remains at v1.0.0 until the v1.10.0 source layout, optional dependency boundary, CI, rights metadata, and Windows/Norton acceptance are reconciled as one reviewable promotion.

The earlier missing-archive blocker is resolved. The repository is still intentionally not relabeled as v1.10.0 before the source import and acceptance gate is complete. See [Recovered v1.10.0 archive verification](ARCHIVE_VERIFICATION.md) and [issue #3](https://github.com/Jnapier2/large-text-chunker/issues/3).

## Current public design highlights

- Paragraph- and sentence-aware splitting with a hard size ceiling
- Configurable context overlap without losing raw chunk boundaries
- SHA-256 integrity checks for the source, every raw segment, and every output file
- Exact in-memory reconstruction during creation and on-demand verification
- Conservative, dependency-free token estimates
- Privacy-conscious manifests that record the source filename, not its full local path
- Atomic output writes and collision-safe destination folders

The current v1.0.0 source is local-only and needs no account, API key, package installation, or network connection. The recovered v1.10.0 package preserves an offline estimate mode and adds optional exact token counting through explicitly installed `tiktoken==0.13.0`; it does not install that optional package automatically.

## Quick start for the current public source

Requires Python 3.10 or newer.

```powershell
python src/large_text_chunker.py split "notes.txt"
```

Adjust the two workload controls without changing the integrity checks:

```powershell
python src/large_text_chunker.py split "notes.txt" --max-chars 12000 --overlap 600
```

Verify an existing bundle before sharing it:

```powershell
python src/large_text_chunker.py verify "notes_chunks"
```

The output contains numbered text files, `index.md`, and `manifest.json`. Each file after the first begins with a recorded prefix from the previous raw chunk. Verification removes those prefixes in memory and confirms the reconstructed normalized-text hash.

## Test

```powershell
python -m unittest discover -s tests -v
python -m py_compile src/large_text_chunker.py
```

## Design boundaries

- Input newlines are normalized to `LF`; the manifest stores both the original byte hash and the normalized-text hash.
- The built-in token value is an estimate, not a model-specific billing count.
- Inputs containing NUL bytes and empty inputs are rejected.
- Existing output folders are never overwritten; a numeric suffix is added instead.
- Chunk contents inherit the sensitivity of the input document and should be handled accordingly.
- Verification of the recovered v1.10.0 archive does not make that package the current GitHub source or prove Windows/Norton acceptance.

## Portfolio and license

[Portfolio](https://jerry-napier-portfolio.netlify.app/) · [GitHub profile](https://github.com/Jnapier2)

Copyright © 2026 Gateway Information Group LLC. All rights reserved. Use is governed by [LICENSE.md](LICENSE.md). Third-party components remain subject to their respective notices and licenses.
