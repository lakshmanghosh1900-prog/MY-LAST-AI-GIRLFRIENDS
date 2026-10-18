# MY LAST AI GIRLFRIENDS — v4.1 Implementation Blueprint

**Product:** MY LAST AI GIRLFRIENDS
**Assistant:** My Companion
**Release:** 0.2.0
**Runtime:** Python 3.12.11
**Scope:** single-user, loopback-first, read-only personal companion

## Product meaning and responsibility

MY LAST AI GIRLFRIENDS is a personal companion application that can eventually
support multiple roles while sharing one owner, one auditable data store and one
explicit capability boundary. My Companion is the current assistant display
name. The product is capable of real conversation but does not claim unlimited
autonomy or perfect semantic accuracy.

The model proposes text. Ordinary code remains responsible for authentication,
data classification, local consent, file/network boundaries, budget reservation,
provider response validation and task state. No future companion role may
bypass those checks.

## Current user flow

1. Run `scripts/setup.ps1 -GenerateToken -Doctor` on Windows, or configure an
   ignored `.env` manually.
2. Select `MLAG_MODE=offline` for a deterministic local demo or `MLAG_MODE=real`
   with a privately supplied Gemini key.
3. Start `uv run --locked my-last-ai-girlfriends` and open the local browser UI.
4. Enter the local token, select an existing conversation or create a new one.
5. Write in English, Bengali or Banglish. Enter sends; Shift+Enter inserts a
   newline.
6. In real mode, ordinary personal text requires both configuration and the
   local consent checkbox. Sensitive/prohibited content remains blocked.
7. Use `/file relative.txt` for an approved local text preview or `/fetch
   https://...` for a safe public readable-text preview. Real mode can summarize
   public extracted text; offline mode only previews it and says it is not AI.

## Architecture

```text
Responsive browser UI
   │ Bearer token, exact host/origin checks, mlag-* session storage
   ▼
Authenticated local HTTP API
   ▼
Lifecycle + deterministic policy + local remote-consent state
   ├── SQLite task/history/provider/budget/audit records
   └── transactional budget ledger
   ▼
Bounded conversation context builder
   ├── OfflineDemoProvider (no network, not AI)
   └── GeminiProvider (explicit real mode, owner key, no fake fallback)
   ▼
Read-only tools
   ├── approved workspace text reader
   └── HTTPS public fetcher with DNS/IP/redirect/size/type controls
```

## Provider modes

### Offline demo

`MLAG_MODE=offline` selects `OfflineDemoProvider`. It performs no remote call,
returns deterministic text/preview responses and sets `ai_generated=false`.
The UI labels the result “Offline demo” or “not AI”.

### Real AI

`MLAG_MODE=real` selects `GeminiProvider` with:

```text
model: gemini-3.8-flash
base URL: https://generativelanguage.googleapis.com/v1beta/openai/
request: <base URL>/chat/completions, appended exactly once
auth: Authorization: Bearer <owner-supplied key>
```

The endpoint, model and prices are configuration values. A timeout, quota,
authentication error or invalid response becomes a visible provider failure or
reconciliation state. The system never substitutes the offline provider.

Official references used for the provider adapter:

- <https://ai.google.dev/gemini-api/docs/openai>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>
- <https://ai.google.dev/gemini-api/docs/pricing>

## Context and privacy

The context builder reads only recent messages from the selected conversation,
excludes the current message by ID before appending the current prompt once,
preserves chronological order, and drops older content when the configured
input-token limit is reached. Sensitive/prohibited history is not sent to the
remote provider.

Data classes:

- `PUBLIC`: public fetched text; may be sent to the configured provider.
- `PERSONAL`: ordinary conversation; real mode requires config plus local
  consent.
- `SENSITIVE`: health, finance, notifications, private documents and similar;
  blocked from remote processing.
- `PROHIBITED`: passwords, API keys, PINs, OTPs, session cookies and tokens;
  rejected and replaced with a safe placeholder in local history.

## Web and file boundaries

The file reader accepts only clean relative paths inside `workspace/`, supported
text/DOCX/PDF suffixes, regular files and configured size limits. DOCX is read
from the bounded `word/document.xml` part without executing document content.
PDF support is intentionally a bounded text-operator subset; unsupported PDF
encodings return a truthful extraction error rather than pretending to parse a
rendered page.

The web reader accepts only HTTPS port 443, rejects credentials and fragments,
resolves all addresses and blocks non-global IPs, pins the selected IP for the
TLS connection, validates every redirect and bounds bytes/content types. HTML is
parsed with Python's standard-library `HTMLParser`; scripts, styles, noscript,
templates and executable markup are removed. Only extracted text enters the
conversation context. The browser receives text via `textContent`, never raw
HTML.

## Storage and migration

Canonical database: `data/my_last_ai_girlfriends.sqlite3`. The migration helper
recognizes the former filename only as an explicit legacy recoverability path.
It checks integrity, checkpoints WAL, creates a timestamped backup, copies to a
new canonical destination, adds current schema columns without dropping data,
and refuses to proceed when both legacy and canonical files exist unexpectedly.
The old source is preserved in `data/migration-backups/` after a verified local
migration. Conversation, message, task, provider, budget and audit rows are
preserved.

## Configuration and token precedence

Precedence is deterministic:

```text
process MLAG_* > MLAG_* values in .env > legacy compatibility values in .env > defaults
```

`my-last-ai-girlfriends doctor` reports source, conflict names, selected mode,
provider/model and token status without printing values. `generate-token`
rotates the ignored `.env` after saving a timestamped backup. The prior token is
not reused. `.env` and database files remain ignored by Git.

## Task state and truthful outcomes

```text
CREATED → RUNNING → VERIFYING → SUCCEEDED
       └──────────→ SAFE_STOP
       └──────────→ NEEDS_RECONCILIATION
```

`SAFE_STOP` is visible and is not an automatic fake answer. A remote timeout or
unknown provider result becomes `NEEDS_RECONCILIATION` and is never silently
retried. `SUCCEEDED` means the response passed deterministic output checks and
was persisted.

## Capability roadmap truth

| Capability | Current status |
|---|---|
| Offline conversation | IMPLEMENTED AND TESTED |
| Gemini real-AI conversation | IMPLEMENTED, REQUIRES OWNER CONFIGURATION |
| Contextual history | IMPLEMENTED AND TESTED |
| Read-only file access | IMPLEMENTED AND TESTED |
| HTML text extraction | IMPLEMENTED AND TESTED |
| Privacy/consent/budget | IMPLEMENTED AND TESTED |
| Document processing | IMPLEMENTED AND TESTED for text, DOCX and bounded PDF text extraction |
| Research/citations | LIMITED public source URL only |
| Voice | NOT IMPLEMENTED |
| Long-term memory | NOT IMPLEMENTED |
| Android companion | NOT IMPLEMENTED; REQUIRES PLATFORM REVIEW |
| Scheduling/background agents | NOT IMPLEMENTED |
| MCP/skills | NOT IMPLEMENTED; REQUIRES SECURITY REVIEW |
| External actions/approval | NOT IMPLEMENTED; REQUIRES SECURITY REVIEW |
| Multi-user/public hosting | NOT IMPLEMENTED; REQUIRES PRIVACY/SECURITY REVIEW |

Payments, messaging, shell/code execution, banking, Accessibility automation,
public hosting, autonomous side effects and unreviewed self-learning remain
disabled exactly as required by the approved blueprint.
