# Recovered v1.10.0 Archive Verification

This record documents the exact Drive package recovered during the August 2, 2026 GitHub and Google Drive reconciliation. It verifies the package identity and describes the remaining source-promotion gate; it does not relabel the current GitHub tree.

## Recovered artifact

- File: `ChatGPT_Text_Chunker_v1.10.0_20260718_0111_CDT.zip`
- Recorded SHA-256: `20a428ae390b0443ef08acc5bbcc562124f0f748be74be25b6d9e547916d8ebf`
- Calculated SHA-256: `20a428ae390b0443ef08acc5bbcc562124f0f748be74be25b6d9e547916d8ebf`
- Package version: `v1.10.0`
- Package source version: `v1.9.0`
- Package file count: `10`
- Original generated time: July 18, 2026 at 1:11:55 AM CDT

The exact ZIP and its checksum companion were both recovered from the owner-controlled Google Drive registry. The calculated digest matches the retained checksum companion exactly.

## Archive and manifest verification

The following checks passed:

- ZIP central-directory and CRC integrity;
- exactly ten expected regular-file entries;
- no duplicate archive paths;
- no absolute paths, parent traversal, symlinks, or device entries;
- canonical `MANIFEST.json` and `MANIFEST.csv` present;
- every non-self manifest file size and SHA-256 record matches the packaged file;
- the two manifest records use the documented `SELF_REFERENTIAL_SEE_ZIP_SHA256_SIDECAR` value rather than pretending a self-referential file hash can be fixed inside itself;
- the package-level SHA-256 sidecar supplies the final immutable archive identity;
- text review found no private-key blocks, credential values, or personal absolute user paths. References to `tiktoken` are dependency names, not authentication tokens.

## Runtime verification

Verification was performed from a clean extraction using Python 3.13.5:

- engine compilation: **PASS**;
- package preflight: **PASS**;
- built-in self-test: **PASS**;
- estimate-mode dry run: **PASS**;
- exact normalized-text reconstruction exercised by the self-test: **PASS**.

The package retains one BAT launcher, one Python engine, one default configuration source, project-relative paths, atomic writes, collision-safe output, bounded diagnostics, and source/chunk exclusion from Export20 support bundles.

## Dependency boundary

The package requires only the Python standard library in its default `estimate` mode.

Optional exact token counting uses:

- package: `tiktoken`
- reviewed version: `0.13.0`
- encoding: `o200k_base`
- installation behavior: never installed automatically
- network behavior: an official encoding-cache retrieval may be needed once when exact mode is first initialized

The current public v1.0.0 source remains dependency-free. The optional v1.10.0 dependency does not become part of the public repository contract until the exact v1.10.0 source layout and CI are imported and reviewed.

## Remaining promotion gate

The earlier “archive unavailable” blocker is resolved. Promotion to public source still requires one controlled pass that:

1. imports the exact recovered v1.10.0 files without reconstructing or silently redesigning them;
2. reconciles the current `src/` and `tests/` layout with the package’s BAT, `tools/`, and `config/` layout;
3. retains the repository’s current rights notice and documents the optional `tiktoken` license and notices;
4. adds regression coverage for estimate, exact-unavailable, auto-fallback, reconstruction, manifest reconciliation, Windows-safe paths, and diagnostic export;
5. runs the hosted Windows and Ubuntu CI matrix;
6. validates the primary BAT launcher on Windows with spaces in the path;
7. runs a Norton-on smoke test against the exact final release artifact; and
8. updates the repository version, README, release ledger, dependency ledger, and downloadable package together only after every gate passes.

Until that pass is complete, GitHub remains the public v1.0.0 source authority and the recovered v1.10.0 ZIP remains the checksum-verified successor package.

Copyright © 2026 Gateway Information Group LLC. All rights reserved.

This notice does not replace or infer a software license. Third-party components retain their respective notices and licenses.
