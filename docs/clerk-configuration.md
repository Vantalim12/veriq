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

The browser upload page, its exact callback `https://veriq.sgp.appwrite.run/upload/callback`, and `VERIQ_UPLOAD_CLIENT_ID` are configured. Real uploads and ChatGPT SOP extraction have succeeded in the development environment. A complete two-account live acceptance run remains pending; automated checks cover the Appwrite bridge, browser code exchange, parsing, verification, persistence and isolation.

## Production cutover

Keep Veriq at `https://veriq.sgp.appwrite.run`. Clerk production needs a domain you own and can configure DNS for; Appwrite's shared hostname cannot supply that DNS ownership. See [Clerk production prerequisites](https://clerk.com/docs/guides/development/deployment/production).

1. Create the Clerk production instance on an owned domain and complete its DNS/certificate requirements.
2. Register the same Veriq MCP resource and both exact callbacks above. Recreate the public OAuth client, custom read/upload scopes, OIDC scopes and PKCE/JWT/audience settings in production.
3. Copy the exact production discovery `issuer`, `jwks_uri` and public client ID into the API function. Use [production.env.example](../deployment/appwrite/production.env.example), preserving the real Appwrite bucket/database IDs and secret runtime key. Set `VERIQ_ENVIRONMENT=production`; startup rejects Clerk development hosts or a missing client ID. Cleanup only needs storage variables.
4. Redeploy the API, update the ChatGPT OAuth client configuration and reconnect both browser and ChatGPT accounts. Production identities differ from development identities: reupload inputs rather than transferring ownership by email.
5. Run [production acceptance](production-readiness.md), then provide publisher/support/privacy/terms pages before public distribution.

Do not set production mode on the current development issuer: the resulting configuration failure is intentional. The production instance/domain is an operator prerequisite, not something generated by this repository.
