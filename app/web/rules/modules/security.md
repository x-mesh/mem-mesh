# Security Rules

Never store sensitive data in mem-mesh.

## Never Save

- API keys
- access tokens
- passwords
- private keys
- `.env` contents
- personal data such as email addresses, phone numbers, or government IDs

Replace sensitive values with `<REDACTED>` when the surrounding context is
important.

## Honesty

- Do not say a memory was saved until the tool call succeeds.
- If a save fails, report the failure and provide the intended summary.
- Do not fabricate memory IDs, tool results, versions, or API behavior.

## Paths

Prefer repository-relative paths in memories. Avoid absolute local paths unless
the path itself is the subject of the memory.
