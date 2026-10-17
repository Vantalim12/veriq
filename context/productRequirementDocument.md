# Veriq — Product Requirements

**Status:** Product requirements; the P0 core is implemented for controlled evaluation, with [release validation still pending](../docs/evaluation.md). P1 local implementation is available; [SOP/MCP usage and remaining validation](../docs/sop-and-mcp.md) describe its scope.  
**Source:** [veriq-plan.md](veriq-plan.md), version 2.0, 2026-10-16.  
**Working tagline:** Detect broken business rules before your automations go live.

## Product outcome

Veriq helps an n8n developer determine whether a workflow change breaks an agreed business rule. It checks exported workflow configuration against human-approved rules, compares revisions, and produces reproducible evidence that a developer or reviewer can inspect before deployment.

The differentiator is repeatable verification and traceability: stable rules, supported workflow semantics, concrete counterexample paths, validated references, and a usable CI result. SOP interpretation assists rule authoring; the deterministic verifier establishes verdicts within its declared model.

## Users and jobs

| User | Trigger | Job | Useful outcome |
|---|---|---|---|
| Solo n8n developer / small automation agency | A workflow changes before client deployment | Check that agreed routing, thresholds, and controls still hold | A reproducible report identifying introduced failures |
| Operations or QA reviewer | A procedure must be mapped to automation configuration | Review interpretations and inspect supporting evidence | SOP passage → approved rule → workflow evidence |
| Developer reviewing a pull request | A candidate export is committed | Apply the same approved policy to both revisions | A clear gate with retained audit artifacts |

The first supported scenario is procurement: purchases above PHP 10,000 require a reviewed approval control before fulfillment. A candidate connection that bypasses the control should produce a supported counterexample, while unknown live approval behavior remains a disclosed limitation.

## Delivery boundaries

The confirmed sequence is **CLI → GitHub Actions → read-only local MCP**. The [design brief](designBrief.md) describes a future website and presentation direction; it does not add a web application to the initial release.

| Phase | Required scope | Delivery gate |
|---|---|---|
| P0 core preview, target weeks 1–6 | One exported n8n workflow, approved rules, three rule types, deterministic checks, revision comparison, JSON/Markdown reports, CLI and CI example | Reliable labeled fixtures and a reproducible procurement regression demo |
| P1 hybrid v0.1, target completion by week 8 | Located PDF/DOCX text, requirement candidates, human approval, traceability, optional local LLM, read-only MCP wrapper | Valid citations, enforced approval boundary, two pilot reviewers |
| Later, demand dependent | Broader adapter support, optional runtime evidence, review history, collaboration and hosted interfaces | Separate validation and security work |

The schedule is a solo-developer target, assuming an existing computer and internet and $0 in additional local software costs. It is not a delivery guarantee. Optional local AI depends on available hardware.

## Functional requirements

| ID | Priority | Requirement | Acceptance evidence |
|---|---|---|---|
| PR-01 | P0 | Safely ingest one n8n JSON export with an initial 100-node limit | Invalid, oversized, malformed, and excessive-depth inputs are rejected without executing workflow content |
| PR-02 | P0 | Preserve node IDs, type/version, disabled state, parameters, and output/input-indexed connections | Fixtures demonstrate correct normalization and stable graph identity |
| PR-03 | P0 | Publish a version-pinned compatibility list | Supported IF routing and literal comparisons are tested; unknown versions/features remain explicit |
| PR-04 | P0 | Read human-authored approved rules from `veriq.rules.yaml` | Strict validation; stable rule IDs; no arbitrary code or unapproved AI drafts enforced |
| PR-05 | P0 | Support `must_pass_through`, `forbid_path`, and `require_condition` | Each has passing, failing, and uncertain fixtures with evidence |
| PR-06 | P0 | Compare a workflow baseline and candidate using the same policy | All rules run on both revisions; structural changes are distinguished from regressions |
| PR-07 | P0 | Export JSON and Markdown audit reports | Rule IDs, input/policy hashes, engine version, node/path evidence, and limitations are present |
| PR-08 | P0 | Provide documented CLI and GitHub Actions behavior | Introduced failures block under the default comparison policy; artifacts survive a failed check |
| PR-09 | P1 | Extract located text from text-based PDF/DOCX SOPs | PDF pages or DOCX headings/paragraphs identify actual source passages; scanned OCR is outside scope |
| PR-10 | P1 | Draft requirements with heuristics and optional local AI | Every candidate retains a verifiable source span and stays a draft until reviewed |
| PR-11 | P1 | Support human review of meaning, scope, and control mapping | Reviewer may edit, approve, or reject; approved policy is committed through the team's review process |
| PR-12 | P1 | Produce an SOP-to-rule-to-evidence traceability matrix | Citations and workflow references validate against the identified input revisions |
| PR-13 | P1 | Expose the same engine through read-only MCP functions | Tool results match CLI results for equivalent inputs and configuration |

### Rule outcomes

| Verdict | Product meaning |
|---|---|
| `PASS` | The applicable rule holds within supported semantics and the declared model boundary; unresolved relevant uncertainty prevents PASS |
| `FAIL` | A supported counterexample or contradictory configuration establishes a violation |
| `NEEDS_REVIEW` | A conclusion depends on unresolved behavior, mapping, interpretation, or exploration coverage |
| `UNSUPPORTED` | The requested feature or rule falls outside the engine's declared capability |
| `NOT_APPLICABLE` | The requirement explicitly does not apply to the selected scope |

Severity (`low`, `medium`, `high`, `critical`) is independent of verdict. A rule with a proven violation remains `FAIL` even when other paths are unknown; those coverage limitations remain visible. Veriq presents counts and evidence rather than a compliance percentage or invented confidence score.

### Verification and CI behavior

Comparison reports classify findings as `INTRODUCED`, `RESOLVED`, `PERSISTING`, `CHANGED`, or `UNKNOWN_IMPACT`. The default gate blocks newly introduced, deterministic failures; pre-existing failures remain reported and can be made blocking through the explicit all-failures policy. Unknowns warn by default and can block in strict mode.

A standalone check without a workflow baseline reports actual rule verdicts, leaves regression classification empty, and returns exit code 1 for a proven failure. It cannot call a failure newly introduced without comparison evidence. Full exit-code precedence belongs to the [technical requirements](technicalRequirementDocument.md#cli-and-exit-contract).

## Human approval and trust

The approved policy is the enforceable artifact. Reviewer identity and review date are user-provided metadata backed by Git review and team process; initial scope does not include accounts, authenticated signoff, or tamper-proof approval. A node named “Manager Approval” is insufficient: the reviewer must map the control to supported configuration and disclose any live/manual behavior outside the model.

Confidential inputs stay local by default. Imported workflow code, expressions, and SOP instructions are treated as data. Optional AI extraction never grants PASS, changes approved rules automatically, or sends customer files to an external service without explicit authorization.

## Excluded from the initial release

- Workflow execution, live n8n connections, production credentials, real HTTP actions, automatic repair, and deployment.
- Arbitrary expressions/JavaScript, unrestricted connector semantics, custom nodes, sophisticated loops, and unknown sub-workflows.
- Regulatory certification, proof of all live executions, or claims about external/manual approval enforcement.
- Dashboard, accounts, hosted uploads, multi-tenancy, billing, SSO, OCR, online vector storage, and PDF report generation.

## Validation and release criteria

1. Interview five potential users in week 1. Continue exploration if at least three report a repeated relevant problem and at least two offer a synthetic/redacted case. These are validation targets, not established market evidence.
2. Start with 12 hand-labeled synthetic fixtures; grow to at least 30 cases spanning supported checks, bypasses, threshold changes, reversed branches, unreachable/disabled guards, and unknown behavior.
3. Require 100% expected agreement on the seeded supported subset, zero false PASS on labeled unsupported/dynamic cases, and valid emitted node/parameter references. Failures block release.
4. Verify canonical verdicts and finding identities repeat over three runs with identical pinned inputs and environment. A rename with the same node ID must not cause a false regression.
5. Demonstrate JSON/Markdown reports, a controlled CI failure, and successful artifact retention. Start CI in warnings-only evaluation until the fixture gate is met.
6. Evaluate SOP extraction separately: at least 20 labeled normative requirements, target ≥90% candidate recall, valid accepted citations, and no unapproved candidate enforced.
7. Two pilot reviewers must understand and act on a finding without developer guidance. Publish measured limitations and evaluation results.

## Related contracts

- [App flow](appFlow.md): local, review, CI, and MCP journeys.
- [Technical requirements](technicalRequirementDocument.md): engine behavior, safety, and implementation decisions still to validate.
- [Artifact schema](databaseSchema.md): file-based entities and relationships.
- [Design brief](designBrief.md): reference-derived visual direction.
- [Glossary](../CONTEXT.md): canonical domain terms.
