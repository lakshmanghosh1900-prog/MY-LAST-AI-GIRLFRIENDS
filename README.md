# MY LAST AI GIRLFRIENDS

**My Companion** is a personal, local-first chat application for the MY LAST AI
GIRLFRIENDS project. It supports a truthful offline demo and an explicit,
configured Gemini real-AI mode. It remains single-user, loopback-first and
read-only in this release.

## What is implemented

- Product and Python package branding migrated to `my_last_ai_girlfriends`.
- Authenticated local browser application with responsive desktop/mobile UI.
- Conversation creation, bounded history listing and conversation selection.
- SQLite persistence using `data/my_last_ai_girlfriends.sqlite3`.
- Safe migration path for the legacy database filename with verified backups.
- Deterministic policy engine and bounded budget ledger retained from the
  approved blueprint.
- Offline demo mode that is explicitly labelled **not AI**.
- Real Gemini mode using Google's OpenAI-compatible endpoint when the owner
  supplies a key locally.
- Recent conversation context, isolated per conversation and bounded by limits.
- Explicit local consent for ordinary personal text in real-AI mode.
- Protected/sensitive/file content blocked from remote processing by default.
- Read-only approved workspace file preview.
- HTTPS public fetching with IP validation, redirects and byte/type limits.
- Readable HTML extraction with scripts/styles/noscript removed.
- Safe text rendering; fetched/model output is never injected as HTML.

## Product responsibility

My Companion can respond conversationally, but it cannot honestly promise 100%
semantic accuracy. Deterministic code remains responsible for authentication,
privacy classification, approved tools, budget reservations, provider response
validation and task state. The model cannot grant itself permission or create a
fake success after a provider failure.

## Runtime

- Python `3.12.11` pinned in `.python-version`.
- Distribution: `my-last-ai-girlfriends`.
- CLI: `my-last-ai-girlfriends`.
- Python entry point: `my_last_ai_girlfriends.main`.
- Environment prefix: `MLAG_`.
- HTTP User-Agent/service identifier: `my-last-ai-girlfriends`.
- Runtime dependencies remain standard-library only.
- `uv.lock` is committed.

## Windows setup

From `C:\Users\User\Desktop\MY LAST AI GIRLFRIENDS`:

```powershell
uv python install 3.12.11
uv sync --locked
.\scripts\setup.ps1 -GenerateToken -Doctor
```

The setup command creates or rotates the ignored `.env` and never prints the
generated token. Use a protected local workflow to enter the ignored token in
the browser when needed. The diagnostic reports provider, mode, model, source,
conflicts and token validity without displaying secret values.

Start the application:

```powershell
$env:PYTHONPATH = "$PWD\src"
uv run --locked my-last-ai-girlfriends
```

Open <http://127.0.0.1:8787>. The first page accepts the local token. The
application will say **Offline demo · not AI** until real mode is configured and
an actual Gemini completion succeeds.

## Real Gemini mode

The provider uses Google's OpenAI-compatible documentation:

- <https://ai.google.dev/gemini-api/docs/openai>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>
- <https://ai.google.dev/gemini-api/docs/pricing>

The configured defaults are:

```text
MLAG_MODE=real
MLAG_PROVIDER=gemini
MLAG_MODEL=gemini-3.8-flash
MLAG_PROVIDER_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai/
MLAG_GEMINI_API_KEY=stored-only-in-ignored-.env
```

The endpoint builder appends `/chat/completions` exactly once. The model,
endpoint and token prices are configurable. The provider is never silently
replaced with the offline demo after a remote error.

Ordinary personal conversation additionally requires:

1. `MLAG_ALLOW_REMOTE_PERSONAL_DATA=true` in local configuration; and
2. the in-app remote-conversation consent checkbox.

Sensitive, health, financial, credential, password, PIN, OTP and authentication
content remains blocked from remote processing. File contents remain local.

## Offline demo mode

The default is:

```text
MLAG_MODE=offline
```

It makes no provider request. Chat responses and file/web previews are
deterministic and visibly labelled **Offline demo (not AI)** or **Offline demo
preview (not AI)**. This mode is intended for local testing and UI work.

## Tools

Use the composer commands:

```text
/file README.txt
/fetch https://example.com
```

`/file` can only read supported text files below `workspace/`. `/fetch` accepts
only HTTPS public destinations, validates every resolved address and redirect,
caps response size, and extracts readable text from HTML. It does not render
HTML, execute scripts or load embedded resources.

## Tests and checks

Run the exact pinned-runtime checks:

```powershell
uv sync --locked
uv lock --check
$env:PYTHONPATH = "$PWD\src"
uv run --locked python -m compileall -q src tests
uv run --locked python -m unittest discover -s tests -p "test_*.py" -v
```

The canonical Make commands are also available:

```text
make test
make check
```

Tests are deterministic and do not require a live API key or paid API call.
Optional live Gemini testing is intentionally separate and is not claimed by
the automated suite.

## Docker

```powershell
docker build --tag my-last-ai-girlfriends:0.2.0 .
docker run --rm -it --env-file .env -e MLAG_HOST=0.0.0.0 -e MLAG_ALLOW_NON_LOOPBACK_BINDING=true -p 127.0.0.1:8787:8787 -v "${PWD}\data:/app/data" my-last-ai-girlfriends:0.2.0
```

The container's internal bind is allowed for the port mapping; publish only to
loopback on the host. Never commit `.env`, provider keys, tokens, databases or
conversation data.

## Capability truth table

| Capability | Status |
|---|---|
| Offline demo conversation | IMPLEMENTED AND TESTED |
| Gemini real-AI conversation | IMPLEMENTED, REQUIRES OWNER CONFIGURATION and live key |
| Contextual conversations | IMPLEMENTED AND TESTED |
| Conversation history | IMPLEMENTED AND TESTED |
| Read-only file access | IMPLEMENTED AND TESTED |
| Safe webpage retrieval/extraction | IMPLEMENTED AND TESTED offline fixtures |
| Local persistence | IMPLEMENTED AND TESTED |
| Privacy and consent | IMPLEMENTED AND TESTED |
| Budget tracking | IMPLEMENTED AND TESTED |
| Document processing | LIMITED: approved local text indexing/search; PDF/DOCX and grounded answers not implemented |
| Research and citations | LIMITED to source URL on public fetch |
| Voice | NOT IMPLEMENTED |
| Long-term memory | LIMITED: explicit local memory management implemented; automatic extraction and remote memory disabled |
| Android companion | NOT IMPLEMENTED; REQUIRES PLATFORM REVIEW |
| Scheduling | NOT IMPLEMENTED |
| MCP and skills | NOT IMPLEMENTED; REQUIRES SECURITY REVIEW |
| Background agents | NOT IMPLEMENTED |
| External actions/approval | NOT IMPLEMENTED; requires separate security review |
| Multi-user/public hosting | NOT IMPLEMENTED; requires privacy/security review |

Payments, messaging, shell execution, arbitrary code execution, banking,
Accessibility automation, public hosting, autonomous side effects and unreviewed
self-learning remain disabled.

## Documents

- [`docs/BLUEPRINT-v4.1.md`](docs/BLUEPRINT-v4.1.md) — current product and
  implementation blueprint.
- [`docs/FINAL-AUDIT.md`](docs/FINAL-AUDIT.md) — audit, migration evidence,
  controls, source status and verification record.
