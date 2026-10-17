# SOP authoring and local MCP

Install the optional readers and server alongside the core:

```bash
python -m pip install -c constraints.txt -e '.[test,sop,mcp]'
```

## Reproducible authoring example

The committed DOCX and review are synthetic examples, not authenticated human signoff. Use new output paths: authoring commands refuse to replace existing files or inputs.

```bash
veriq rules draft --sop examples/procurement-sop.docx --output reports/sop-draft.json
# A human now inspects the draft and writes/edits the review decisions.
veriq rules approve --sop examples/procurement-sop.docx \
  --draft reports/sop-draft.json --review examples/procurement-review.json \
  --output reports/sop.rules.yaml
veriq verify --workflow examples/purchase-v2.json --baseline examples/purchase-v1.json \
  --rules reports/sop.rules.yaml --sop examples/procurement-sop.docx --output-dir reports/sop-audit
```

The final command returns exit 1 with `REQ-004 / FAIL / INTRODUCED`, validated source text, paragraph location, and the approval-bypass route. Using `purchase-v1.json` alone returns exit 0, including under `--strict-unknown` when the source validates.

A draft records source hashes, extraction/parser versions, exact quotes/offsets, and candidate IDs. Actor/action/trigger/condition/ordering/exception fields start unresolved; the interpretation and review questions guide human review. Heuristics identify normative language, not complete business meaning. Review the surrounding source and exceptions. Drafts are rejected as verification policies.

The review JSON has a required `draft_hash`, policy identity/version, declared field types, reviewer/date metadata and exactly one decision per candidate. Copy the hash printed by `rules draft` into the review after inspecting that draft. See [the example review](../examples/procurement-review.json). Each decision has `candidate_id`, `decision` (`approve`, `reject`, `review_only`), and a nonblank `reason`. Only `approve` accepts a `rule` mapping using the [existing rule grammar](rule-format.md), with `source` and `approved` omitted: Veriq attaches the validated original citation and review metadata. Edit the rule title, scope, condition, and mapping to record the approved interpretation. Rejected and external/manual requirements remain in the version-controlled review file, outside enforcement. If every candidate is rejected or review-only, no policy is created and approval returns exit 2.

The draft hash covers the parsed draft, including source identity, candidates and interpretations; JSON formatting and key order do not affect it. A changed draft requires fresh review before recording its current hash. Old review files without `draft_hash` are rejected. If you edit the draft itself, inspect the edits and obtain its current hash with:

```bash
python -c 'from pathlib import Path; from veriq.sop import read_draft; print(read_draft(Path("reports/sop-draft.json")).content_hash)'
```

Keep the SOP, draft, review, and approved policy together in version control under your team's review process. Metadata is a reviewer claim, not authenticated approval. MCP cannot perform approval.

## Citation and extraction boundaries

`verify --sop` validates policy document identity and every supplied citation before returning a completed audit. Changed bytes, extraction/parser versions, locations, offsets, or quotes fail with exit 2. Without the source, rules still run but their citations are explicitly unvalidated; `--strict-unknown` counts these review items. Citation warnings set `review_required` without changing workflow coverage or suppressing introduced failures. Hand-authored policies require no SOP. JSON `traceability` rows and the Markdown matrix connect citations to rule IDs, workflow evidence, verdicts, comparisons, and limitations.

Readers are local and never execute macros, JavaScript, embedded files, or links:

- Input: at most 10 MiB; extracted text: at most 120,000 characters; drafts: at most 100 candidates, each quote at most 4,000 characters. Split larger sources before drafting.
- Draft JSON, review JSON and approved policy YAML must each fit the core readers' 2 MiB UTF-8 byte limit. Authoring also checks the readers' nesting, item and YAML limits before creating output files; repeated section text can make an artifact larger than its SOP text. Audit reports retain their separate 16 MiB limit.
- PDF: 1–30 unencrypted pages, each with extractable text. Locations use one-based page numbers and character offsets in extracted page text. OCR is excluded; mixed scanned/text content still requires human review of extraction completeness and layout.
- DOCX: at most 1,000 ZIP parts, 40 MiB declared total decompressed size, and 3,000 body/table paragraphs. Locations use one-based paragraph indices, offsets, and the nearest Heading style. No rendered-page claim is made.
- DOCX rejects macros/embedded files, encrypted or duplicate ZIP parts, XML entity declarations, text boxes, tracked changes, imported content, content controls and fields (including cached REF values). Flatten unsupported content to plain text first. Headers, footers, footnotes and endnotes are excluded with an explicit limitation that remains in the draft and audit; place enforceable requirements in the body.

Quotes preserve extracted text, which can differ from visual PDF reading order. Citation validity proves the passage exists, not that the interpretation is correct or the full SOP was understood.

## Optional Ollama assistance

```bash
veriq rules draft --sop examples/procurement-sop.docx --model YOUR_INSTALLED_MODEL \
  --output reports/model-draft.json
```

Omit `--model` for deterministic heuristics and no network traffic. Assistance sends extracted text only to `127.0.0.1:11434`, uses a 45-second socket timeout and bounded JSON response, and validates exact quotations before emitting drafts. It never approves a rule or downloads a model. Select/install a model suited to your hardware separately. Model output is untrusted and can vary. Transport/schema/citation failure returns exit 2 without creating the draft. The client follows the [Ollama generate API](https://docs.ollama.com/api/generate); testing uses a simulated service, not a measured model-quality claim.

## Local read-only MCP

```bash
veriq mcp --root /absolute/path/to/reviewed-project
```

Configure your MCP client to launch the absolute path to this environment's `veriq` executable with arguments `mcp`, `--root`, and the chosen directory. This uses the [official Python SDK](https://github.com/modelcontextprotocol/python-sdk) with stdio only. This local command has no HTTP listener or uploads; [Phase 2](hosted-deployment.md) supplies a separate OAuth-protected hosted mode. A ChatGPT attachment is not automatically accessible to the server.

Tool file arguments must be relative paths within the configured root, including after symlink resolution. Choose a directory containing only files you intend to make readable. This is a local trusted-filesystem boundary, not isolation against another process racing file replacements.

| Tool | Purpose |
|---|---|
| `ingest_sop_document` | Located SOP text and hash |
| `ingest_n8n_workflow` | Node identities/types and graph edges without parameters/credentials |
| `verify_workflow_rules` | Same core verification as CLI |
| `compare_workflow_versions` | Same policy applied to both workflow revisions |
| `get_audit_finding` | Exact finding from a session audit |
| `export_audit_report` | Return JSON/Markdown without writing files |
| `draft_sop_requirements` | Heuristic drafts with validated citations; no model call |

Verification tools accept `sop`, `strict_unknown` and `fail_on_all`; comparison also requires `baseline`. Completed audits are held in memory, at most eight audits of at most 16 MiB each. Restarting or eviction requires rerunning the audit. Tool annotations declare read-only behavior. Tools cannot edit files, approve policy, execute workflows or override verdicts.

The repository includes a distribution-ready [auditor skill](../skills/veriq-auditor/SKILL.md); it is not installed globally or publicly published. The hosted plugin ZIP builder packages this skill with deployment metadata.

Smoke-test with the [official Inspector CLI](https://modelcontextprotocol.io/docs/tools/inspector) from the repo root:

```bash
npx -y @modelcontextprotocol/inspector --cli .venv/bin/python -m veriq mcp --root examples --method tools/list
npx -y @modelcontextprotocol/inspector --cli .venv/bin/python -m veriq mcp --root examples \
  --method tools/call --tool-name verify_workflow_rules \
  --tool-arg workflow=purchase-v2.json --tool-arg rules=veriq.rules.yaml
```

The protocol test also initializes a real stdio client, lists tools, verifies, exports canonical JSON and checks a rejected path escape. Human pilot reviews, model quality/hardware checks and public distribution remain release work.
