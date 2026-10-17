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
The safe Stage 07A slice now implemented is explicit, local-only memory
management; it does not close Stage 07 and does not authorize remote memory
injection.
