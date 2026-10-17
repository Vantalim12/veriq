# Policy format — schema version 1

The [example policy](../examples/veriq.rules.yaml) is runnable with the P0 CLI. [policy.schema.json](policy.schema.json) describes its structural types; the engine additionally validates cross-field/type-specific constraints and references. Use human review and Git to establish approval before supplying a policy. Reviewer/date fields are claims, not an identity or signature service.

## Common fields

```yaml
schema_version: 1
policy_id: procurement
policy_version: 1
fields:
  body.amount: number
rules:
  - id: REQ-004
    title: High-value purchases cross the reviewed blocking control
    type: must_pass_through
    severity: high
    scope:
      source_node_id: intake
      target_node_id: fulfillment
    gate_node_id: approval-gate
    when:
      field: body.amount
      operator: gt
      value: 10000
    approved:
      reviewer: example-reviewer
      reviewed_on: '2026-10-16'
```

Required policy fields are `schema_version`, `policy_id`, `policy_version`, and 1–100 rules. `fields` declares the typed input assumptions for predicates: `number` or `string`. A referenced field must be declared with the matching literal type. A predicate contains `field`, `operator`, and `value`; numbers support `eq/ne/gt/ge/lt/le`, while strings support `eq/ne`. Missing/null fields, implicit coercion, dates, arbitrary expressions, and compound predicates are outside this grammar.

Identifiers use ASCII letters, digits, underscore, dot, colon, or hyphen, with a maximum length of 128. Field paths use dot-separated identifiers. Rule IDs are unique; every rule needs a title, type, severity, and reviewer/date metadata. Quote review dates. Extra policy/rule keys, duplicate mapping keys, YAML anchors/aliases, unsafe tags, and non-finite numbers are rejected.

## Rule types

| Type | Required fields | Meaning |
|---|---|---|
| `must_pass_through` | `scope.source_node_id`, `scope.target_node_id`, `gate_node_id` | Every applicable, supported source-to-target route crosses the reviewed blocking Wait control |
| `forbid_path` | `scope.source_node_id`, `scope.target_node_id` | No supported route connects the endpoints; an optional reviewed `gate_node_id` permits only routes crossing that gate |
| `require_condition` | `node_id`, `condition` | The designated IF v1 configuration has the approved field/operator/literal |

Path rules accept one optional `when` predicate describing applicability at the selected source. Endpoints and gate must be distinct. The gate must map to a supported Wait v1 using webhook resume with no timeout; a name or No Operation node is insufficient. A missing source/target/control identity requires review. No feasible route for `must_pass_through` requires applicability review; it is not vacuous PASS. A graph route that is absent or provably infeasible can satisfy `forbid_path`.

`require_condition` uses a predicate-shaped `condition`, for example:

```yaml
node_id: threshold
condition:
  field: body.amount
  operator: gt
  value: 10000
```

It checks configuration equality, not arbitrary logical equivalence. It does not accept path scope, gate, or `when`. An unsupported node/condition yields UNSUPPORTED; a supported conflicting literal configuration yields FAIL.

A reviewer can explicitly exclude a rule using `applicable: false` with a nonblank `not_applicable_reason`; the result is NOT_APPLICABLE. Approval remains required. Without that explicit exclusion, a missing node or uncertain path cannot silently become non-applicable.

## Source references

Optional `source_document` and rule `source` metadata remain **unvalidated** review items when no SOP is supplied. P1 authoring creates document-bound spans; `verify --sop` checks their hash, parser/extraction identity, location, offsets, and exact quote before marking traceability validated. Hand-authored rules still work without a source. See [SOP authoring](sop-and-mcp.md) for the review contract and limits.

## Comparison identity

The same selected policy runs on both workflow revisions. Rule IDs, stable node IDs, supported branch conditions, and route evidence determine findings; node names and array positions do not determine semantic identity. Reports retain full JSON pointers against each actual revision separately.

A previously passing rule that now has a supported violation is INTRODUCED. A failing rule that becomes fully supported PASS is RESOLVED. An additional supported route absent from a complete baseline can be INTRODUCED even if another failure already existed. An altered condition on an already failing route is CHANGED, not automatically a new violation. Unknown semantics or capped coverage cannot establish a confident resolution or complete change impact. Use `--fail-on-all-verified-failures` when any current supported violation must block, including changed historical failures.

At most eight counterexample routes per rule are retained. Further evidence or exploration beyond the budget produces an explicit coverage limitation; a supported failure remains FAIL. Identical inputs, policy bytes, engine/adapters, and effective configuration yield identical canonical reports, without run timestamps.

Each finding records `coverage_complete` for its static workflow analysis, separately from source-citation warnings. `review_required` includes verdict follow-up, citation warnings and unresolved comparison impact. A disconnected unsupported gate cannot invalidate an independently supported bypass.
