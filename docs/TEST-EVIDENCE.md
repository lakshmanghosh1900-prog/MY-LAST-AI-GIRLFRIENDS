# MY LAST AI GIRLFRIENDS — Test Evidence

This file records commands that were actually executed. Historical evidence in
`docs/FINAL-AUDIT.md` is kept separate from current execution evidence.

## Baseline — 17 October 2026

Working directory:

```text
C:\Users\User\Desktop\MY LAST AI GIRLFRIENDS
```

Equivalent container path used for execution:

```text
/c/Users/User/Desktop/MY LAST AI GIRLFRIENDS
```

### Reproducibility checks

```text
uv run --locked python --version
PASS — Using CPython 3.12.11

uv lock --check
PASS — resolved and checked one locked package

uv sync --locked
PASS — editable my-last-ai-girlfriends package installed
```

### Application checks

```text
make check
PASS — compileall completed
PASS — 27 tests ran, 27 passed, 0 failed, 0 skipped

uv run --locked my-last-ai-girlfriends doctor
PASS — valid token status, real mode, Gemini provider/model and key presence
       reported without displaying secret values
```

### Runtime check and defect

An authenticated launch smoke was attempted with the existing ignored local
configuration. The application did not reach HTTP readiness because SQLite
raised `OperationalError: disk I/O error` while opening the canonical database
on the mounted workspace. The full database plus WAL was copied to a container
filesystem, opened successfully, and transactionally backed up. The recovered
database passed `PRAGMA integrity_check` and retained 1 conversation, 24
messages, 17 tasks, 8 provider calls, 16 budget events and 114 audit events.

The initial runtime check is therefore `FAIL` for the mounted sidecar state,
not a test pass. The runtime fallback and a repeat launch smoke belong to Stage
01 and will be recorded here after execution.

## Stage 01 verification — 17 October 2026

### Automated checks

```text
PYTHONPATH="$PWD/src" uv run --locked python -m unittest tests.test_configuration_provider -v
PASS — 9 tests

PYTHONPATH="$PWD/src" uv run --locked python -m unittest tests.test_migration -v
PASS — 2 tests

uv run --locked python -m compileall -q src tests
PASS

make check
PASS — compileall and 32 tests, 32 passed, 0 failed, 0 skipped
```

## Stage 07A local memory evidence

```text
PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_memory tests.test_http_api -v
PASS — 7 tests

make check
PASS — compileall and 36 tests, 36 passed, 0 failed, 0 skipped
```

Verified behavior includes explicit local creation, global and
conversation-scoped listing, cross-conversation isolation, tombstone deletion,
expiration filtering, migration version 3, unauthorized API rejection,
prohibited/sensitive rejection and persistence through service restart. Memory
contents are not written to audit metadata or provider context.

The current canonical database file was not migrated because independent
inspection found it has a zeroed/non-SQLite header; the valid recovery candidate
remains preserved under the ignored migration-backups directory. Tests use
temporary databases only.

## Stage 08A local document evidence

```text
PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_documents tests.test_memory tests.test_http_api -v
PASS — 11 tests

make check
PASS — compileall and 40 tests, 40 passed, 0 failed, 0 skipped
```

Verified behavior includes deterministic bounded chunking, approved-root text
indexing, content hashing, migration version 4, idempotent re-indexing,
authenticated search, deletion/tombstoning, traversal rejection and empty
query rejection. This is local text indexing only; no PDF/DOCX extraction,
provider grounding or citation claim is made.

## Stage 09A research evidence

```text
PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_research tests.test_documents tests.test_memory tests.test_http_api -v
PASS — 14 tests

make check
PASS — compileall and 43 tests, 43 passed, 0 failed, 0 skipped
```

Verified behavior includes explicit public HTTPS URL validation, secret-like
query rejection, bounded multi-source runs, partial-failure status, source
hashes, structured citations, authenticated API behavior and no automatic
provider answer. Tests use mocked fetch boundaries; they do not claim live
internet research quality.

## Stage 10A scheduler evidence

```text
PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_scheduler tests.test_research tests.test_documents tests.test_memory tests.test_http_api -v
PASS — 17 tests

make check
PASS — compileall and 47 tests, 47 passed, 0 failed, 0 skipped
```

## Stage 11 / Stage 12A evidence

```text
PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_tool_registry tests.test_policy_tools tests.test_http_api -v
PASS — 11 tests

make check
PASS — compileall and 47 tests, 47 passed, 0 failed, 0 skipped
```

Stage 11 is `BLOCKED_EXTERNAL` because no real audio stack or hardware is
available. Stage 12A verifies a static read-only registry, exact argument
validation and rejection of unallowlisted tools; it does not claim arbitrary
automation or external actions.

## Stage 13A evaluation evidence

```text
PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_evaluation tests.test_tool_registry tests.test_scheduler -v
PASS — 5 tests

make check
PASS — compileall and 48 tests, 48 passed, 0 failed, 0 skipped
```

The versioned local evaluation reports truthful offline output, prohibited
input safe-stop and explicit memory creation. It is deterministic and does not
claim live-provider quality, voice, device or external-action evaluation.

## Current publication checkpoint

The owner-verified published feature branch baseline is
`ebd37c3d5588b02b8af27b3a02a90125e94b55c2`. Its isolated worktree check below
ran 48 tests. Local HEAD is `52b5ef1`, which adds the Stage 15–21 governance
slice, one-time device pairing, durable agent-run readback and approval expiry
validation and currently runs 53 tests; it has not been published. Earlier
`3acccc3` and `c6ef387` references in this file are historical checkpoints only.

The published baseline and local continuation checks are:

```text
make -C /tmp/mlag-ebd-baseline check
PASS — published ebd37c3 baseline, compileall and 48 tests, 48 passed, 0 failed, 0 skipped

make check
PASS — compileall and 53 tests, 53 passed, 0 failed, 0 skipped

PYTHONPATH="$PWD/src:$PWD/tests" uv run --locked python -m unittest tests.test_governance tests.test_http_api -v
PASS — 8 tests
```

Verified behavior includes timezone-required schedule normalization, durable
one-shot creation, due execution, separate run persistence, idempotent second
execution, cancellation and existing message-policy/task lifecycle reuse. No
background worker or external side effect is claimed.

### Current SQLite recovery evidence

```text
canonical: data/my_last_ai_girlfriends.sqlite3
canonical SHA-256: 2e3c9e3a21b33a867a9958ebbec68e960cf8daae652073f91bca0b6cdc8810d5
canonical result: DatabaseError: file is not a database

recovery: data/migration-backups/my_last_ai_girlfriends.recovered.20261017T103434Z.sqlite3
recovery SHA-256: 47ada56b639d5edf9194e79f19a3391b031c5ca20dbbfc56eafad1ebffaea073
recovery integrity: ok
recovery counts: conversations=1 messages=24 tasks=17 provider_calls=8 budget_events=16 audit_events=114
original preservation: data/migration-backups/canonical-invalid-preserved-20261018T000000Z.sqlite3
original/preservation hashes: identical

isolated recovery migration: PASS — schema version 8, integrity ok, all six
existing record counts preserved, governance tables created
live replacement: NOT PERFORMED
```

The canonical file and its owner data remain untouched. The recovery candidate
was copied to a temporary isolated database before initialization; no migration
was run against the invalid live path.

### Authenticated application smoke

The CLI was started with the ignored local configuration. Without printing the
token, the smoke verified:

```text
GET /v1/health       200, state READY, product MY LAST AI GIRLFRIENDS
POST /v1/conversations 201, conversation identifier present
```

The configured mode was real and `provider_status.connected` was false before
any provider request, which is truthful: local readiness is not live Gemini
connectivity. No paid provider call was made in this smoke.

### Reproducibility/security notes

- `git diff --check` is required before the Stage 01 commit.
- Only tracked source, tests and documentation are eligible for staging.
- `.env`, SQLite files, WAL/SHM files, migration backups and generated bytecode
  remain ignored and are not release artifacts.
- Direct live Gemini application evidence remains a later Stage 03 check.

## Historical Git publication evidence

The verified Stage 01 commit is local at `31bc78a`. The attempted publication
command was:

```text
git push --set-upstream origin feat/mlag-real-ai-premium-ui
```

The first publication attempt was `BLOCKED_EXTERNAL` — GitHub HTTPS
authentication was unavailable:
`fatal: could not read Username for 'https://github.com': No such device or
address`.

## Historical Git publication evidence — rechecked at the `3acccc3` resume checkpoint

```text
git fetch origin --prune
PASS

git ls-remote --heads origin feat/mlag-real-ai-premium-ui
PASS — 3acccc3ef86cf7f4c44410da76c9ea8d3985982a

git ls-remote --heads origin main
PASS — c98a091330a05ef73823d9744bfd58d5c973059f

GitHub API pull-request query for head feat/mlag-real-ai-premium-ui, base main
HISTORICAL PASS — empty result; no pull request existed at that checkpoint
```

The feature branch was published and matched the local tip at that historical
recheck. `main` remains at the earlier commit. No merge was claimed. The current
owner-verified publication and PR #1 state are recorded in the current
checkpoint sections below; the `gh` CLI remains unavailable in this container.

Historical resume publication retry:

```text
git push origin feat/mlag-real-ai-premium-ui
BLOCKED_EXTERNAL — fatal: could not read Username for 'https://github.com': No such device or address
```

The local status candidate at that retry was `d93b852`; later owner-side
publication advanced the remote feature branch through `3acccc3`.

## Stage 02 verification — 17 October 2026

```text
PYTHONPATH="$PWD/src" uv run --locked python -m unittest tests.test_migration -v
PASS — 2 tests, including source preservation and second-run idempotency

PYTHONPATH="$PWD/src" uv run --locked python -m unittest tests.test_configuration_provider -v
PASS — 9 tests, including legacy/new compatibility conflict behavior

uv run --locked python -m compileall -q src tests
PASS

make check
PASS — compileall and 32 tests, 32 passed, 0 failed, 0 skipped
```

The current CLI was started against the recovered canonical database and an
authenticated `GET /v1/health` returned `200`, `state=READY` and
`database=ready`. No token value or conversation content was printed.

## Stage 03 live application evidence — 17 October 2026

The configured local `.env` was used in memory by the running application. The
token and provider key were not printed or stored in this document. After an
authenticated health check, remote conversation consent was enabled through
the application endpoint and one conversation received three sequential
requests.

```text
health: 200, mode=real, provider=gemini, connected=false before a call
consent: 200, enabled=true
conversation: 201
request 1: 200, SUCCEEDED, provider=gemini, model=gemini-3.8-flash, ai_generated=true
request 2: 200, SUCCEEDED, provider=gemini, model=gemini-3.8-flash, ai_generated=true
request 3: 200, SUCCEEDED, provider=gemini, model=gemini-3.8-flash, ai_generated=true
```

The first and third prompts requested exact markers; the observed responses
contained the requested markers. The second response recalled the first marker,
proving application-level same-conversation context for this run. This is a
real provider smoke result for this configured environment, not a mock result.

## Stage 03 deterministic provider evidence

```text
PYTHONPATH="$PWD/src" uv run --locked python -m unittest tests.test_configuration_provider -v
PASS — 12 tests

make check
PASS — compileall and 32 tests, 32 passed, 0 failed, 0 skipped
```

## Stage 04 deterministic context evidence

The service suite verifies bounded chronological context, exact-once current
message insertion, same-conversation history, cross-conversation isolation,
prohibited-input handling, and no offline fallback after real-provider failure.
Those checks are included in the 32-test `make check` result above.

## Evidence rules

- A mocked provider response proves only the adapter contract, not live Gemini.
- A live Gemini result will be recorded only when an application-level request
  actually completes with the owner-configured endpoint.
- A skipped symlink test is not silently counted as a pass when the platform
  cannot create the fixture.
- Secrets, raw conversation content and private database payloads are never
  copied into this evidence file.

## Stage 05 and Stage 06 verification — 17 October 2026

Stage 05 behavior is covered by the existing UI contract, HTTP API, policy and
read-only tool tests in the full suite. The source audit confirmed responsive
mobile CSS, keyboard handling, session reset, explicit offline labeling,
`textContent`-only dynamic rendering, no external CDN, bounded filesystem
access, HTTPS public-destination checks and readable HTML extraction.

```text
make check
PASS — compileall and 32 tests, 32 passed, 0 failed, 0 skipped

docker --version
BLOCKED_EXTERNAL — /bin/bash: docker: command not found

docker info --format '{{.ServerVersion}}'
BLOCKED_EXTERNAL — /bin/bash: docker: command not found

command -v powershell.exe; command -v pwsh; command -v where.exe
NOT_RUN — no native Windows command bridge is available in this WSL execution container

Native Windows Docker paths under /mnt/c and /c/Program Files/Docker
NOT_FOUND in the mounted filesystem

Host Docker build/smoke evidence supplied by the owner
Container smoke assertions and a successful image-build result are present in
the current owner supplement. Exact source-commit provenance and cleanup result
are not verified.
```

The deterministic MVP checks are green. The current owner supplement reports
these container smoke assertions, recorded separately from local checks:

```text
owner: Docker container smoke reported PASS
owner: authenticated health reached READY
owner: unauthenticated health returned HTTP 401
owner: authenticated conversation creation succeeded
owner: offline message succeeded with ai_generated=false and explicit not-AI label
```

Owner evidence status:

```text
Docker image build result         OWNER-SUPPLIED PASS
Image source-commit provenance   UNVERIFIED
Container cleanup                 PENDING — finally was separate; result not supplied
```

Earlier owner-evidence publication retries after `3acccc3` are historical. The
current owner-published baseline is `ebd37c3`:

```text
git push origin feat/mlag-real-ai-premium-ui
NOT RUN for the current unpublished continuation commits
```

Remote feature SHA: owner-verified `ebd37c3`; local continuation commits
`1df67f6`, `a3106fb`, `52b5ef1` and later changes are not remote. The local commits `2200953` and
`94a990c` remain preserved.

The container assertions and build result are not independently reproduced
here because this execution container has no Docker CLI or native Windows
bridge. Stage 06 remains blocked on cleanup and normal PR/main integration;
source-commit provenance is also unverified. No cleanup PASS, merge or release
readiness is claimed.

Current reconciliation candidate checks at published baseline `ebd37c3` plus
local continuation `52b5ef1`:

```text
uv run --locked python --version
PASS — Python 3.12.11
uv lock --check
PASS
uv sync --locked
PASS
uv run --locked python -m compileall -q src tests
PASS
make check
PASS — 53 tests, 0 failures, 0 skips
git diff --check
PASS
secret scan of release diff
PASS — no credential/key markers; ordinary `Bearer` protocol references are not secrets
```

### Draft PR #1 status

```text
GitHub pull-request API: open, draft=true, head=ebd37c3, base=c98a091
mergeable: true
mergeable_state: clean
status contexts: 0
check runs: 0
```

The API did not reproduce a `mergeable=false` state. The PR remains a draft and
was not merged; its body is stale relative to the published 48-test baseline and
the local continuation. The `gh` executable is unavailable, so no PR mutation or
merge operation was attempted.
