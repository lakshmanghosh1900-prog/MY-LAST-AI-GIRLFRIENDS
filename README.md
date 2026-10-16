# MY LAST AI GIRLFRIENDS — JARVIS OMEGA

JARVIS OMEGA is a local-first personal assistant vertical slice for the project
named **MY LAST AI GIRLFRIENDS**. The name means a persistent, capable personal
companion that can grow into many specialized “girlfriend” personas without
giving any persona permission to bypass the owner, the operating system, the
budget, or the verified state of an action. In this first build, the name is a
product identity, not a claim that the system can safely do literally anything.

## What is built

This release is a reproducible, single-user, loopback-first service with:

- an authenticated local browser UI;
- a deterministic policy layer outside the model;
- an explicit task lifecycle and safe-stop states;
- an offline fake provider for repeatable tests and local development;
- an opt-in OpenAI-compatible provider adapter with bounded output and timeout;
- a transactional SQLite budget ledger;
- a read-only text-file tool rooted at `workspace/`;
- a constrained HTTPS public-fetch tool with DNS/IP, redirect, size and type checks;
- redacted audit metadata and a small health/budget API;
- no phone control, Accessibility automation, payments, messaging, shell, code
  execution, MCP, dynamic skills, background agents or public hosting.

## Responsibility and execution accuracy

The assistant's responsibility is to **propose and explain**, while ordinary
code decides whether a request is permitted, whether a provider call fits the
budget, and whether the result passed deterministic checks. The model is never
the authority for permissions, tools, policy, budget or success.

No AI system can truthfully promise 100% semantic accuracy. This build instead
uses measurable invariants: unauthorized tools are denied, secrets are not
accepted as model input, unsafe paths/URLs are blocked, budgets are reserved
transactionally, and only verified provider text is shown as a successful task.
Any future feature must add its own tests and release gates before it is
enabled.

## Runtime and reproducibility

- Python `3.12.11` is pinned in `.python-version`.
- The application uses the Python standard library at runtime.
- `uv.lock` is committed for reproducible project metadata.
- The default provider is offline and deterministic.
- No provider credential is needed to run the test suite.

## Setup

### Windows PowerShell

```powershell
uv python install 3.12.11
uv venv --python 3.12.11
Copy-Item .env.example .env
# Replace JARVIS_AUTH_TOKEN in .env with a random value of at least 32 characters.
$env:PYTHONPATH = "$PWD\src"
python -m jarvis_omega.main
```

Open <http://127.0.0.1:8787>, paste the same token, and connect. The service
binds to loopback by default. The `workspace/` directory is the only approved
file root; use `/file README.txt` in the chat to read a text file.

### Linux/macOS

```bash
uv python install 3.12.11
uv venv --python 3.12.11
cp .env.example .env
# Replace JARVIS_AUTH_TOKEN in .env with a random value of at least 32 characters.
export PYTHONPATH="$PWD/src"
python -m jarvis_omega.main
```

The `.env` loader is intentionally small and does not overwrite an existing
process environment variable.

## Test and check commands

The canonical offline test command is:

```bash
make test
```

On Windows, where GNU Make may not be installed, run the same command body:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -m unittest discover -s tests -p "test_*.py" -v
```

The broader check is:

```bash
make check
```

It compiles the source and runs the offline tests. Tests use temporary SQLite
databases and fake providers; they do not contact an AI service or the public
internet.

## Optional remote provider

Remote use is disabled by default. To opt in, set:

```text
JARVIS_PROVIDER=openai-compatible
JARVIS_PROVIDER_URL=https://your-approved-endpoint.example/v1
JARVIS_PROVIDER_API_KEY=your-secret-kept-only-in-.env
JARVIS_ALLOW_REMOTE_PERSONAL_DATA=false
```

With the default `false`, ordinary personal text and `/file` requests are
stopped before any remote data transfer. `/fetch https://...` is treated as
public content but remains untrusted and is subject to the fetcher limits.
Review the provider's current data-use terms and pricing before enabling it.

## Docker

Build and run with the host port bound to loopback:

```bash
docker run --rm -it --env-file .env -p 127.0.0.1:8787:8787 \
  -v "$(pwd)/data:/app/data" jarvis-omega:0.1.0
```

The container listens on `0.0.0.0` inside the container because Docker's port
mapping is the boundary. Do not publish it as `-p 8787:8787` on a shared host.

## Safe scope

The current build deliberately does **not** implement an autonomous Android
operator, Accessibility automation, SMS/email sending, payments, banking,
OTP/PIN handling, arbitrary filesystem access, shell/code execution, browser
login automation, external side effects, MCP, skills, sub-agents, vector DB,
VPS deployment, multi-user accounts, always-on microphone, or public hosting.
These are separate features with separate platform, privacy, security and cost
reviews; they are not hidden behind a UI switch.

## Project documents

- [`docs/FINAL-AUDIT.md`](docs/FINAL-AUDIT.md) — completed documentation-only
  audit, loop-hole review, status labels, cost arithmetic, source register,
  release gates, unresolved items and final build decision.
- [`docs/BLUEPRINT-v4.1.md`](docs/BLUEPRINT-v4.1.md) — the implemented vertical
  slice blueprint, responsibilities, state machine and dependency-aware roadmap.

## Reset local data

Stop the service, then remove the local `data/` directory. This deletes the
SQLite conversation and audit database. Do not delete `workspace/` unless its
sample files are no longer wanted.
