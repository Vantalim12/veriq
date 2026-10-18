# Phase 2: Docker, HTTPS and plugin packaging

This phase implements hosted distribution using the existing verifier. It does not add live n8n access, workflow execution, auto-repair, billing or an audit dashboard. The owner selected **Appwrite Cloud for hosting and Clerk for authentication**. The API is deployed for development testing; no public directory listing has been created. The browser upload page is live for pilot use; updated code still needs redeployment after changes.

## Selected target: Appwrite Cloud + Clerk

The connected Appwrite account already has a `veriq` project in the Singapore region. Clerk issues user OAuth access tokens; Veriq will validate them using its existing JWT verifier.

The Appwrite Functions adapter, private Storage backend, TablesDB ownership/quota records and scheduled cleanup are implemented. Follow the [Appwrite deployment guide](appwrite-deployment.md) to provision resources, package the source and deploy both functions. Clerk tokens are validated by Veriq; all Appwrite access uses a private server key and backend ownership checks.

The Docker Compose instructions below remain an alternative Docker-host deployment procedure. Appwrite Cloud uses its own HTTPS function endpoint and durable services instead of Caddy, a persistent `/data` mount and a process-local audit cache.

The development issuer, MCP hostname and public client ID are configured; see [Clerk configuration](clerk-configuration.md). Private Appwrite resources, runtime credentials, activation, browser sign-in/uploads and ChatGPT account linking have been exercised. Production Clerk, a complete two-account live audit and publisher/support/legal URLs remain pending. Keep the resource tied to the MCP hostname before issuing tokens or building a release package.

## Start with Docker + HTTPS

From the repository root:

```bash
cp deployment/.env.example deployment/.env
# Set the real domain, OAuth issuer and trusted JWKS URL in deployment/.env.
docker compose --env-file deployment/.env -f deployment/compose.yaml config -q
docker compose --env-file deployment/.env -f deployment/compose.yaml up --build -d
```

Point the domain's DNS at this host and make TCP ports 80/443 reachable. Caddy obtains/renews certificates and redirects HTTP to HTTPS. The verifier has no published host port; Caddy reaches it on the Compose network. [Caddy HTTPS requirements](https://caddyserver.com/docs/automatic-https).

`VERIQ_DOMAIN` is a hostname without a scheme or path. Compose derives `VERIQ_PUBLIC_ORIGIN=https://<domain>`. The issuer must exactly match the provider's token `iss`, including a trailing slash when present. `VERIQ_JWKS_URL` is the provider's trusted HTTPS signing-key endpoint. The application refuses to start without this configuration. It never implements an anonymous fallback, creates OAuth users or downloads model weights.

The app image runs as UID/GID 10001, with a read-only root filesystem, a private named data volume, a 64 MiB temporary filesystem, dropped Linux capabilities, and CPU/memory/process limits. Caddy owns a separate persistent certificate volume. Keep the verifier at one process/replica: storage quotas and audit caches are local to that instance. Use a host with an encrypted data disk for confidential inputs. Do not publish port 8000 directly.

For non-container inspection, install `python -m pip install -c constraints.txt -e '.[test,hosted]'`. `veriq serve` uses the same environment settings, plus optional `VERIQ_DATA_DIR` (default `/data`), and listens on port 8000 behind the HTTPS proxy.

## Configure Clerk before opening access

1. In **Configure → Agents → MCP server**, register the exact resource `https://<public-mcp-host>/mcp`. Automatic CIMD onboarding stays off for this manually registered client. See [Clerk MCP setup](https://clerk.com/docs/guides/ai/mcp/build-mcp-server).
2. In **Configure → Developers → OAuth applications → Scopes**, create and advertise `veriq:read` and `veriq:upload`. Veriq reads the access token's space-separated `scope` claim. Reading audits requires `veriq:read`; uploading/deleting inputs requires `veriq:upload`.
3. Create a **Public** OAuth application with those allowed scopes and keep the consent screen enabled. Enable `openid`, `email`, and `profile` when Clerk advertises them in discovery: ChatGPT requests advertised OIDC scopes by default, even when the plugin base scope is only `veriq:read`. Keep private/public metadata scopes disabled. See [OpenAI OIDC scope requirements](https://developers.openai.com/plugins/build/auth#oidc-scopes). Clerk lists `offline_access` as a built-in allowed scope; the plugin requests only `veriq:read` by default. Allowed scopes do not themselves grant access. Register the exact ChatGPT callback supplied during connection setup. See [Clerk OAuth behavior](https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth).
4. Under OAuth **Settings**, require PKCE S256, select **JWT access tokens**, and enable **Include Audience**. Send `resource=https://<public-mcp-host>/mcp` in the authorization request and verify that exact value in the token's `aud`. Keep CIMD/DCR publication disabled for the manually registered client. Veriq validates JWTs locally; already-issued tokens remain valid until expiry. See [token formats](https://clerk.com/docs/guides/development/machine-auth/token-formats).
5. Copy the exact `issuer` and `jwks_uri` from the instance's `/.well-known/openid-configuration` into the service settings. The configured development issuer has **no trailing slash**. Preserve discovery values exactly when switching to production.
6. Put only the public client ID and matching issuer in the plugin configuration. Obtain a real user OAuth access token and verify allowed/denied scopes, wrong-audience rejection, user isolation and expiry before opening access. Do not substitute a Clerk session/ID token or an Appwrite API key for the MCP access token. Never disable audience validation to make a token pass.

Use an authorization server supporting discovery and authorization-code login with PKCE S256. Register a public client for the plugin (`token_endpoint_auth_method=none`) and allow the exact ChatGPT callback shown during connection setup. Keep this public client ID for the plugin package. Other OAuth registration methods need a separate configuration change; the generated package uses a pre-registered public client.

Configure access tokens with:

- Audience/resource: `https://<domain>/mcp` exactly; echo the OAuth `resource` request into the access token audience.
- Issuer: exactly `VERIQ_OAUTH_ISSUER`.
- RSA RS256 or EC ES256 signatures published at `VERIQ_JWKS_URL`.
- Required claims: `iss`, `aud`, `sub`, `iat`, `exp`; normal `nbf` checks also apply.
- Space-separated `scope`: `veriq:read` for MCP; `veriq:upload` for uploading/deleting inputs. Grant scopes only to authorized users. Restrict initial access to pilot users through the provider.

The resource metadata is available at `/.well-known/oauth-protected-resource/mcp`; a missing/invalid token returns a 401 with its discovery URL. Each MCP tool declares its OAuth scope. The service verifies signature, issuer, audience, validity and scopes on requests. It scopes artifacts and audit access by the verified issuer and subject, independent of user-supplied filenames or IDs. It does not fetch user-supplied URLs. [OpenAI authentication requirements](https://developers.openai.com/plugins/build/auth).

JWT validation uses a cached trusted JWKS. Use short-lived access tokens: this service does not introspect revocations or implement provider logout/refresh. A valid already-issued token may remain usable until expiry; provider signing-key cache refresh is also bounded by its cache lifetime. Login/consent, provider configuration, real token issuance and ChatGPT OAuth connection must be tested with the chosen provider before public use.

## Upload inputs securely

### Browser upload page

Open `https://<domain>/upload` after deploying this version. It accepts one file per upload: n8n workflow JSON (2 MiB), SOP PDF/DOCX (10 MiB), and reviewed Veriq rules YAML (2 MiB). Upload a baseline as a second workflow when comparing versions. The rules form requires confirmation that a human reviewed the rules; file validation still runs on the server. This confirmation does not create or independently certify an approval.

1. In the existing Clerk **Public** OAuth application, add the exact callback `https://<domain>/upload/callback`. Keep the existing ChatGPT callback. The application must allow `veriq:upload`, require PKCE S256 and issue JWT access tokens with Include Audience enabled. See [Clerk public clients and PKCE](https://clerk.com/docs/guides/configure/auth-strategies/oauth/how-clerk-implements-oauth#public-clients-and-pkce).
2. Set `VERIQ_UPLOAD_CLIENT_ID` to its public client ID in the API function's variables (or Docker environment), then redeploy. No client secret or Clerk publishable key is required. An empty value disables browser login while leaving the bearer-token API available.
3. Sign in through the page with the **same Clerk user** connected to Veriq in ChatGPT. Allow upload access, upload your files, and copy each artifact ID. Files remain private and expire after 24 hours. The ID list is held only in the current page; copy IDs before refreshing or leaving.

The selected development deployment uses `VERIQ_UPLOAD_CLIENT_ID=RG1VUYAaWua4aGng` and requires the additional callback `https://veriq.sgp.appwrite.run/upload/callback` to be registered before browser login will work. Local source changes do not update an active Appwrite deployment: push the changes to the connected repository and deploy that commit, or deploy a new archive.

Login uses a ten-minute, browser-bound state/PKCE transaction and checks Clerk's exact authorization-response issuer. The server exchanges the authorization code and validates the access token with the same signature, issuer, audience, expiry and scope checks as MCP. The browser requests only `veriq:upload`; no OIDC identity or refresh scopes are requested. Access tokens live in a host-only Secure, HttpOnly, SameSite=Lax cookie and are never returned to JavaScript. Cookie credentials authorize only the browser upload routes, which also require an exact same-origin `Origin` header on uploads and sign-out. They do not authorize `/mcp` or the raw artifact API. Browser sessions expire within one hour or at token expiry, whichever comes first; sign in again when needed. Signing out clears the upload cookie, but does not revoke the token at Clerk, delete files, or end Clerk/ChatGPT sessions.

### Raw artifact API

The artifact API accepts raw file bodies using the same resource-bound OAuth access token. Obtain that token through your configured provider's authorized client flow. The read-only MCP tools cannot upload or approve rules. Review and approve policies locally before upload.

For example, with `VERIQ_URL=https://<domain>` and a short-lived `VERIQ_ACCESS_TOKEN` in your local environment:

```bash
curl --fail-with-body "$VERIQ_URL/artifacts/workflow" \
  -H "Authorization: Bearer $VERIQ_ACCESS_TOKEN" -H 'Content-Type: application/octet-stream' \
  --data-binary @examples/purchase-v2.json
curl --fail-with-body "$VERIQ_URL/artifacts/policy" \
  -H "Authorization: Bearer $VERIQ_ACCESS_TOKEN" -H 'Content-Type: application/octet-stream' \
  --data-binary @examples/veriq.rules.yaml
```

Each response returns `artifact_id`, `kind`, `bytes`, and `expires_at`. Give those IDs to `verify_workflow_rules` as `workflow` and `rules`. Upload a baseline as another workflow and use `compare_workflow_versions`; upload an SOP through `/artifacts/pdf` or `/artifacts/docx` and supply its ID as `sop`. `ingest_*` and `draft_sop_requirements` retain the existing `relative_path` parameter name, but hosted calls accept artifact IDs only. Absolute paths, relative server paths, guessed IDs belonging to another user, and download URLs are rejected. ChatGPT attachments are not automatically ingested; this first hosted version uses explicit authenticated uploads.

Input validation runs before an artifact is committed. Limits remain 2 MiB for workflow/policy and 10 MiB for PDF/DOCX, with the existing document/graph validation budgets. Body limits apply to streamed uploads as well as Content-Length. Upload reads have a 30-second deadline and two upload-validation slots. Parsing itself is bounded by input budgets and container limits, not a per-parser process timeout.

Storage is capped at 100 files/64 MiB per user and 1,000 files/512 MiB for the instance. Artifact files expire after 24 hours and are removed by a minute-period cleanup task; interrupted uploads are eligible for cleanup after ten minutes. Expired IDs stop resolving immediately. Request early deletion with:

```bash
curl --fail-with-body -X DELETE "$VERIQ_URL/artifacts/ARTIFACT_ID" \
  -H "Authorization: Bearer $VERIQ_ACCESS_TOKEN"
```

In the Docker deployment, audit results remain in memory, limited to the last eight completed audits per owner, with global caps of 1,000 audits/512 MiB; access is user-scoped and reads expire after one hour. Restarting or eviction requires rerunning verification. Appwrite stores those reports durably with the same one-hour access TTL; see its guide for cleanup and quotas. Input-file expiry/deletion does not erase an already-stored audit immediately. Responses use `Cache-Control: no-store`. Body/token values are excluded from access logs; file contents may appear in source citations and audit results intentionally.

The persistent volume is not a database or a backup policy. Operator backups, underlying disk snapshots and provider logs have their own retention. Hosted SOP parsing uses a resource-limited Linux subprocess without runtime credentials. This protects request workers from parser crashes and overruns; it is not a kernel or filesystem sandbox. See [production readiness and acceptance](production-readiness.md) for the remaining live checks.

## Build the plugin ZIP

```bash
cp deployment/plugin.example.json deployment/plugin.json
# Replace example URLs, publisher name and public OAuth client ID with real values.
veriq plugin --config deployment/plugin.json --output dist/veriq-plugin.zip
```

Run this command from the repository root, or pass `--repo-root /path/to/veriq`. Install the hosted extra first. Existing output files are preserved: use a new output path for each build.

The ZIP contains root `plugin.json`, root `mcp.json`, the auditor skill, and the existing icon. It declares the HTTPS Streamable HTTP endpoint, OAuth resource/scopes, and a pre-registered public client. It excludes source code, policies, workflow exports, uploaded documents, reports, environment files and credentials. Metadata rejects unknown fields such as client secrets. The ZIP uses reproducible member ordering/timestamps. [OpenAI packaging format](https://developers.openai.com/plugins/build/plugins).

`deployment/plugin.example.json` is a preview template: its hostnames are not functional services and its publisher is not verified. Supply real publisher-controlled HTTPS pages for website, support, privacy policy and terms; this implementation does not create or claim those legal pages. The client secret is neither needed for this public-client configuration nor accepted in the package. The package version is `0.1.0`; choose an explicit new version before publishing updates.

Test the connected service in ChatGPT, then complete publisher verification, domain verification, five positive/three negative review cases, a reviewer-accessible walkthrough, and demo-account access in the secure submission dashboard. No directory submission or public publication is performed by this code. [OpenAI submission requirements](https://developers.openai.com/plugins/deploy/submission).

## Operate and verify

```bash
curl --fail https://YOUR_DOMAIN/healthz
curl --fail https://YOUR_DOMAIN/.well-known/oauth-protected-resource/mcp
# Expect HTTP 401 with WWW-Authenticate, without an access token:
curl -i -X POST https://YOUR_DOMAIN/mcp -H 'Content-Type: application/json' --data '{}'
docker compose --env-file deployment/.env -f deployment/compose.yaml ps
docker compose --env-file deployment/.env -f deployment/compose.yaml logs --tail 100 verifier
```

Stop while retaining data and certificates with `docker compose --env-file deployment/.env -f deployment/compose.yaml down`. Avoid `down --volumes` unless you intend to delete stored inputs and certificates. Build and test a replacement image before upgrading; no database migration is required. Docker base images follow their major tags; record deployed digests and rebuild for security updates.

Automated tests cover JWT signatures/claims, OAuth discovery, scopes, host/origin checks, bounded/invalid uploads, expiry, quotas, private file permissions, cross-user artifact/audit access, Appwrite cold-start persistence and quota rollback, shared core results, local stdio compatibility and package safety. CI includes an image build and installed-entrypoint check. Live Appwrite provisioning/deployment, DNS, certificates, Clerk login, ChatGPT connection, public review and production load remain deployment work.
