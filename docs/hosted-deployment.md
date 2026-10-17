# Phase 2: Docker, HTTPS and plugin packaging

This phase implements hosted distribution using the existing verifier. It does not add live n8n access, workflow execution, auto-repair, billing or a dashboard. The owner selected **Appwrite Cloud for hosting and Auth0 for authentication**. No public service or directory listing has been created.

## Selected target: Appwrite Cloud + Auth0

The connected Appwrite account already has a `veriq` project in the Singapore region. Auth0 will issue user access tokens; Veriq will validate them using its existing JWT verifier.

The Appwrite Functions adapter, private Storage backend, TablesDB ownership/quota records and scheduled cleanup are implemented. Follow the [Appwrite deployment guide](appwrite-deployment.md) to provision resources, package the source and deploy both functions. Auth0 tokens are validated by Veriq; all Appwrite access uses a private server key and backend ownership checks.

The Docker Compose instructions below remain an alternative Docker-host deployment procedure. Appwrite Cloud uses its own HTTPS function endpoint and durable services instead of Caddy, a persistent `/data` mount and a process-local audit cache.

Still needed: public MCP hostname, Auth0 tenant domain and public client ID, and publisher/support/legal URLs. Keep the final API identifier tied to that hostname before issuing tokens or building a release package.

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

## Configure Auth0 before opening access

1. Register a custom API with identifier `https://<public-mcp-host>/mcp` exactly and RS256 signing. Add permissions `veriq:read` and `veriq:upload`. Veriq reads the token's space-separated `scope` claim, not Auth0's optional `permissions` array. [API settings](https://auth0.com/docs/get-started/apis/api-settings).
2. Register a public OAuth application with authorization-code flow, PKCE S256, token endpoint authentication method `none`, and the exact ChatGPT callback supplied during setup. Authorize that client for this API and its intended scopes; grant upload access only where required. Strict third-party applications require an explicit API client grant and user consent. [Auth0 security controls](https://auth0.com/docs/get-started/applications/third-party-applications/security-controls).
3. Check the tenant's Resource Parameter Compatibility Profile: Auth0 documents `resource` as an alternative to `audience` when this is set to `compatibility`. Test that a request for `resource=https://<public-mcp-host>/mcp` yields that exact token audience. Do not work around a mismatch by disabling audience validation. [PKCE authorization parameters](https://auth0.com/docs/api/authentication/authorization-code-flow-with-pkce/authorize-with-pkce).
4. Copy the exact `issuer` and `jwks_uri` from `https://<auth0-domain>/.well-known/openid-configuration` into the service settings. A typical issuer is `https://<tenant>.<region>.auth0.com/` and JWKS URL is `https://<tenant>.<region>.auth0.com/.well-known/jwks.json`. Preserve the issuer's trailing slash and use discovery values when a custom domain is enabled.
5. Put only the public client ID and matching issuer in the plugin configuration. Obtain a real user access token and verify allowed/denied scopes, wrong-audience rejection, user isolation and expiry before opening access. Do not use an ID token or an Appwrite API key as the MCP bearer token.

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

In the Docker deployment, audit results remain in memory, globally limited to the last eight completed audits; access is user-scoped and reads expire after one hour. Restarting or eviction requires rerunning verification. Appwrite stores those reports durably with the same one-hour access TTL; see its guide for cleanup and quotas. Input-file expiry/deletion does not erase an already-stored audit immediately. Responses use `Cache-Control: no-store`. Body/token values are excluded from access logs; file contents may appear in source citations and audit results intentionally.

The persistent volume is not a database or a backup policy. Operator backups, underlying disk snapshots and provider logs have their own retention. The service is for controlled single-instance evaluation; isolate untrusted document parsing more strongly before a broad public rollout.

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

Automated tests cover JWT signatures/claims, OAuth discovery, scopes, host/origin checks, bounded/invalid uploads, expiry, quotas, private file permissions, cross-user artifact/audit access, Appwrite cold-start persistence and quota rollback, shared core results, local stdio compatibility and package safety. CI includes an image build and installed-entrypoint check. Live Appwrite provisioning/deployment, DNS, certificates, Auth0 login, ChatGPT connection, public review and production load remain deployment work.
