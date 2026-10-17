# P0 evaluation and remaining release work

## Local evidence

The implementation has 87 passing automated tests covering 32 manually labeled synthetic workflow cases, input/rule validation, feasibility, comparison, evidence references, CLI round trips, report escaping, and output safety. The workflow gold labels are committed in [cases.json](../tests/fixtures/cases.json); these labels were reviewed as synthetic expectations rather than produced from verifier output.

All 87 tests passed on Python 3.14.7 and a separate temporary Python 3.12.14 environment on 2026-10-16. Exact dependency versions are recorded in [constraints.txt](../constraints.txt). The installed CLI also reproduced the expected baseline, regression, standalone, and strict-unknown exits. Run `python -m pytest -q` after installing the project to reproduce the suite; [CI](../.github/workflows/ci.yml) defines Python 3.12 and 3.14 runs but has not been executed on GitHub during this session.

| Check | Scope and evidence |
|---|---|
| Verdict agreement | All three rule results match labels across 32 workflows: 96 expected rule outcomes |
| Unknown handling | Code, dynamic/unsupported conditions, disabled controls, loops, error routing, and unsupported ports do not silently pass affected path rules |
| Failure with uncertainty | A supported bypass remains FAIL while a separate unknown route remains disclosed |
| Evidence references | Emitted node, edge, and parameter references are validated; tests resolve them against fixture JSON |
| Repeatability | Three identical library runs compare equal; repeated CLI runs write identical JSON/Markdown |
| Nonmaterial edits | Rename, node reordering, and canvas changes preserve semantic identity; failing-finding reordering is also checked |
| Gate behavior | Standalone, introduced, persisting, resolved, strict-unknown, all-failures, and warnings-only cases |
| Input safety | Oversize/deep/invalid inputs, duplicate keys/IDs, YAML aliases/tags, non-finite numbers, invalid approvals, and unsupported fields |
| Output safety | Escaped Markdown, restrictive report file permissions, input-overwrite prevention, and errors on unwritable output |
| Offline behavior | Imported code remains data; network creation is prohibited in the security fixture |

The passing baseline and deliberately broken candidate are runnable from [README.md](../README.md). The broken comparison returns exit 1 with `REQ-004 / FAIL / INTRODUCED` and the supported bypass path. This is local implementation evidence, not an independent benchmark or a claim of complete n8n support.

## Interpretation limits

The synthetic cases were used while developing the engine; they are not a blinded holdout. A passing suite establishes agreement on these cases only. The current adapter supports a restricted node/version/condition model and declared typed input assumptions, not live execution, external approval, missing/null coercion, or arbitrary connector behavior.

Evidence is capped at eight routes and exploration is bounded. Coverage limitations remain visible; changed conditions on an already failing route can be CHANGED rather than a newly established regression. `--fail-on-all-verified-failures` is available when every current proven failure must block.

## Remaining P0 release gates

- Interview five target users; record whether three report a repeated relevant problem and two offer synthetic/redacted test cases. No interviews have been conducted here.
- Add and label an independent held-out set before evaluating it. Publish measured false PASS/FAIL, unknown rate, valid-reference rate, and coverage for that set.
- Validate import/adapter assumptions against real, redacted n8n exports and an independently controlled n8n environment. Synthetic JSON and source review do not establish full runtime compatibility.
- Run the GitHub workflows in an actual repository and confirm artifacts are retained after a deliberately failed check. Both configured Python versions have passed locally.
- Have two pilot reviewers follow the README and explain the evidence without developer guidance.
- Compare against generic ChatGPT analysis only after a common gold set and reproducible methodology exist; no comparative performance claim has been measured.

The local P0 core is usable for controlled evaluation. These remaining checks prevent describing the entire P0 product/release gate as complete. P1 local implementation evidence is recorded below; the external release gates remain pending.


## P1 local implementation evidence — 2026-10-16

The combined suite has 134 passing tests on Python 3.12.14 and 3.14.7. P1 tests exercise generated text PDFs and DOCX files (including table paragraphs), exact quotes and source locations, stale/forged citations, deterministic drafts, explicit review decisions, approved mappings, traceability, restrictive output creation, document limits and archive attacks, and a simulated loopback Ollama service. Drafts cannot be used as approved policies. Decimal thresholds and line-wrapped conditions retain their source text.

The official MCP SDK client initializes the local stdio server, lists seven read-only tools, verifies a workflow, exports canonical JSON, and observes a rejected path escape. Direct tool results equal core-library results. The official MCP Inspector CLI also successfully listed tools and called `verify_workflow_rules` on the synthetic failing workflow: canonical exit 1, `isError: false`. Tool failure is distinct from a successful verification that finds a violation.

The runnable DOCX → draft → synthetic human-review file → approved YAML → regression audit demo produced a validated paragraph-2 citation for `REQ-004 / FAIL / INTRODUCED`, with no unresolved review items for that rule. See [the guide](sop-and-mcp.md); session output is in `reports/p1-demo/`. The example's second requirement stays review-only because live manager identity needs external evidence.

The project-local [auditor skill](../skills/veriq-auditor/SKILL.md) passes the skill frontmatter validator. It has not been globally installed or publicly published. CI installs the SOP/MCP extras so these tests run on both configured Python versions.

MCP/AnyIO stdio tests stall inside this session's restricted sandbox; even a minimal worker-thread check stalls there. The complete suite passes outside that sandbox. This is an environment constraint; it does not skip the protocol test.

Still pending: real installed-model quality and hardware evaluation, diverse independent SOP extraction fixtures (especially complex PDF layouts and partially scanned content), two human pilot reviews, a recorded product walkthrough, GitHub-hosted CI execution, and public/remote plugin distribution. Exact citations establish source presence, not correct interpretation, complete document coverage, live authorization, or regulatory compliance.

## Audit regression fixes — 2026-10-16

All 150 tests pass on Python 3.12.14 and 3.14.7 outside the restricted sandbox, including the real MCP stdio round trip. Added checks cover disconnected unsupported gates, citation-independent regression classification, final review flags, report depth round trips, repeated requirement offsets, explicit rejection of DOCX fields, and bounded CLI/MCP serialization. The oversized-report regression uses a valid 702 KB workflow and 100 rules under a 256 MiB process address-space cap; it returns the output-limit error and preserves existing reports instead of raising `MemoryError`. Real model inference, live n8n compatibility and remote CI remain untested.


## Phase 2 hosted distribution evidence — 2026-10-16

The combined suite has **173 passing tests on Python 3.12.14 and 3.14.7**. New cases exercise signed JWT validation (bad signatures, issuer/audience mismatch, expiration and future issuance), required scopes, exact issuer discovery, private raw-file uploads, chunked byte limits, invalid data, quotas, file expiry/permissions, cross-user input/audit isolation, deletion, shared core findings, and reproducible allowlisted plugin ZIPs. The existing local CLI, SOP and stdio tests continue to pass.

`docker compose --env-file deployment/.env.example -f deployment/compose.yaml config -q` passes. The official Caddy executable accepts the committed proxy configuration and enables HTTPS plus HTTP redirection. A loopback smoke test using a temporary locally trusted TLS certificate passed through Caddy to the actual Veriq application, checking health, exact OAuth resource metadata and a 401 authentication challenge. This exercises HTTPS proxy routing; it does not establish public DNS or ACME certificate issuance.

`dist/veriq-preview.zip` was built from the explicitly illustrative metadata in `deployment/plugin.example.json`. It contains only public manifests, the auditor skill and the existing icon; it does not represent a working public endpoint or verified publisher. The skill passes its frontmatter validator.

Container builds/runs could not be performed: the environment denies access to the Docker daemon socket, including outside the command sandbox. The CI definition now includes a Docker image build and installed-entrypoint smoke check, but it has not run on GitHub here. The HTTP test client emits a Starlette deprecation warning for the installed httpx integration; tests pass without changing runtime dependencies.

Selected providers: Appwrite Cloud hosting and Auth0 authentication. Read-only account discovery found the existing `veriq` project in Singapore; no Cloud resources were changed. The subsequent Cloud adaptation is described below. Public hostname, Auth0 tenant/client and publisher metadata remain to be configured. Remaining release checks include real Appwrite deployment, Docker image execution for that alternative, public HTTPS/DNS, real Auth0 login/tokens/PKCE, ChatGPT connection, publisher/domain verification, legal/support URLs, reviewer cases/video/demo account and OpenAI review.

## Appwrite Cloud architecture evidence — 2026-10-17

The final suite passes **202 tests on both Python 3.12.14 and 3.14.7**. Docker Compose configuration validation also passes. The existing Starlette/httpx test-client deprecation warning remains; no runtime dependency was added to silence it.

`appwrite_function.py` bridges Appwrite's Python request/response lifecycle to the real HTTP MCP application. `appwrite_store.py` persists private inputs/reports in Storage, with TablesDB ownership, pending/ready state, expiry and transactional owner/global quota counters. A separate scheduled entry point removes expired data and refuses non-scheduled invocations. The verifier and Auth0 claim/scope checks are shared with Docker; local stdio behavior remains covered.

Thirteen Appwrite-specific tests exercise cold starts through the actual Functions bridge and signed JWT middleware, cross-user input/report rejection, artifact deletion, quota bounds and conflict rollback, failed uploads, expiry/cleanup, preservation of in-flight reservations during audit eviction, chunked binary writes, sanitized upstream errors, private resource definitions, provisioning without overwrites, and source archive safety. They use a service simulator and HTTP mock transport, not a live Appwrite project.

`dist/veriq-appwrite.tar.gz` was built using the source allowlist and successfully built an installable wheel from a temporary extraction. Its entry points and installation metadata are present; environment files, input fixtures, reports and credentials are excluded. Provisioning definitions and instructions are in [the Appwrite guide](appwrite-deployment.md).

No live resources, deployments or account settings were changed. Appwrite/Auth0 credentials, public origin, real provider payload/time/memory limits, actual concurrent service transactions, cleanup scheduling and ChatGPT connection remain deployment checks. Tests do not establish public production readiness. Temporary files after abrupt runtime termination, cleanup backlogs, provider backups/log retention and zero-usage pseudonymous quota rows are explicit retention limits.
