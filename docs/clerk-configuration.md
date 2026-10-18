# Clerk configuration

The selected provider is Clerk OAuth. These public values were configured on 2026-10-17 in Veriq's **development** instance:

| Setting | Value |
| --- | --- |
| Appwrite project | `6ad2328b00051a40cfb7` (Singapore) |
| API function | `6ad2d7070016276ccc51` |
| Public origin | `https://veriq.sgp.appwrite.run` |
| MCP resource / token audience | `https://veriq.sgp.appwrite.run/mcp` |
| OAuth issuer | `https://large-bluebird-4071.clerk.accounts.dev` |
| JWKS URL | `https://large-bluebird-4071.clerk.accounts.dev/.well-known/jwks.json` |
| OAuth application | `Veriq ChatGPT` (Public) |
| Public client ID | `RG1VUYAaWua4aGng` |
| Registered callback | `https://chatgpt.com/connector_platform_oauth_redirect` |
| Authorization URL | `https://large-bluebird-4071.clerk.accounts.dev/oauth/authorize` |
| Token URL | `https://large-bluebird-4071.clerk.accounts.dev/oauth/token` |

## Where to configure it

- [Clerk OAuth applications](https://dashboard.clerk.com/apps/app_3KnwQlebi0BFmezsshYIeQiFAcB/instances/ins_3KnwQiXWkn5JbRfq1XI8LJfdFSg/oauth-applications): client, exact callbacks, custom scopes, and OAuth settings.
- [Clerk MCP server](https://dashboard.clerk.com/apps/app_3KnwQlebi0BFmezsshYIeQiFAcB/instances/ins_3KnwQiXWkn5JbRfq1XI8LJfdFSg/agents/mcp-servers): registered resource URL. Automatic CIMD onboarding is off.
- Appwrite Console → project `veriq` → Functions → `veriq` → Settings → Variables: `VERIQ_PUBLIC_ORIGIN`, `VERIQ_OAUTH_ISSUER`, and `VERIQ_JWKS_URL` are saved. Redeploy after changing variables.
- [Appwrite environment example](../deployment/appwrite/.env.example) and [plugin configuration example](../deployment/plugin.example.json): public settings for deployment and packaging. Publisher/legal URLs remain placeholders.

The client permits `veriq:read` and `veriq:upload`, with consent enabled and device authorization disabled. The original setup omitted `openid`, `email`, and `profile`. A real ChatGPT connection on 2026-10-18 failed with `invalid_scope` because the client could not request `openid`. The user subsequently enabled these three scopes and connected the ChatGPT account successfully. Clerk advertises all three OIDC scopes, and ChatGPT requests advertised OIDC scopes by default. Do not enable private/public metadata scopes. See [OpenAI OIDC scopes](https://developers.openai.com/plugins/build/auth#oidc-scopes). Clerk also lists the built-in allowed scope `offline_access`; the plugin's default request is only `veriq:read`. Upload/delete access requires an explicit upload scope grant.

OAuth settings were verified as **Require PKCE**, **JWT access tokens**, and **Include Audience**, with CIMD/DCR publication off. The public client uses token endpoint authentication `none`; no client secret belongs in the plugin or Veriq's runtime. PKCE binds each authorization code to a one-time verifier. It does not impose a user-count limit, and a public client ID is not proof of the caller's identity. Veriq still validates token signature, issuer, audience, expiry, subject, and scopes.

The stable ChatGPT callback above applies when the authorization server supports issuer identification in authorization responses, which this instance advertises. During the actual ChatGPT connection, compare its displayed callback with the registered URI; register an additional exact URI if required. Do not use wildcard callbacks. See [OpenAI authentication](https://developers.openai.com/plugins/build/auth).

## Remaining deployment checks

The existing API and scheduled cleanup deployments are active, with private Appwrite storage, TablesDB and secret runtime keys configured. Public health/discovery checks and ChatGPT account linking/tool discovery succeeded. These checks do not establish a complete authenticated audit.

The new browser upload page still needs deployment, the additional exact callback `https://veriq.sgp.appwrite.run/upload/callback`, and the API variable `VERIQ_UPLOAD_CLIENT_ID=RG1VUYAaWua4aGng`. Keep the ChatGPT callback already registered. See [browser upload setup](hosted-deployment.md#browser-upload-page). The page requests only `veriq:upload` with PKCE; it uses the existing public client without a secret.

Real browser uploads and a complete ChatGPT audit still need a live smoke test. Automated tests cover the browser's code exchange with simulated Clerk responses, token boundaries, file parsing and user isolation. Clerk's MCP dashboard reports checks unavailable in this development environment.

Before a public launch, create/configure the Clerk production instance and repeat registration, callback and token checks with its discovery values. Supply real publisher/support/privacy/terms pages before building a release plugin.
