# Large Text Chunker

[![Tests](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml/badge.svg)](https://github.com/Jnapier2/large-text-chunker/actions/workflows/test.yml)

Large Text Chunker prepares documents for systems with input-size limits without giving up traceability. It splits text at readable boundaries, preserves configurable context, records integrity metadata, and verifies exact reconstruction of the normalized source.

Its distinctive choice is to keep transport context separate from source content: overlap is added to each readable output, while raw boundaries remain available for integrity checks. Verification removes that overlap and proves the normalized source reconstructs exactly.

## Design highlights

- Paragraph- and sentence-aware splitting with a hard size ceiling
- Configurable context overlap without losing raw chunk boundaries
- SHA-256 integrity checks for the source, every raw segment, and every output file
- Exact in-memory reconstruction during creation and on-demand verification
- Conservative, dependency-free token estimates
- Privacy-conscious manifests that record the source filename, not its full local path
- Atomic output writes and collision-safe destination folders

The tool is local-only and needs no account, API key, or network connection.

## Quick start

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

## License

Copyright 2026 Gateway Information Group LLC. Use is governed by [LICENSE.md](LICENSE.md).
