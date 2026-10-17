# Supported n8n semantics — P0 preview

**Adapter manifest:** `n8n-v1-bounded-1`  
**Canonicalization:** version 1. These are pinned node `typeVersion` values, not a claim of support for an entire n8n application release.

| Node type | Accepted typeVersion | Supported interpretation |
|---|---|---|
| `n8n-nodes-base.webhook` | 1 | Entry waypoint with main output 0; input values are governed by declared policy assumptions |
| `n8n-nodes-base.noOp` | 1 | Linear main routing with empty parameters |
| `n8n-nodes-base.if` | 1 | One numeric comparison or string equality/inequality; true output 0, false output 1 |
| `n8n-nodes-base.wait` | 1 | Blocking route waypoint with `resume: webhook`, no timeout, main output 0 |

Only main connections to input 0 are modeled for nodes that accept input. Webhook is an entry node and cannot be treated as accepting an incoming edge. Parallel edges retain channel, indices, and connection position. Unsupported channel/port use on a relevant route creates review-needed coverage.

## IF grammar and typed assumptions

IF v1 uses `parameters.conditions.number` or `.string` containing exactly one comparison with `value1`, `operation`, and `value2`. The adapter accepts `combineOperation` all/any with that single comparison; multiple active comparisons, boolean/date conditions, regex, and other operations remain unsupported.

The left operand may be a literal or exactly a dot-path reference such as `={{ $json.body.amount }}`. This syntax is recognized, never executed. Other expressions, arithmetic, environment access, computed properties, bracket notation, and interpolation are not interpreted. The right operand must be a literal.

Numeric literals are finite and at most `2**53` in absolute value. The model uses finite binary64 number comparisons and supports `equal`, `notEqual`, `larger`, `largerEqual`, `smaller`, and `smallerEqual`. Strings support exact case-sensitive `equal`/`notEqual`. It does not reproduce implicit type coercion or missing/null behavior: the reviewed policy explicitly assumes referenced fields are present and have the declared type.

Path feasibility checks conjunctions of comparisons over unchanged, independently typed fields. Incompatible branch predicates are pruned. Unknown nodes or a Wait may change payload identity; a later field-dependent IF then requires review. An IF comparing constants can still be interpreted without resolving external payload data.

## Coverage boundary

Only the declared source-to-target scope and relevant graph routes are checked. Relevant unknown node types/versions, disabled nodes, arbitrary Code, sub-workflows, expressions, execution/error options, and cycles prevent an all-path PASS. An independently supported counterexample remains FAIL even when another route is unknown. An unrelated disconnected unknown node does not invalidate a local supported rule result.

A Wait establishes a configured blocking waypoint, not who called its resume endpoint or whether a manager approved anything. The fulfillment node in the example is also a synthetic waypoint. This engine never executes workflow code, calls a connector, authenticates an approver, or proves a live business transaction correct.

The static model does not assess workflow failures, retries, timeouts outside the accepted gate configuration, external side effects, cross-item joins, or distributed execution. Use runtime/integration tests separately.

## Resource budgets

| Budget | Bound |
|---|---|
| Workflow/policy input | 2 MiB per file, UTF-8 |
| Workflow size | 1–100 nodes, at most 1,000 connections |
| Nesting | 32 levels for inputs; 40 for saved reports, including evidence/source wrappers |
| Parsed input values | 50,000 items; YAML event scanning also bounded |
| Exploration | 10,000 generated/processed states per path rule, including queued states |
| Stored counterexamples | Eight per rule, with an explicit warning if capped |
| Report | 16 MiB per JSON/Markdown file, enforced during serialization; larger output is a tool error |

Traversal exhaustion and cycles are review items, not PASS. Limits are recorded in the audit configuration where relevant. These are conservative preview defaults, not measured capacity or latency promises.

## Normalization and evidence

Keep raw SHA-256 separately from normalized graph identity. Node array ordering, object key ordering, display names, canvas positions, notes, and colors do not create rule regressions. Node IDs, types/versions, parameters, execution metadata, workflow settings, and indexed connections remain part of the configuration basis. Renaming IDs requires human mapping rather than a guessed equivalence.

Path findings include actual typed edges, applicability predicates, branch conditions, and parameter pointers. Node/edge/parameter references are checked against each workflow revision before an audit is returned. Report rendering escapes imported text; complete files replace old artifacts, and outputs cannot overwrite supplied input files. Both reports carry the audit identity; if writing fails, exit 2 takes precedence and any older report must not be treated as the failed run's result.

## Primary references

The adapter was checked against n8n's own source on 2026-10-16: [IF v1](https://github.com/n8n-io/n8n/blob/master/packages/nodes-base/nodes/If/V1/IfV1.node.ts), [No Operation](https://github.com/n8n-io/n8n/blob/master/packages/nodes-base/nodes/NoOp/NoOp.node.ts), [Webhook](https://github.com/n8n-io/n8n/blob/master/packages/nodes-base/nodes/Webhook/Webhook.node.ts), and [Wait](https://github.com/n8n-io/n8n/blob/master/packages/nodes-base/nodes/Wait/Wait.node.ts). Their current source URLs can change; the executable accepted subset is pinned by this adapter version and the committed fixtures. No live n8n import/execution test has been performed.
