# Large Text Chunker

[![Tests](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml/badge.svg)](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml)

Large Text Chunker turns oversized documents into readable, ordered bundles that can be shared without losing source integrity. It favors paragraph and sentence boundaries, adds optional context overlap, records per-file evidence, and verifies exact reconstruction of the normalized source.

## Highlights

- Readable paragraph- and sentence-aware splitting with a hard size ceiling
- Exact normalized-text reconstruction, even when chunks include context overlap
- SHA-256 evidence for the source, every raw segment, and every output file
- Source-level and per-chunk token counts with three explicit modes
- A dated, nonblocking comparison with reviewed ChatGPT upload caps
- Privacy-conscious manifests that retain the source filename, not its local path
- Atomic writes and collision-safe output folders

This makes large-document handoffs easier to inspect, resume, and validate. A recipient can confirm both the order of the chunks and whether the reconstructed content still matches the source.

## Quick start

Requires Python 3.10 or newer. The default path is offline and uses only the Python standard library.

```powershell
python src/large_text_chunker.py split "notes.txt"
```

Adjust the workload controls without weakening the integrity checks:

```powershell
python src/large_text_chunker.py split "notes.txt" --max-chars 12000 --overlap 600
```

Verify a bundle before sharing it:

```powershell
python src/large_text_chunker.py verify "notes_chunks"
```

Each bundle contains numbered text files, `index.md`, and `manifest.json`.

## Token accounting

`estimate` is the default. It uses a conservative UTF-8 byte estimate and needs no package or network connection.

```powershell
python src/large_text_chunker.py split "notes.txt" --token-count-mode estimate
```

Optional exact counting uses OpenAI `tiktoken==0.13.0` with `o200k_base`. The tool never installs it automatically.

```powershell
python -m pip install tiktoken==0.13.0
python src/large_text_chunker.py split "notes.txt" --token-count-mode exact
```

`auto` attempts exact counting and falls back to the offline estimate with a visible warning if the optional tokenizer cannot initialize:

```powershell
python src/large_text_chunker.py split "notes.txt" --token-count-mode auto
```

The first exact-mode run may allow `tiktoken` to retrieve its official encoding cache. No OpenAI account, API key, or API request is required.

## Evidence in every bundle

The manifest records:

- original-byte and normalized-text SHA-256 digests;
- raw offsets, line ranges, overlap length, and hashes for each chunk;
- estimated tokens plus the selected token count, method, and encoding;
- optional tokenizer version and fallback state; and
- an upload-cap advisory with its source review date and freshness status.

Upload guidance is advisory only. It does not promise plan eligibility, successful ingestion, available context size, or that all uploaded content will enter active model context. The embedded July 18, 2026 policy review automatically changes to `review_due` after 30 days without blocking chunk creation.

## Release lineage

- **Current public source:** `1.10.0`
- **Recovered source package:** `ChatGPT_Text_Chunker_v1.10.0_20260718_0111_CDT.zip`
- **Verified package SHA-256:** `20a428ae390b0443ef08acc5bbcc562124f0f748be74be25b6d9e547916d8ebf`

Version 1.10.0 brings the recovered package's token-accounting and dated-advisory capabilities into the compact public layout while retaining the repository's stricter path validation, manifest checks, cross-platform tests, security policy, and license. The recovered ZIP remains immutable provenance; it is not recreated or represented as a GitHub-built artifact. See [archive verification](ARCHIVE_VERIFICATION.md) and [the changelog](CHANGELOG.md).

## Test

```powershell
python -m py_compile src/large_text_chunker.py tests/test_large_text_chunker.py
python -m unittest discover -s tests -v
```

GitHub Actions runs the same source and test checks on Windows and Ubuntu.

## Design boundaries

- Character-based boundaries remain stable; token counts are reporting evidence, not a new splitting algorithm.
- Input newlines are normalized to `LF`; the manifest retains both original-byte and normalized-text hashes.
- NUL-containing and empty inputs are rejected.
- Existing output folders are never overwritten; a numeric suffix is added.
- Generated chunks inherit the sensitivity of the source document.
- Exact token counts depend on an optional third-party package; estimate mode remains the portable default.

## Portfolio and license

[Portfolio](https://jerry-napier-portfolio.netlify.app/) · [GitHub profile](https://github.com/Jnapier2)

Copyright © 2026 Gateway Information Group LLC. All rights reserved. Use is governed by [LICENSE.md](LICENSE.md). No third-party code is bundled; optional components retain their own terms described in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
