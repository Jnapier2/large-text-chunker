# Changelog

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
