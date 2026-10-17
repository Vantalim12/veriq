# Appwrite Cloud deployment with Auth0

Veriq's Appwrite Functions adapter reuses the same MCP routes, Auth0 JWT checks and verifier as the Docker service. Appwrite hosts the HTTPS endpoint; Caddy and a persistent Docker volume are unnecessary for this deployment. Code is prepared for deployment; no Cloud resources, credentials or public endpoints were created by this implementation.

| Component | Appwrite implementation |
| --- | --- |
| HTTP MCP and artifact API | `veriq-api`, Python 3.12, `deployment/appwrite/main.py` |
| Authentication | Auth0 user access tokens, validated inside Veriq |
| Private inputs and audit reports | Storage bucket `veriq-private`, inaccessible to client SDKs |
| Ownership, expiry and quota reservations | Private TablesDB database `veriq`, tables `objects` and `quotas` |
| Expiry cleanup | Separate `veriq-cleanup` function, every five minutes, no client execute permissions |
| Parsing workspace | Private temporary directory per invocation, removed on normal completion/error |

Use the existing `veriq` project in Singapore. Its project ID is visible in the Appwrite Console; the regional API endpoint is `https://sgp.cloud.appwrite.io/v1`. The public MCP URL is the **function's HTTPS domain plus `/mcp`**, not the Appwrite project API endpoint.

## Prepare private resources

From the repository root, install `python -m pip install -c constraints.txt -e '.[test,appwrite]'`.

The reviewable resource definitions are in [resources.json](../deployment/appwrite/resources.json). They disable client access to the bucket, database and tables, use no public row/file permissions, enable bucket encryption, and define both functions. Tables are created with their columns and indexes together. The runtime uses the published REST API through the already-installed `httpx` dependency; it does not require an Appwrite SDK.

To create missing resources, supply configuration through your shell environment:

```bash
export APPWRITE_FUNCTION_API_ENDPOINT=https://sgp.cloud.appwrite.io/v1
export APPWRITE_FUNCTION_PROJECT_ID=YOUR_VERIQ_PROJECT_ID
# Set VERIQ_APPWRITE_API_KEY privately to a temporary provisioning key.
python deployment/appwrite/provision.py
```

The provisioning key needs bucket/database/table/column/index/function creation and read scopes. The script creates missing resources, preserves existing data, and refuses existing definitions with different permissions or relevant settings. It does not overwrite an existing schema, delete resources, upload code or create Auth0 applications. If existing definitions differ, review them in the Console. Wait until columns and indexes report `available` before deploying traffic. Retire the provisioning key after setup.

Create a separate **runtime** server API key with `files.read`, `files.write`, `rows.read` and `rows.write`. These cover Storage access and TablesDB row/transaction operations. Grant no user-management, schema-management or function-management scopes to the runtime key. Keep this key in a secret function variable named `VERIQ_APPWRITE_API_KEY`; never put it in the plugin ZIP, browser code or an incoming request header. Appwrite function scopes remain empty because this version deliberately uses the configured server key rather than request-supplied credentials.

Because a server key bypasses client permissions, isolate Veriq in its own Appwrite project. Ownership is enforced by the backend using the verified Auth0 issuer/subject hash. Auth0 tokens are not Appwrite sessions. [Server API keys](https://appwrite.io/docs/advanced/platform/api-keys), [TablesDB transactions](https://appwrite.io/docs/products/databases/tablesdb/transactions).

## Build and deploy the functions

```bash
python deployment/appwrite/package.py --output dist/veriq-appwrite.tar.gz
```

The archive includes only Python application sources, the two entry points and installation metadata. It excludes environment files, workflows, policies, reports, uploaded documents, tests, private resource definitions and credentials. Existing output archives are preserved; choose a fresh output name for later builds.

Upload this same archive to both functions using **Create deployment → Manual** in the Appwrite Console. Settings are also recorded in `resources.json`:

| Setting | API function | Cleanup function |
| --- | --- | --- |
| Runtime | Python 3.12 | Python 3.12 |
| Entrypoint | `deployment/appwrite/main.py` | `deployment/appwrite/cleanup.py` |
| Build command | `pip install -r requirements.txt` | `pip install -r requirements.txt` |
| Timeout | 120 seconds | 120 seconds |
| Execute permissions | Any | None |
| Schedule | None | `*/5 * * * *` |
| Execution logging | Disabled | Disabled |

The API permits unauthenticated invocation so OAuth resource discovery and health checks work. Its MCP tools and upload/delete routes still require Auth0 tokens and scopes. The cleanup entry point is deployed separately with no client execute permissions and additionally requires Appwrite's platform-supplied `x-appwrite-trigger=schedule` metadata; ordinary HTTP/API invocations return 404 even if a domain is assigned. It is never a branch on the public API. Configure at least 1 GiB of runtime memory where available and validate the supported document budgets with your selected runtime specification. [Appwrite manual deployment](https://appwrite.io/docs/products/functions/deploy-manually).

Set these variables on **both** functions:

- `VERIQ_APPWRITE_API_KEY`: the private runtime key, marked secret.
- `VERIQ_APPWRITE_DATABASE=veriq` and `VERIQ_APPWRITE_BUCKET=veriq-private`.

Appwrite supplies `APPWRITE_FUNCTION_API_ENDPOINT` and `APPWRITE_FUNCTION_PROJECT_ID`. For local invocation tests, set these explicitly. The public API function additionally needs:

- `VERIQ_PUBLIC_ORIGIN=https://<api-function-domain>` without a path or trailing slash.
- `VERIQ_OAUTH_ISSUER`: the exact Auth0 discovery issuer.
- `VERIQ_JWKS_URL`: the trusted Auth0 discovery signing-key URL.

Use [the example variables](../deployment/appwrite/.env.example) as a reference. Redeploy after changing variables or build settings. Add a custom domain before registering the final Auth0 API identifier if you plan to use one. Appwrite supplies HTTPS for the function domain. [Functions domains](https://appwrite.io/docs/products/functions/domains).

Follow [Auth0 configuration](hosted-deployment.md#configure-auth0-before-opening-access), using `https://<api-function-domain>/mcp` as the API identifier/resource. Keep the plugin's origin, issuer and public client ID consistent. The existing plugin builder and explicit raw-body artifact upload API work with this URL.

## Persistence, limits and failure handling

Each call creates its own application and temporary workspace. The bridge passes method, path, query, Auth0 authorization and MCP headers to the existing ASGI app, runs its lifespan, and returns its status, headers and bytes through Appwrite's binary response API. It ignores Appwrite user/key headers for authorization. MCP uses stateless JSON responses; persistent SSE connections and session affinity are unnecessary. [Functions request/response lifecycle](https://appwrite.io/docs/products/functions/develop).

Artifact IDs and canonical audit IDs keep their existing external format. Storage IDs are internal; a caller cannot provide a Storage URL or server path. A fresh invocation downloads only objects belonging to its verified Auth0 owner. Reupload existing Docker/local inputs when switching deployments; this code does not transfer old data automatically.

Inputs retain their 24-hour TTL and 2 MiB workflow/policy or 10 MiB PDF/DOCX limits. Storage uploads over 5 MiB use Appwrite's chunked protocol. Per-owner quotas remain 100 inputs/64 MiB, with 1,000 inputs/512 MiB across the service. Audits are now durable across cold starts, retain the last eight completed results globally, expire after one hour, and have a separate 128 MiB total budget. Repeated verification can refresh retention by storing another result with the same canonical audit ID; report lookup selects the newest unexpired ready result for that owner.

Quota counters and object reservations commit atomically in TablesDB transactions. Bound checks apply to both owner and global counters; conflicts are retried up to three times. Storage and TablesDB do not share a transaction: records remain `pending` until the complete blob is uploaded, and pending records are never readable. Failed writes attempt cleanup; interrupted uploads retain a quota reservation for ten minutes before scheduled removal. Function timeouts must remain below this reservation lifetime. [Atomic operation bounds](https://appwrite.io/docs/products/databases/tablesdb/atomic-numeric-operations).

Expired records stop resolving immediately. Scheduled cleanup removes their blobs and releases counters; it works in bounded batches with a time budget, so physical deletion can lag during outages or a backlog. A failed delete can leave an unavailable record consuming quota until the next successful cleanup. Zero-usage quota rows retain pseudonymous owner IDs; input/report expiry does not delete those counters. Monitor cleanup failures and storage usage. Backups and provider retention are separate from application TTLs. Abrupt runtime termination may leave private temporary files until the worker is recycled; normal completion and handled errors remove the workspace.

Requests are buffered by Appwrite before Veriq sees them. Veriq enforces its byte caps again, but cannot undo the platform's initial buffering. Host/origin checks, scope checks and parser budgets remain active. Cloud HTTP payload/time/memory limits can further restrict large reports or expensive documents; exercise them on the actual deployment. This remains a bounded evaluation service, not an assurance that arbitrary hostile PDFs are safe to parse in-process.

## Verify the real deployment

1. Check `/healthz` and `/.well-known/oauth-protected-resource/mcp` through the function domain. Confirm the exact public resource and Auth0 issuer.
2. Confirm anonymous `/mcp` calls return 401 with `WWW-Authenticate`, and missing scopes return 403.
3. With an Auth0 user token, upload the procurement example workflows/policy and run `compare_workflow_versions`. Read the report in a later invocation; another user must be denied both inputs and audit results.
4. Confirm cleanup removes expired input/report files and releases counters. Test concurrent uploads near both quotas, interrupted uploads and key rotation.
5. Test ChatGPT connection, provider consent/PKCE, large supported files and reports, and deployment cold starts before public submission.

Automated tests simulate the Appwrite services and invoke the real Functions bridge, JWT middleware, MCP tools and verifier. They cover cold-start persistence, user isolation, quota rollback/conflicts, chunked binary uploads, expiry, deletion, error sanitization and archive safety. Live Appwrite deployment, Auth0 issuance, provider payload limits and ChatGPT connection still require the configured accounts and domain.
