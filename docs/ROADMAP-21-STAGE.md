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

The current published feature tip is `cf6ba6da5d9ff25d1929c4a70b0dac0fd85b22a6`; it adds a CI workflow that passed 76 tests (0 failures, 0 skips), locked dependency validation, compileall and `uv build`. Remote `main` remains `c98a091330a05ef73823d9744bfd58d5c973059f`, with 45 commits between the current feature tip and main. Draft PR #1 is open and unmerged. Current status is:

| Stage | Current status | Implemented slice / remaining gate |
|---|---|---|
| 14 | `BLOCKED_EXTERNAL / CONTRACT PARTIAL` | Capability inventory truthfully reports missing Android toolchain/device evidence. |
| 15 | `PARTIAL — LOCAL GOVERNANCE` | Hashed device enrollment, one-time replay-resistant pairing, diagnostics, identity verification, last-seen tracking, revocation and authenticated routes; no encrypted PC–phone transport. |
| 16 | `PARTIAL — READ-ONLY MCP` | Approved credential-free HTTPS JSON-RPC `tools/list`/`tools/call` transport under explicit read scopes; write/external scopes disabled. |
| 17 | `PARTIAL — DECLARATIVE EXECUTION` | Provenance, capability allowlisting, draft/review/approved/revoked lifecycle and one bounded local text-file skill; no shell/code/network/provider/side-effect execution or self-learning. |
| 18 | `PARTIAL — BOUNDED LOCAL` | Fixed-role bounded orchestration, durable evidence and authenticated readback; provider-backed multi-step delegation remains open. |
| 19 | `PARTIAL — LOCAL ACTIONS` | Hashed approval parameters/nonces/sessions, future-expiry validation and single-use local schedule execution; calendar/email side effects disabled. |
| 20 | `PARTIAL — LOCAL PROVIDER` | Device/local-brain inventory and optional loopback Ollama adapter; no local service/device mesh verified. |
| 21 | `PARTIAL — LOCAL GATE` | Integrity/schema/secret-free readiness endpoints; Docker cleanup, provenance, PR and `main` integration remain open. |

The current deterministic suite is 76 passing tests, confirmed by GitHub Actions at the checkpoint above. The canonical SQLite path
is `data/my_last_ai_girlfriends.sqlite3`; it is preserved and not migrated
because its header is invalid. The verified recovery candidate remains in
`data/migration-backups/`, and migrations through version 10 have only been
executed on an isolated copy with all existing row counts preserved. No live
replacement has been performed.


## Current delivery checkpoint — 18 October 2026

- Published feature HEAD: `cf6ba6da5d9ff25d1929c4a70b0dac0fd85b22a6`.
- Exact CI run: [39111020536](https://github.com/lakshmanghosh1900-prog/MY-LAST-AI-GIRLFRIENDS/actions/runs/39111020536) — PASS; 76 tests, dependency lock/sync, compileall and package build pass.
- Draft PR #1 remains open and unmerged; `main` remains `c98a091330a05ef73823d9744bfd58d5c973059f`.
- Database restoration, Stage 06 Docker cleanup/provenance, full Stage 11 voice, Stage 14 native Android, full PC–phone transport, broad MCP/skill/agent execution, external actions, device mesh and final hardening remain incomplete.
- Stage status labels in this roadmap refer to engineering scope; the current release and database blockers are not waived by a green unit-test/packaging workflow.
