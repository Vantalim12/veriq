# Veriq

Detect broken business rules before your automations go live.

Veriq's core is a local, read-only Python CLI that checks exported n8n workflow configuration against reviewed YAML rules. It provides bounded path evidence, baseline comparison, and JSON/Markdown reports. This is an early preview with a deliberately narrow compatibility list, not full n8n execution verification or compliance certification.

## Install and run

Python 3.12 or newer is required. From this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -c constraints.txt -e '.[test]'
```

Inspect the synthetic workflow without executing it:

```bash
veriq inspect --workflow examples/purchase-v1.json
```

Check the passing baseline:

```bash
veriq verify \
  --workflow examples/purchase-v1.json \
  --rules examples/veriq.rules.yaml \
  --output-dir reports/baseline
```

Detect the deliberately introduced bypass; this command should return **exit 1**:

```bash
veriq verify \
  --workflow examples/purchase-v2.json \
  --baseline examples/purchase-v1.json \
  --rules examples/veriq.rules.yaml \
  --output-dir reports/regression
```

The result identifies `REQ-004` as `FAIL / INTRODUCED` and gives the path `intake → intake-route → threshold → fulfillment`, including the true-output connection. Read `reports/regression/audit.md`, or retrieve canonical evidence:

```bash
veriq explain --report reports/regression/audit.json --finding REQ-004
python -m pytest -q
```

Core verification makes no network requests and needs no model/API key after installation. The [synthetic SOP](examples/procurement-sop.md) explains the case; the example does not implement a live approval or fulfillment service.

## Rules and supported semantics

The three rule types are `must_pass_through`, `forbid_path`, and `require_condition`. Every enforced rule includes reviewer/date metadata; enforcement assumes the user supplied a genuinely reviewed policy through their Git/team process. Metadata is not authenticated signoff.

See [the rule format](docs/rule-format.md), [machine-readable policy schema](docs/policy.schema.json), and [supported n8n semantics](docs/supported-n8n-semantics.md). Initial adapters accept **typeVersion 1 only** for Webhook, No Operation, IF, and webhook-resumed Wait without timeout. IF supports one literal numeric comparison or string equality/inequality, with a constrained `$json.field` reference and explicitly declared field types. Arbitrary expressions, Code nodes, unknown versions, disabled nodes, loops, and non-default error routing stay review-needed/unsupported.

The model assumes declared fields are present and correctly typed. A Wait is a configured blocking waypoint; Veriq does not prove manager identity, authorization, connector internals, or live execution correctness. Field identity after a Wait is unresolved for downstream conditions.

## Exit policy

| Exit | Meaning |
|---|---|
| 0 | No blocking proven violation; warnings or historical failures may remain |
| 1 | Introduced deterministic failure in comparison mode, or any proven failure in standalone mode |
| 2 | Invalid input/policy, engine error, or inability to write the requested reports |
| 3 | Unresolved coverage under `--strict-unknown`, when no blocking failure/error takes precedence |

Use `--fail-on-all-verified-failures` to block existing failures too. A proven failure remains FAIL when other paths are unknown. Without a baseline, regression classification is null. `--warnings-only` preserves the canonical gate result/verdicts but returns process exit 0 for finding-based outcomes; input/tool errors still return 2. Use it when evaluating a new policy before enabling gates.

## CI

[Core CI](.github/workflows/ci.yml) tests Python 3.12 and 3.14. The [workflow-check example](.github/workflows/veriq-example.yml) analyzes a candidate JSON export against the base revision's approved policy and baseline, installing the verifier from that reviewed base. Candidate program code is not installed or executed for that check. The base branch must already contain the verifier before this workflow is usable.

The example checks changes to `examples/purchase-v1.json`; the deliberately broken `purchase-v2.json` is reserved for the local failure demo. Artifacts are retained even on a failed check. These examples contain synthetic data; choose access and retention deliberately before applying the workflow to confidential reports. Protect the repository's workflow/policy review process before relying on its gate.

GitHub Actions are pinned to full commit hashes verified against the official v7.0.0 releases of [checkout](https://github.com/actions/checkout/releases/tag/v7.0.0), [setup-python](https://github.com/actions/setup-python/releases/tag/v7.0.0), and [upload-artifact](https://github.com/actions/upload-artifact/releases/tag/v7.0.0). The verifier source is pinned to the reviewed base commit and Python dependencies are constrained by [constraints.txt](constraints.txt). Review upstream changes before updating these pins.

[Security scans](.github/workflows/security.yml) check Git history with Gitleaks and the complete pinned Python dependency inventory with pip-audit. Downloads, scanner errors, secrets and reported vulnerabilities fail their respective jobs. See [the publishing checks](docs/publishing-security.md) for scope, local commands and the pending first networked scan.

## SOP authoring and MCP

P1 adds located PDF/DOCX extraction, source-backed requirement drafts, explicit file-based human review, validated SOP-to-rule traceability, optional local Ollama assistance, and a read-only local MCP server. Install with `python -m pip install -c constraints.txt -e '.[test,sop,mcp]'`, then follow the [runnable SOP and MCP guide](docs/sop-and-mcp.md). Drafts cannot enforce rules, and MCP cannot approve them.

## Hosted deployment

Phase 2 adds an OAuth-protected HTTP MCP service, private expiring uploads and a plugin ZIP builder. The selected Appwrite Cloud deployment includes Functions entry points, private Storage, transactional TablesDB quotas and scheduled expiry cleanup, with Clerk OAuth authentication. Follow the [Appwrite deployment guide](docs/appwrite-deployment.md). The [Docker + HTTPS option](docs/hosted-deployment.md) remains available. Clerk development-instance configuration is recorded in [the configuration guide](docs/clerk-configuration.md).

The browser upload page at `/upload` supports workflow JSON, SOP PDF/DOCX and reviewed rules YAML. Configure `VERIQ_UPLOAD_CLIENT_ID` and register the exact `<public-origin>/upload/callback` in Clerk before deploying this version. Sign in with the same Clerk account used in ChatGPT, then copy the returned artifact IDs into your Veriq requests. See [browser upload setup](docs/hosted-deployment.md#browser-upload-page).

## Current phase

Implemented: bounded ingestion, strict policy validation, four pinned node adapters, three rule types, conservative path feasibility, validated evidence references, baseline diff, stable finding fingerprints, CLI, reports, synthetic fixtures, and CI definitions.

The [evaluation record](docs/evaluation.md) separates measured local checks from pending validation. Real user interviews, pilot reviews, an independent held-out benchmark, and an actual GitHub-hosted CI run are still required before claiming the P0 release gate is complete. P1 implementation and its remaining model/pilot validation are documented in the evaluation record; a website/dashboard is later.

Product context: [PRD](context/productRequirementDocument.md), [technical requirements](context/technicalRequirementDocument.md), [app flow](context/appFlow.md), [data model](context/databaseSchema.md), [design brief](context/designBrief.md), and [glossary](CONTEXT.md).
