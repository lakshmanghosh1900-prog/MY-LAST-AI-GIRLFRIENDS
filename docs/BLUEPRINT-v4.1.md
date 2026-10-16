# JARVIS OMEGA v4.1 — Implemented Vertical-Slice Blueprint

**Project:** MY LAST AI GIRLFRIENDS  
**Release:** 0.1.0  
**Review/build date:** 17 October 2026  
**Implementation status:** The files in this repository are implemented locally;
the release gates in `docs/FINAL-AUDIT.md` are the authority for what is and is
not proven.

## Product meaning

“MY LAST AI GIRLFRIENDS” is the product umbrella: a personal assistant that can
represent multiple companion roles while keeping one owner, one explicit
capability boundary and one auditable source of truth. “JARVIS OMEGA” is the
engine name: it coordinates requests, tools and model providers. “Omega” means
the end-to-end boundary is designed first; it does not mean unlimited or
error-free autonomy.

## First user flow

1. The owner creates `.env` from `.env.example` and sets a long token.
2. The service starts on `127.0.0.1` and initializes SQLite in `data/`.
3. The owner opens the local UI and supplies the token in the browser session.
4. A conversation is created; each message becomes a bounded task.
5. Deterministic policy classifies the data before the provider is called.
6. `/file relative.txt` uses only the approved `workspace/` root; `/fetch
   https://...` uses only the constrained HTTPS fetcher.
7. The provider output is schema-checked and the task is marked `SUCCEEDED`
   only after the result is persisted. Unsafe, over-budget, unavailable or
   uncertain work becomes a visible safe-stop state.

## Architecture

```text
Browser UI
   │ Authorization: Bearer token; exact origin/host checks
   ▼
Local HTTP API (127.0.0.1 by default)
   ▼
Lifecycle + request validation
   ▼
Deterministic Policy Engine ── Budget Ledger (SQLite BEGIN IMMEDIATE)
   ▼
Bounded Orchestrator
   ├── Fake provider (default, offline)
   ├── OpenAI-compatible provider (explicit opt-in)
   ├── Read-only file tool (approved root)
   └── HTTPS fetch tool (public IP + redirect + size/type checks)
   ▼
SQLite task/message/provider/audit records
```

## Task state

```text
CREATED → RUNNING → VERIFYING → SUCCEEDED
       └──────────→ SAFE_STOP
       └──────────→ NEEDS_RECONCILIATION
```

`SAFE_STOP` is an intentional user-visible result, not a hidden retry. It is
used when policy, limits, provider schema, tool validation or local execution
cannot prove a safe result. `NEEDS_RECONCILIATION` is reserved for a remote
provider timeout where usage/outcome is not knowable locally; the adapter never
automatically resends that call.

## Responsibility split

| Concern | Owner | What is independently checked |
|---|---|---|
| User intent | Owner/UI | Exact message and explicit command |
| Capability | Policy engine | Static allowlist, data class, provider boundary |
| Cost | Budget ledger | Reservation before call, settlement after call |
| Model text | Provider adapter | Timeout, size, schema and tool-call rejection |
| File access | File tool | Relative path, root containment, no symlink, type/size |
| Web access | Fetch tool | HTTPS, public DNS result, redirect, content and byte limits |
| Success | Orchestrator | Persisted assistant text and terminal task state |

## Data policy

- `PUBLIC`: public fetch content may use an approved remote provider.
- `PERSONAL`: local fake provider by default; remote use requires explicit
  configuration.
- `SENSITIVE`: local-only by default; local file content never goes to the
  remote provider unless the owner explicitly enables personal-data transfer.
- `PROHIBITED`: passwords, keys, PINs, OTPs and session cookies are rejected.

Provider credentials are never placed in prompts, messages, audit metadata or
URLs. The fake provider is the default so the project remains useful offline.

## Dependency-aware roadmap

| Stage | Scope | Required evidence before enabling |
|---|---|---|
| 0 | Current local read-only slice | Offline tests, compile check, task persistence |
| 1 | Second provider/fallback | Provider privacy matrix, cost tests, fail-closed routing |
| 2 | Private PWA access | Device enrollment, revocation, network boundary tests |
| 3 | Native Android companion | Target-device process/permission tests and distribution review |
| 4 | Voice | Consent, audio retention, measured cost/battery tests |
| 5 | MCP/skills | Per-server auth, provenance, sandbox, rollback and denial tests |
| 6 | External side effects | Action-bound approval, idempotency and reconciliation evidence |
| 7 | Multi-user/public use | Tenancy, privacy/legal, monitoring, support and incident response |

No later stage is implied by the current code. Each stage must be implemented
and checked separately.
