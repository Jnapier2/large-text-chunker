# Large Text Chunker

Large Text Chunker turns large text documents into ordered, overlap-aware, independently verifiable chunks. It keeps useful context at chunk boundaries while preserving enough metadata to reconstruct the normalized source exactly.

## What it demonstrates

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

Choose a different raw chunk size and overlap:

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
- Binary and empty inputs are rejected.
- Existing output folders are never overwritten; a numeric suffix is added instead.
- Chunk contents inherit the sensitivity of the input document and should be handled accordingly.

## License

Copyright 2026 Gateway Information Group LLC. Source is shared for portfolio review under the terms in [LICENSE.md](LICENSE.md).
