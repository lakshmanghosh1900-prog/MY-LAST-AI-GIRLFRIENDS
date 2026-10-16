# JARVIS OMEGA v4 — Final Pre-Build Audit, Loop-Hole Review and v4.1 Readiness

**Project:** MY LAST AI GIRLFRIENDS  
**Audit/build date:** 17 October 2026  
**Mode:** documentation audit followed by the bounded vertical-slice implementation  
**Repository path checked:** `C:\Users\User\Desktop\MY LAST AI GIRLFRIENDS`  
**Git state at start:** empty directory, no `.git`, no files, empty GitHub target repository  
**Status rule:** a design is not evidence; code presence is not a passing test; a passing test is not a security proof.

## 1. Final decision

### Before implementation

**NO-GO for the broad JARVIS OMEGA v4 roadmap.** The original “do anything” scope
included high-impact phone control, messaging, payments, self-learning skills,
MCP, background agents and multi-device autonomy without a complete verified
policy, cost model or repository baseline.

**CONDITIONAL GO for the narrow v4.1 vertical slice** after it was reduced to a
single-user, local-first, read-only service with bounded provider calls and an
offline test path.

### Current release decision

**CONDITIONAL GO for local development of the implemented slice, subject to the
checks recorded in this repository.** The slice is not a public service and is
not an autonomous Android operator. Broad autonomy remains **NO-GO** until a
separate review closes its platform, privacy, authorization, reconciliation and
cost gates.

This report does not claim 100% semantic accuracy. It does require 100% pass on
the deterministic safety invariants selected for this slice before a release is
called ready.

## 2. Evidence labels

- **SOURCE-VERIFIED:** the cited primary source directly supports the narrow
  claim stated, at the stated review date.
- **PARTIALLY VERIFIED:** a source is relevant but the exact scope/date/condition
  was not independently confirmed.
- **UNVERIFIED:** the claim is retained only as an open item and must not drive
  implementation.
- **PROPOSED:** design recommendation only.
- **IMPLEMENTED:** code/configuration exists in this repository.
- **TESTED:** the named reproducible check was run and passed.
- **VERIFIED:** implementation and evidence satisfy the defined acceptance gate.

At the beginning of this work, all application controls were unimplemented.
After implementation, status is only promoted by the recorded test commands;
the final summary must not promote an unrun check.

## 3. Scope and responsibility audit

### Product meaning

“MY LAST AI GIRLFRIENDS” is the personal-assistant product umbrella. It may
eventually contain multiple companion roles, but each role has the same owner,
the same capability boundary and the same audit trail. “JARVIS OMEGA” is the
coordination engine. “She can do anything” is treated as a long-term aspiration,
not permission for uncontrolled execution. The current build is responsible
for accurate bounded execution, honest state reporting and safe stopping.

### Current responsibility boundary

The model proposes text. Ordinary code owns authentication, data class,
allowlisted tools, budget reservations, provider schema validation and task
state. Only a persisted and checked result becomes `SUCCEEDED`.

### Explicitly excluded from this release

Android Accessibility automation, SMS/email/WhatsApp sending, calls, payments,
banking, PIN/OTP/credential entry, arbitrary filesystem access, shell/code
execution, browser login automation, MCP, dynamic skills, self-learning,
sub-agents, always-on microphone/camera, vector databases, Redis, VPS/public
hosting, multi-user tenancy, autonomous schedules and external side effects.

These exclusions are executable scope boundaries, not merely documentation.

## 4. Repository and reproducibility audit

| Check | Result/status |
|---|---|
| Actual working directory | `C:\Users\User\Desktop\MY LAST AI GIRLFRIENDS` confirmed |
| Initial repository | Empty; no Git metadata or source files |
| GitHub target | `https://github.com/lakshmanghosh1900-prog/MY-LAST-AI-GIRLFRIENDS` was reachable and empty |
| Runtime | Python 3.12.11 pinned; local Python 3.14 also exists but is not the project runtime |
| Lockfile | `uv.lock` required and generated for the release |
| Dependencies | Standard library runtime; offline tests use `unittest` |
| Container | Dockerfile included; host publication must be loopback-bound |
| Test command | `make test`; Windows equivalent documented in README |
| Secrets | `.env.example` contains placeholders only; `.env` is ignored |

## 5. Loop-hole closure review

| Area | Previously identified hole | Implemented control | Required evidence |
|---|---|---|---|
| Binding | Loopback mistaken for auth | Explicit host check, bearer token, exact origin | Auth/origin tests |
| WebSocket | Unauthenticated upgrade | No WebSocket surface in MVP | Route inventory test |
| Sessions | Replay/query leakage | Header-only bearer token; no query token | Auth tests and log scan |
| Authorization | Model can grant itself tools | Static `PolicyEngine` and registry | Denial tests |
| Prompt injection | File/web text treated as instructions | Delimited untrusted data; provider tool calls rejected | Injection fixtures |
| Files | Traversal/symlink/binary/oversize | Relative root, real-path containment, suffix/size/NUL checks | Path tests |
| SSRF | Private IP/redirect/DNS rebinding | HTTPS-only, public resolved IP, pinned connection, redirect revalidation | URL/DNS tests |
| Egress | Ambient proxy bypass | Fetcher does not use URL opener/proxy; app-level IP pinning | Fetcher tests; OS firewall remains deployment responsibility |
| Budget | Concurrent overspend | SQLite immediate transaction and append-only ledger | Concurrent reservation test |
| Retry | Unknown provider result resent | No automatic retry; `NEEDS_RECONCILIATION` | Provider timeout test |
| Cancellation | Late work overwrites state | Task writes are bounded and terminal state is persisted | Lifecycle test |
| Secrets | Error/log leakage | API key only in auth header; redaction and structured metadata | Canary scan |
| Provider drift | Silent tool/capability change | OpenAI-compatible tool-call rejection and pinned model config | Adapter fixtures |
| Failure language | False “done” | `SUCCEEDED`, `SAFE_STOP`, `NEEDS_RECONCILIATION` visible | UI/API tests |

The OS-level network boundary is intentionally not claimed as implemented by a
Python process. If this service is exposed beyond loopback later, a host firewall
or an explicitly reviewed private overlay is required.

## 6. Authentication, authorization and approvals

This slice has no irreversible action approval pipeline because it has no
irreversible action. Every `/v1` endpoint requires `Authorization: Bearer ...`.
Tokens are not accepted in URLs. Browser origins are limited to the local UI's
known origins and unexpected `Host` values are rejected. The token is stored as
a SHA-256 verifier in memory; the raw token remains in the process environment
or the owner's local `.env`.

The deterministic policy enforces:

1. non-empty and size-bounded messages;
2. rejection of credentials and OTP/PIN-like content;
3. provider/data-class compatibility;
4. a static tool allowlist containing only `file.read_text` and `web.fetch`;
5. HTTPS-only, credential-free public web URLs;
6. no tool call or policy decision from model output.

If future releases add red actions, an approval record must bind the exact
canonical parameters, requesting session, approving device, policy version,
one-time nonce, expiry and resource state. Telegram buttons alone are not
approval security. That pipeline is not in this release.

## 7. SSRF, filesystem and network-isolation controls

### HTTPS fetch

The fetcher accepts only HTTPS on port 443, rejects userinfo/fragments/invalid
hosts, IDNA-normalizes host names, rejects local names, resolves all addresses,
requires every result to be globally routable, pins the selected IP for the TLS
connection, revalidates each absolute redirect, caps redirects at three, uses
identity encoding, limits bytes and accepts only text-like content types. It
never renders HTML or follows embedded resources.

The tests cover loopback, RFC1918, link-local, metadata-style, IPv6 and
IPv4-mapped private addresses, unsafe schemes, ports, credentials and redirect
conditions. DNS rebinding is reduced by resolving all addresses and dialing the
validated address; a deployment-level egress firewall remains the stronger
control.

### File root

The tool accepts clean relative paths only, rejects dot/hidden components,
absolute/drive paths, NUL bytes, path escapes, symlinks, unsupported suffixes,
binary NUL content and oversized files. The application database is outside the
approved `workspace/` root by default.

### Later sandbox requirement

No code execution exists. If added later it requires a disposable non-root
environment with no host mounts, no Docker socket, no default network, resource
limits, pinned images/dependencies and destructive cleanup tests. Docker alone
is not a sandbox proof.

## 8. Provider privacy and fallback routing

The default provider is a deterministic fake provider and uses no network. The
remote adapter is opt-in. Personal and sensitive content is stopped before a
remote call unless `JARVIS_ALLOW_REMOTE_PERSONAL_DATA=true` is set. Prohibited
secrets are rejected regardless of provider. No automatic provider fallback is
implemented; a remote timeout becomes `NEEDS_RECONCILIATION`.

The provider adapter sends credentials only in an authorization header, limits
response size, rejects tool/function calls, validates JSON schema and records
the returned model identifier when available. Provider model and pricing are
configuration values, not hidden constants.

## 9. Corrected financial model

### Inputs and source status

| Input | Value | Status/source |
|---|---:|---|
| FX planning rate | ₹95/USD | **PARTIALLY VERIFIED**, rounded from Reuters report dated 16 Oct 2026; actual bank/card rate may differ |
| Flash intro input | $0.75 / 1M tokens | **SOURCE-VERIFIED in supplied baseline**, official pricing URL below, through 31 Dec 2026 |
| Flash intro output | $3.75 / 1M tokens | **SOURCE-VERIFIED in supplied baseline**, official pricing URL below, through 31 Dec 2026 |
| Flash 2027 input/output | $1.50 / $7.50 | **SOURCE-VERIFIED in supplied baseline**, from 1 Jan 2027 |
| Argon launch input/output | $2 / $10 | **SOURCE-VERIFIED in supplied baseline**, through 30 Nov 2026 |
| Argon standard input/output | $4 / $20 | **SOURCE-VERIFIED in supplied baseline**, from 1 Dec 2026 |
| Search grounding | 5,000 free requests; then $14/1,000 | **PARTIALLY VERIFIED**; count actual underlying requests |
| Live audio | $0.005 incoming/min and $0.018 outgoing/min | **PARTIALLY VERIFIED**; text tokens may be additional |
| Tax/GST/card markup | not included | **UNVERIFIED**; inspect invoice/adviser |

Primary URLs: [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing),
[Gemini models](https://ai.google.dev/gemini-api/docs/models),
[Reuters 16 Oct 2026 FX report](https://www.reuters.com/world/india/rupee-rise-offshore-traders-cut-bearish-bets-rbi-clarifies-hedging-rules-2026-10-16/).
Verification date for this register: 17 October 2026. Live fetch of some
provider pages was not available in this session; the rates above are retained
as supplied-baseline facts and must be refreshed before a billing decision.

### Scenario A — local-first

Cloud APIs, search and voice: ₹0. Incremental electricity assumption:

```text
40–110 kWh/month × ₹8–₹10/kWh = ₹320–₹1,100/month
backup/storage allowance = ₹0–₹500/month
total planning range = ₹320–₹1,600/month
```

Existing hardware and internet are excluded. Local model performance is not
promised until measured on the target PC.

### Scenario B — controlled hybrid, Flash intro pricing

Assumptions: 10M input tokens, 2M output tokens, 6,000 search requests,
optional 300 incoming and 300 outgoing Live minutes, no Argon or sub-agents.

```text
input  = 10 × $0.75 = $7.50
output =  2 × $3.75 = $7.50
search = (6,000 - 5,000) / 1,000 × $14 = $14.00
text + search = $29.00
voice = (300 × $0.005) + (300 × $0.018) = $6.90
all-in API estimate = $35.90
```

At ₹95/USD:

```text
no voice: $29 × ₹95 × 1.10 reserve = ₹3,028.50
voice:    $35.90 × ₹95 × 1.10 reserve = ₹3,751.55
hosting/storage allowance = ₹500–₹1,800
planning total = ₹3,528.50–₹5,551.55/month
```

From 1 January 2027, the same text/search usage becomes:

```text
input = 10 × $1.50 = $15.00
output = 2 × $7.50 = $15.00
search = $14.00
text + search = $44.00
no voice with reserve = $44 × ₹95 × 1.10 = ₹4,598
```

### Scenario C — high-use Argon after 1 December 2026

Assumptions: 20M input, 4M output, 20,000 searches, 1,000 incoming and 1,000
outgoing Live minutes, plus ₹1,300–₹4,000 hosting/storage allowance.

```text
Argon input  = 20 × $4  = $80
Argon output =  4 × $20 = $80
search       = (20,000 - 5,000) / 1,000 × $14 = $210
voice        = (1,000 × $0.005) + (1,000 × $0.018) = $23
total        = $393
$393 × ₹95 × 1.10 = ₹41,068.50
plus hosting/storage = ₹42,368.50–₹45,068.50/month
```

These are planning arithmetic, not a maximum bill. Extra context, retries,
provider-side tokenization, multiple search queries, text tokens in voice,
taxes and FX differences can increase the invoice.

### Enforced cost defaults

The implementation defaults to ₹3,500/month planning budget, with provider
reservations made before each remote call. Fake calls cost zero. Premium Argon,
voice and paid search are not enabled by this default. A reservation race must
not permit a new call after the configured limit.

## 10. UX failure/recovery matrix

| Situation | User-visible result | System behavior |
|---|---|---|
| Empty/oversized message | Clear validation text | No provider call |
| Prohibited secret | “Credentials are never sent” | Deny and audit code only |
| Personal data + remote disabled | Local-safe stop | No remote payload |
| Provider timeout | “Outcome uncertain; not retried” | `NEEDS_RECONCILIATION` |
| Provider schema/tool call | “Provider output was not accepted” | Safe stop, no claim of success |
| Over-budget | Budget message with local option | No new remote call |
| Bad file path | Path reason only | No outside-root read |
| Unsafe URL | Destination blocked | No network request |
| Partial/failed internal work | Safe-stop status | No hidden retry |
| Bengali/Banglish text | Same text is preserved | No forced translation |
| Connection loss | UI shows disconnected | No external side effect is claimed |

Every response distinguishes `SUCCEEDED`, `SAFE_STOP` and
`NEEDS_RECONCILIATION`; the word “Done” is not used for an unverified result.

## 11. Test strategy and release gates

### Required test groups

1. Configuration and loopback-binding validation.
2. Authentication, host/origin and route authorization.
3. Policy classification and prohibited-data rejection.
4. File traversal, symlink, type, NUL and size limits.
5. URL scheme, port, credential, private-IP and redirect validation.
6. Concurrent budget reservations and idempotent settlement.
7. Fake-provider prompt-injection and output-boundary behavior.
8. Service persistence, task states and safe-stop responses.
9. Compile and offline reproducibility.

### Objective gates

- **G-REPRO:** pinned runtime, lockfile, Dockerfile and offline test command exist.
- **G-AUTH:** unauthorized API requests are rejected; no token query surface.
- **G-POLICY:** unknown/prohibited tools and secrets are rejected before provider.
- **G-FS:** path escapes, links, binaries and oversize files are blocked.
- **G-SSRF:** non-HTTPS, credentials, private destinations and unsafe redirects
  are blocked by the fetcher.
- **G-BUDGET:** concurrent reservations cannot exceed the configured ledger.
- **G-PROVIDER:** malformed/tool-call outputs cannot become successful tasks.
- **G-STATE:** provider uncertainty is not auto-retried or reported as success.
- **G-DOCS:** README has exact setup, run, test, Docker and reset instructions.

No quality score can offset a failed security gate. Passing these tests does
not prove resistance to every future attack.

## 12. Dependency-aware roadmap

| Phase | Result | Exit gate |
|---|---|---|
| 0 | Current slice | All G-* gates pass and local smoke flow works |
| 1 | Provider failover | Data-class, privacy, drift, cost and fallback tests |
| 2 | Private phone/PWA access | Enrollment, revocation, private-network and mobile UX evidence |
| 3 | Native Android | Actual device process-death/permission tests; policy route selected |
| 4 | Voice | Audio consent, retention, battery and actual pricing evidence |
| 5 | Skills/MCP | Allowlist, auth/audience, sandbox, provenance and rollback |
| 6 | External actions | Action-bound approvals, idempotency, reconciliation and abuse tests |
| 7 | Public product | Multi-user isolation, legal/privacy, operations and support review |

## 13. Claims and source register S1–S25

The original bibliography URLs were not included in the supplied partial audit.
The mapping below is therefore a reconstruction of claim topics, not proof of
original citations.

| ID | Claim | Status on 17 Oct 2026 | Primary source/disposition |
|---|---|---|---|
| S1 | Gemini 3.8 Flash stable/listed | SOURCE-VERIFIED in supplied baseline | <https://ai.google.dev/gemini-api/docs/models> |
| S2 | Flash modalities/capabilities | SOURCE-VERIFIED in supplied baseline | <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash> |
| S3 | Gemini 3.7 auto-routes to 3.8 | UNVERIFIED exact behavior | Do not rely on implicit routing |
| S4 | Gemini 4 Argon model/capabilities | SOURCE-VERIFIED in supplied baseline | <https://ai.google.dev/gemini-api/docs/models/gemini-4-argon> |
| S5 | Argon model-card critical capability risk | PARTIALLY VERIFIED | Model card link requires direct review before security use |
| S6 | Argon paid-only and pricing | SOURCE-VERIFIED in supplied baseline | <https://ai.google.dev/gemini-api/docs/pricing> |
| S7 | Secondary Argon price source | SUPERSEDED | Use official pricing page |
| S8 | Secondary Argon date source | SUPERSEDED | Use official pricing page |
| S9 | Secondary Flash price source | SUPERSEDED | Use official pricing page |
| S10 | Free/Paid data use and search price | SOURCE-VERIFIED in supplied baseline | <https://ai.google.dev/gemini-api/docs/pricing> |
| S11 | Interactions API default since June 2026 | PARTIALLY VERIFIED | Confirm migration docs before adapter choice |
| S12 | Generation parameter behavior | PARTIALLY VERIFIED | Confirm endpoint-specific docs and contract tests |
| S13 | Play Accessibility restrictions | SOURCE-VERIFIED in supplied baseline | <https://support.google.com/googleplay/android-developer/answer/10964491?hl=en> |
| S14 | Android foreground/background restrictions | SOURCE-VERIFIED in supplied baseline | <https://developer.android.com/develop/background-work/services/fgs/changes> and <https://developer.android.com/develop/background-work/services/fgs/restrictions-bg-start> |
| S15 | Universal Termux 32-process/kill claim | PARTIALLY VERIFIED | Treat as device/OS-dependent; no MVP dependency |
| S16 | MCP auth/resource/audience/token rules | SOURCE-VERIFIED in supplied baseline | <https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization> |
| S17 | WhatsApp blanket AI ban from 15 Jan 2026 | UNVERIFIED as stated | <https://whatsappbusiness.com/policy/> does not establish the blanket claim in the reviewed text |
| S18 | DPDP commencement dates | PARTIALLY VERIFIED | <https://www.meity.gov.in/documents/act-and-policies/digital-personal-data-protection-rules-2025-gDOxUjMtQWa?pageTitle=Digital-Personal-Data-Protection-Rules-2025%3B>; exact dates require legal/source review |
| S19 | OWASP Agentic Top 10 2026 | SOURCE-VERIFIED framework existence in supplied baseline | <https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/> |
| S20 | OpenClaw malicious-skill percentages | PARTIALLY VERIFIED | Secondary audits vary; never used as a numeric design fact |
| S21 | Groq free limits/privacy | UNVERIFIED here | No fallback until official limits/terms are reviewed |
| S22 | ₹96.2948/USD on 18 May 2026 | LEGACY SOURCE NOT RECOVERED | Planning FX uses Reuters 16 Oct 2026 ₹94.96, rounded to ₹95 |
| S23 | Tailscale Personal plan | SOURCE-VERIFIED in supplied baseline | <https://tailscale.com/pricing>; terms must be rechecked for commercial use |
| S24 | Gemma 4 edge/mobile feasibility | SOURCE-VERIFIED family positioning; runtime performance requires device test | <https://ai.google.dev/gemma/docs/core> |
| S25 | OpenDroid README crypto address/solo maintainer | UNVERIFIED here | Original repository URL absent; do not execute or grant permissions |

## 14. Platform and legal disposition

- **Android:** technical sideloading is not equivalent to Play eligibility or
  reliability. No Android operator is included.
- **Accessibility:** no public Play design is based on autonomous cross-app
  initiation, planning or execution.
- **WhatsApp:** the supplied blanket ban is not treated as established; the
  integration is excluded because its current terms/product path are outside
  this verified slice.
- **DPDP:** no personal-use exemption or commencement conclusion is asserted.
  Public/multi-user use requires a new legal review.
- **MCP:** excluded; future use requires per-server credentials, resource/audience
  validation and token-passthrough prevention.

## 15. Unresolved blockers and human decisions

The owner authorized this local build, so no additional approval was required to
create the bounded slice. The following remain real blockers for expansion:

1. Provider prices, free/paid data terms and model capabilities must be refreshed
   from primary pages before billing or sensitive cloud use.
2. The actual bank/card FX and tax treatment are unknown.
3. OS-level egress firewalling is not created by this Python process.
4. No Android device matrix or Play policy review has been performed.
5. No red-action approval/reconciliation implementation exists because red
   actions are excluded.
6. The remote provider adapter has not been exercised against a live endpoint;
   only offline/fake-provider behavior can be verified without credentials.
7. Container build success depends on the local Docker daemon and network cache;
   it must be run and recorded separately.
8. GitHub push requires valid credentials; no token is stored in the repository.

## 16. Change log

1. Confirmed the real workspace and empty GitHub target; did not assume the
   earlier `jarvis-os` path.
2. Converted the broad “Any Job” vision into a local-first read-only slice.
3. Added a pinned Python runtime, lockfile workflow, Dockerfile, README and
   offline test command.
4. Added SQLite task, message, policy, provider, budget and audit persistence.
5. Added deterministic auth/policy, file-root protection and constrained fetch.
6. Added fake provider default and explicit remote-provider boundary.
7. Added transparent cost arithmetic and scheduled-price sensitivity.
8. Added claims/source labels and retained unresolved external claims as such.
9. Added UX recovery states and objective release gates.
10. Kept Android autonomy, external side effects, skills, MCP, code execution and
    public hosting outside this release.

## 17. Verification log for this release

The following checks were actually run from the confirmed workspace. These
results apply to the current source state; a later change requires rerunning
the relevant checks.

| Command | Result | Evidence/status |
|---|---|---|
| `uv lock` | passed | `uv.lock` generated with Python 3.12 constraint |
| `uv lock --check` | passed | lockfile is consistent |
| `python -m compileall -q src tests` | passed | source and tests compile |
| `python -m unittest discover -s tests -p "test_*.py" -v` | passed | 11 tests passed; 1 symlink test skipped because Windows account cannot create symlinks |
| `docker build --tag jarvis-omega:0.1.0 .` | passed | image built from `python:3.12.11-slim` |
| Docker authenticated health/conversation/message smoke | passed | `READY`, conversation created, fake-provider task `SUCCEEDED` |

The symlink test is a platform limitation of this machine, not a pass. The
implementation still rejects a symlink when the operating system exposes it.
The remote provider, public web fetch against a live host, host firewall and
Android features remain untested and are intentionally outside this release.
