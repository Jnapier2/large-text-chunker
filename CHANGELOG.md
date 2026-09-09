# Changelog

## 1.11.0 — 2026-09-09

- Selectively adapted BOM-aware UTF-8/16/32 input decoding from the 1.19.1 source lineage into the existing compact public runtime.
- Added `--input-encoding` for explicit supported decoders, including endian-specific unmarked Unicode. Kept this setting separate from the optional tokenizer encoding.
- Reject conflicting byte-order marks and explicit choices, malformed marked/selected text, and decoded NULs throughout the document without exposing source contents in decoder errors.
- Preserved the default unmarked UTF-8/Windows-1252/Latin-1 fallback, newline normalization, original-byte evidence, manifest schema, optional tokenizer pin, output locations, and legacy verification behavior.
- Added twelve encoding/integration regression methods to the existing test file, including CLI execution from an unrelated directory and failure before output creation.

This is a public-source capability port, not the complete private 1.19.1 application. Its streaming, launchers, diagnostics, internal records, and acceptance claims are not inherited. No dependency, workflow, license, repository name, or permission was changed. Native device/Norton acceptance remains separate from source tests.

## 1.10.0 — 2026-08-02

- Added source-level and per-chunk token evidence while retaining the existing character-based splitting algorithm.
- Added `estimate`, `exact`, and `auto` token modes. Estimate remains dependency-free; exact uses optional `tiktoken==0.13.0`; auto provides a visible fallback.
- Added a dated, nonblocking ChatGPT upload-cap advisory with an automatic review-due state.
- Preserved backward verification support for 1.0.0 manifests.
- Strengthened verification by independently recalculating every retained estimated-token value and checking new token/advisory metadata for internal consistency.
- Retained the hardened path, filename, reconstruction, hash, atomic-write, license, and cross-platform CI controls from the public 1.0.0 source.

The checksum-matched 1.10.0 recovery package provided feature and provenance evidence. The compact public layout remains authoritative and retains the repository's stronger validation, tests, security policy, and cross-platform structure.

## 1.0.0 — 2026-07-18

- Introduced paragraph- and sentence-aware splitting, configurable overlap, integrity manifests, exact normalized-text reconstruction, atomic output, and conservative token estimates.

Copyright © 2026 Gateway Information Group LLC. All rights reserved.
