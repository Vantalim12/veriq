"""Build an allowlisted plugin ZIP without bundling source inputs or credentials."""

from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from pydantic import Field, model_validator

from .contracts import Contract
from .ingestion import InputError, load_json, read_bytes


class PluginConfig(Contract):
    origin: str
    issuer: str
    oauth_client_id: str = Field(min_length=1, max_length=256)
    publisher: str = Field(min_length=1, max_length=80)
    website_url: str
    support_url: str
    privacy_policy_url: str
    terms_url: str

    @model_validator(mode="after")
    def urls(self):
        from .hosted_auth import HostedSettings, https_url
        for field in ("origin", "issuer", "website_url", "support_url", "privacy_policy_url", "terms_url"):
            https_url(getattr(self, field))
        HostedSettings(self.origin, self.issuer, self.issuer.rstrip("/") + "/jwks", Path("."))
        if not self.publisher.strip() or not self.oauth_client_id.strip():
            raise ValueError("publisher and OAuth client ID must not be blank")
        return self


def manifests(config):
    resource = config.origin + "/mcp"
    manifest = {"$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json", "name": "veriq",
        "version": "0.1.0", "description": "Evidence-backed static checks for exported n8n workflows and reviewed business rules.",
        "author": {"name": config.publisher}, "homepage": config.website_url,
        "extensions": {"com.openai": {"interface": {
            "displayName": "Veriq", "shortDescription": "Check automation rules",
            "longDescription": "Check exported n8n workflows against human-reviewed business rules, compare revisions, and trace findings to SOP citations. Results cover a bounded static model; they do not certify compliance or prove live authorization.",
            "developerName": config.publisher, "category": "Developer Tools",
            "websiteURL": config.website_url, "supportURL": config.support_url,
            "privacyPolicyURL": config.privacy_policy_url, "termsOfServiceURL": config.terms_url,
            "composerIcon": "./assets/icon.png", "logo": "./assets/icon.png",
            "defaultPrompt": ["Check my workflow against its reviewed rules.", "Compare my workflow revisions and explain introduced failures."]}}}}
    auth = {"type": "oauth", "client": {"mode": "provided", "clientId": config.oauth_client_id,
            "tokenEndpointAuthMethod": "none"}, "authorizationServerBase": config.issuer,
            "resource": resource, "baseScopes": ["veriq:read"]}
    mcp = {"$schema": "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json", "mcpServers": {
        "veriq": {"type": "streamable-http", "url": resource, "extensions": {"com.openai": {"auth": auth}}}}}
    return manifest, mcp


def build_plugin(config_path: Path, destination: Path, root: Path):
    config = PluginConfig.model_validate(load_json(read_bytes(config_path)))
    manifest, mcp = manifests(config)
    skill = root / "skills/veriq-auditor/SKILL.md"
    icon = root / "public/favicon.png"
    inputs = [config_path, skill, icon]
    if destination.resolve() in {p.resolve() for p in inputs} or destination.exists():
        raise InputError("plugin output must be a new path separate from input files")
    members = {"plugin.json": json.dumps(manifest, sort_keys=True, indent=2).encode(),
               "mcp.json": json.dumps(mcp, sort_keys=True, indent=2).encode(),
               "skills/veriq-auditor/SKILL.md": read_bytes(skill), "assets/icon.png": read_bytes(icon, 5 * 1024 * 1024)}
    stream = BytesIO()
    with ZipFile(stream, "w", compression=ZIP_DEFLATED) as archive:
        for name, payload in members.items():
            info = ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, payload)
    # Binary output uses exclusive creation just like authoring artifacts.
    destination.parent.mkdir(parents=True, exist_ok=True)
    import os
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(stream.getvalue())
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
