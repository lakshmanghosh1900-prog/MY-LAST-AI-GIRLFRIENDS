# MY LAST AI GIRLFRIENDS — 21-Stage Execution Roadmap

This is the versioned execution ledger for the approved Stage 01–21 roadmap.
It does not replace `docs/BLUEPRINT-v4.1.md` or `docs/FINAL-AUDIT.md`; those
documents remain the product and historical audit sources.

## Status vocabulary

- `CLOSED — VERIFIED`: all applicable acceptance checks were executed and passed.
- `IN PROGRESS`: implementation or verification is active.
- `BLOCKED_EXTERNAL`: safe work is complete, but a required external service,
  credential, device, or permission was unavailable.
- `NOT STARTED`: dependency gate has not opened.
- `NOT APPLICABLE`: deliberately outside the enabled release scope, with a
  reason recorded in the execution status.

## Dependency order

| Stage | Scope | Dependency | Initial status |
|---|---|---|---|
| 01 | Repository and configuration repair | Task 00 | IN PROGRESS |
| 02 | Product rename and data migration | Stage 01 | NOT STARTED |
| 03 | Real Gemini provider | Stage 02 | NOT STARTED |
| 04 | Conversation context and isolation | Stage 03 | NOT STARTED |
| 05 | UI/UX and readable web tools | Stage 04 | NOT STARTED |
| 06 | MVP verification, security and release | Stages 01–05 | NOT STARTED |
| 07 | Long-term memory | Stage 06 | NOT STARTED |
| 08 | Document intelligence | Stage 07 | NOT STARTED |
| 09 | Research engine | Stage 08 | NOT STARTED |
| 10 | Task planner and scheduler | Stage 09 | NOT STARTED |
| 11 | Voice AI | Stage 10 | NOT STARTED |
| 12 | Controlled tools and automation | Stage 11 | NOT STARTED |
| 13 | Assistant integration and evaluation | Stage 12 | NOT STARTED |
| 14 | Native Android companion | Stage 13 | NOT STARTED |
| 15 | Secure PC–phone connectivity | Stage 14 | NOT STARTED |
| 16 | MCP connector framework | Stage 15 | NOT STARTED |
| 17 | Skills and controlled learning | Stage 16 | NOT STARTED |
| 18 | Multi-agent orchestration | Stage 17 | NOT STARTED |
| 19 | Human approval and external actions | Stage 18 | NOT STARTED |
| 20 | Device mesh and optional local brain | Stage 19 | NOT STARTED |
| 21 | Final reliability, security and release hardening | Stage 20 | NOT STARTED |

## Legacy roadmap mapping

The current checkout contains no document with explicit `Phase 0` through
`Phase 7` headings. A repository search found only the capability roadmap in
the blueprint and audit. Therefore the following is an explicit provisional
mapping inferred from the committed history and existing implementation; it is
not presented as a source document that was found:

| Existing implementation phase (inferred) | Approved stages |
|---|---|
| Phase 0 — blueprint, scope and baseline recovery | Task 00 |
| Phase 1 — local configuration, authentication and policy | Stage 01 |
| Phase 2 — package/product rename and SQLite migration | Stage 02 |
| Phase 3 — provider adapter and truthful mode handling | Stage 03 |
| Phase 4 — bounded context, privacy and conversation isolation | Stage 04 |
| Phase 5 — browser UI and read-only tools | Stage 05 |
| Phase 6 — deterministic MVP security and release gate | Stage 06 |
| Phase 7 — future capability expansion and owner handoff | Stages 07–21 |

The absence of an explicit Phase 0–7 source is a documentation discrepancy,
not permission to overwrite historical documents. If a canonical Phase 0–7
document is later recovered, this table must be reconciled against it before a
stage is declared complete.

## Current execution status

The dependency table above preserves the approved roadmap's initial statuses.
The current implementation status is maintained in `docs/EXECUTION-STATUS.md`.
The safe Stage 07A, Stage 08A and Stage 09A slices now implemented are
explicit local memory management, bounded text-document indexing/search and
explicit public-URL research with source provenance; they do not close their
full stages or authorize remote memory/document transfer.

The latest published implementation commit is `1ca32e2bbf5df79194e2f5a9c82d3097d4b97b83`. Both push and pull-request GitHub Actions pass 83 tests, locked dependency validation, compileall and `uv build`. Draft PR #1 is open and unmerged. Current status is:

| Stage | Current status | Implemented slice / remaining gate |
|---|---|---|
| 10 | `PARTIAL — 10B IMPLEMENTED` | Recurring hourly/daily/weekly UTC schedules, occurrence idempotency, restart advancement and bounded worker lifecycle are implemented/tested; planner quality and operational soak remain open. |
| 14 | `BLOCKED_EXTERNAL / CONTRACT PARTIAL` | Capability inventory truthfully reports missing Android toolchain/device evidence. |
| 15 | `PARTIAL — LOCAL GOVERNANCE` | Hashed device enrollment, one-time replay-resistant pairing, diagnostics, identity verification, last-seen tracking, revocation and authenticated routes; no encrypted PC–phone transport. |
| 16 | `PARTIAL — READ-ONLY MCP` | Approved credential-free HTTPS JSON-RPC `tools/list`/`tools/call` transport under explicit read scopes; write/external scopes disabled. |
| 17 | `PARTIAL — DECLARATIVE EXECUTION` | Provenance, capability allowlisting, draft/review/approved/revoked lifecycle and one bounded local text-file skill; no shell/code/network/provider/side-effect execution or self-learning. |
| 18 | `PARTIAL — BOUNDED LOCAL` | Fixed-role bounded orchestration, durable evidence and authenticated readback; provider-backed multi-step delegation remains open. |
| 19 | `PARTIAL — LOCAL ACTIONS` | Hashed approval parameters/nonces/sessions, future-expiry validation and single-use local schedule execution; calendar/email side effects disabled. |
| 20 | `PARTIAL — LOCAL PROVIDER` | Device/local-brain inventory and optional loopback Ollama adapter; no local service/device mesh verified. |
| 21 | `PARTIAL — LOCAL GATE` | Integrity/schema/secret-free readiness endpoints; Docker cleanup, provenance, PR and `main` integration remain open. |

The published deterministic suite at `1ca32e2bbf5df79194e2f5a9c82d3097d4b97b83` is 83 passing tests, confirmed by both push and pull-request GitHub Actions. The canonical SQLite path
is `data/my_last_ai_girlfriends.sqlite3`; it is preserved and not migrated
because its header is invalid. The verified recovery candidate remains in
`data/migration-backups/`, and migrations through version 11 have only been
executed on an isolated copy with all existing row counts preserved. No live
replacement has been performed.


## Current delivery checkpoint — 18 October 2026

- Latest source-code implementation commit verified by push and PR CI: `1ca32e2bbf5df79194e2f5a9c82d3097d4b97b83`; it includes recurring schedules, isolated recovery verification, bounded DOCX/PDF extraction and shared SQLite concurrency regression coverage.
- Its exact implementation-head CI: [push run 39130261975](https://github.com/lakshmanghosh1900-prog/MY-LAST-AI-GIRLFRIENDS/actions/runs/39130261975) and [PR run 39130266696](https://github.com/lakshmanghosh1900-prog/MY-LAST-AI-GIRLFRIENDS/actions/runs/39130266696) — PASS; 83 tests, dependency lock/sync, compileall and package build pass. Later commits are documentation-only; Draft PR #1 gives the latest published branch head and exact-head check results.
- Draft PR #1 remains open and unmerged; `main` remains `c98a091330a05ef73823d9744bfd58d5c973059f`.
- Database restoration, Stage 06 Docker cleanup/provenance, full Stage 11 voice, Stage 14 native Android, full PC–phone transport, broad MCP/skill/agent execution, external actions, device mesh and final hardening remain incomplete.
- Stage status labels in this roadmap refer to engineering scope; the current release and database blockers are not waived by a green unit-test/packaging workflow.


## Published delivery checkpoint — 18 October 2026

- Latest verified implementation commit: `cc295be03b993b55abd5422c2e84abff4cd765a3`.
- Push CI: [39111389515](https://github.com/lakshmanghosh1900-prog/MY-LAST-AI-GIRLFRIENDS/actions/runs/39111389515) — PASS.
- Pull-request CI: [39111392093](https://github.com/lakshmanghosh1900-prog/MY-LAST-AI-GIRLFRIENDS/actions/runs/39111392093) — PASS.
- Verified: 76 tests, lock validation/sync, compileall and package source/wheel build.
- A concurrent SQLite scheduler-read race exposed on an earlier PR run is fixed in the tested implementation commit by serializing read methods on the shared connection.
- Draft PR #1 remains open/unmerged; remote `main` remains `c98a091330a05ef73823d9744bfd58d5c973059f`.

## Earlier local continuation checkpoint — 18 October 2026

- Local implementation commit: `883613d`.
- `make check`: PASS — 82 tests, 0 failures, 0 skips.
- `uv lock --check`, `uv sync --locked`, compileall and `uv build`: PASS.
- Recovery candidate verifier: PASS in an isolated temporary application copy;
  live canonical replacement was not performed.
- Docker: BLOCKED_EXTERNAL because the executable is unavailable in this
  execution container; no current image/cleanup provenance is claimed.
- Database restoration, Stage 06 Docker cleanup/provenance, full voice, native Android, full PC–phone transport, broad MCP/skill/agent execution, external actions, device mesh and final hardening remain incomplete.
