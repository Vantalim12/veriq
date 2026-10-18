# Production configuration and acceptance

The public Veriq origin remains `https://veriq.sgp.appwrite.run`. The current live login is Clerk development. Production configuration and acceptance tooling are implemented; a production instance on an owned domain and two live user OAuth tokens are still required to validate the cutover.

## Clerk production

Follow [Clerk cutover](clerk-configuration.md#production-cutover). Configure the API with [production.env.example](../deployment/appwrite/production.env.example), retaining the actual existing database/bucket IDs and secret key. `VERIQ_ENVIRONMENT=production` refuses `*.clerk.accounts.dev` issuer/JWKS URLs, an invalid environment name, and a missing/placeholder public upload client. The generic JWT verifier still validates signature, exact issuer/audience, expiry and scope. A production label alone cannot prove that provider settings or DNS are correct.

Development remains an explicit supported pilot mode. Do not enable production mode on the live development issuer. The cleanup function does not use OAuth configuration. No live Clerk/Appwrite settings are changed by the acceptance script.

## Automated acceptance

Install the app with its hosted/test dependencies. From the repository root:

```bash
.venv/bin/python -m pytest -q
```

The Appwrite acceptance test invokes the real Functions bridge, authenticated MCP tools, parser subprocesses, verifier and durable-store adapter against simulated Appwrite/Clerk services. It uploads baseline/changed JSON, synthetic reviewed YAML, PDF and DOCX; checks baseline PASS and regression FAIL against the local verifier; exports JSON/Markdown and finding evidence; denies another identity's access/deletion; then deletes inputs. Other tests cover expiry, scheduled physical cleanup, transaction conflicts, quota rollback and owner-specific audit rotation. These simulated checks are not evidence of production Clerk issuance or actual provider limits.

## Live acceptance

Set the public origin, exact issuer/JWKS URL, public upload client ID and `VERIQ_ENVIRONMENT` in your shell. Obtain short-lived OAuth **access** tokens for two different users with both `veriq:read veriq:upload`, for the exact resource `https://veriq.sgp.appwrite.run/mcp`. Set `VERIQ_SMOKE_ALICE_TOKEN` and `VERIQ_SMOKE_BOB_TOKEN` locally; never paste tokens into issues, commits or screenshots. Interactive hidden entry avoids placing the token in shell history:

```bash
read -rs -p 'First user access token: ' VERIQ_SMOKE_ALICE_TOKEN
export VERIQ_SMOKE_ALICE_TOKEN
read -rs -p 'Second user access token: ' VERIQ_SMOKE_BOB_TOKEN
export VERIQ_SMOKE_BOB_TOKEN
.venv/bin/python deployment/acceptance.py
unset VERIQ_SMOKE_ALICE_TOKEN VERIQ_SMOKE_BOB_TOKEN
```

For an intentional check of the current development deployment, use `VERIQ_ENVIRONMENT=development` and add `--allow-development`. The runner checks resource discovery, health, anonymous denial, all four file formats, SOP extraction/drafting, baseline/regression results, persisted report/finding retrieval and cross-account denial. It uses the repository's **synthetic demonstration policy**, which does not constitute approval of real business requirements. It deletes its inputs on success/failure; its two private audit records expire after one hour. A failure exits nonzero without printing credentials or document contents. If cleanup is interrupted, inputs remain private and expire after 24 hours.

Complete these live checks separately and record their date/deployment ID:

- Sign into `/upload` and ChatGPT with the same production account, upload real approved inputs, call the tools through ChatGPT and inspect the resulting source citations. Reconnect/reupload after changing issuers.
- Confirm real input/report expiry and physical deletion after the scheduled cleanup; inspect quota counters. Simulated clock tests cannot establish that the actual schedule/provider is operating.
- Exercise concurrent uploads near the caps, supported large files, cold starts and key rotation on the selected Appwrite runtime. No measured load-capacity claim is made.

## Audit retention and parser boundary

Appwrite and the Docker memory cache retain eight audits **per owner**, plus global caps of 1,000 audits/512 MiB. Appwrite reservations count toward caps. Owner rotation never selects another owner's report. Global pressure rejects a new report rather than deleting another user's unexpired evidence. A rejected audit is a tool error and must not be presented as a saved result. Expired Appwrite rows release capacity through scheduled cleanup; the memory cache expires entries on subsequent audit activity.

Hosted PDF/DOCX parsing uses a fresh Linux process for upload validation and every MCP extraction/drafting/audit read. It receives a private input copy and a scrubbed environment, not server credentials. Limits: 15 seconds wall time, 8 CPU seconds, 512 MiB address space, 2 MiB output, 32 descriptors, no child processes, core dumps or privilege escalation. Python socket/process operations are denied; timeouts/crashes fail closed. Temporary copies/output are removed after completion. Unsupported hosts fail closed for hosted SOP parsing; CLI/local stdio retain their existing parser behavior.

This process has the same OS user/kernel/filesystem visibility as its host. Python audit hooks do not contain arbitrary native-code execution. Appwrite's function isolation or Docker hardening remains necessary; a dedicated parser service/container with no network and restricted filesystem is the next boundary if the threat model requires containment of native parser exploits.

The upload page advertises the version-pinned [n8n subset](supported-n8n-semantics.md), generated from the adapter manifest, and workflow uploads report unsupported nodes. Preflight compatibility is not a passing audit; unsupported relevant behavior remains review-needed.
