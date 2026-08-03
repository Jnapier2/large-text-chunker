# Security Policy

Please use GitHub private vulnerability reporting if it is enabled. Otherwise, contact the maintainer through the GitHub profile and request a private reporting channel. Do not attach confidential source documents or generated chunks to a public issue.

Large Text Chunker requires no credentials. Its default estimate mode runs locally with the Python standard library and makes no network requests. Optional exact mode uses a separately installed `tiktoken` package and may retrieve the official encoding cache when it is first initialized; it does not call the OpenAI API.

Generated bundles contain source-derived content and must be protected according to the sensitivity of the input. Reports should include the tool version and a redacted manifest, but never a confidential source document or generated chunk.
