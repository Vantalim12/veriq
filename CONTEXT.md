# Veriq

Veriq provides evidence about whether changes to a business automation preserve approved business rules. Its vocabulary distinguishes static verification, human interpretation, and evidence about changes.

## Language

### Requirements and approval

**SOP requirement**:
A business obligation expressed in a standard operating procedure, including its conditions and exceptions.
_Avoid_: Executable rule, certified control

**Requirement candidate**:
A proposed interpretation of an SOP requirement that a human has not yet approved for enforcement.
_Avoid_: Approved rule, verified requirement

**Approved rule**:
A human-reviewed, machine-checkable interpretation of a business requirement, with an explicit workflow scope and control mapping.
_Avoid_: AI verdict, inferred policy

**Policy**:
A versioned collection of approved rules used together in a verification run.
_Avoid_: SOP, workflow baseline

**Control mapping**:
The reviewed association between a business control and specific workflow nodes, parameters, and supported behavior.
_Avoid_: Node-name match, proof of live approval

### Workflow comparison

**Workflow baseline**:
The reviewed workflow revision selected as the reference for a comparison.
_Avoid_: Policy baseline, guaranteed passing workflow

**Candidate workflow**:
The workflow revision being checked against the policy and, when supplied, the workflow baseline.
_Avoid_: Requirement candidate

**Structural change**:
A difference between workflow revisions, such as a changed connection, condition, node type, or name.
_Avoid_: Regression, violation

**Regression**:
A newly introduced, deterministically established rule violation relative to the selected workflow baseline under the same policy.
_Avoid_: Every workflow change, every existing failure

### Results and evidence

**Audit**:
One recorded verification result for identified workflow inputs, a policy, and a declared verification model.
_Avoid_: Compliance certificate, runtime test

**Finding**:
A rule-specific result with a verdict, evidence, limitations, and a comparison classification when available.
_Avoid_: Unverified AI suggestion

**Verdict**:
The result of checking a rule: PASS, FAIL, NEEDS_REVIEW, UNSUPPORTED, or NOT_APPLICABLE.
_Avoid_: Severity, confidence percentage

**Counterexample path**:
A concrete workflow route that establishes a rule violation under supported semantics.
_Avoid_: Hypothetical live execution, arbitrary reachable path

**Source span**:
An identifiable passage in a particular SOP revision that supports a requirement interpretation.
_Avoid_: Unverified quotation, document summary

**Model boundary**:
The workflow behavior, conditions, assumptions, and exploration limits within which a verdict is supported.
_Avoid_: Full execution coverage, compliance guarantee

**Coverage limitation**:
An explicit boundary or unresolved behavior that prevents a complete conclusion about some part of a rule's scope.
_Avoid_: Passing check, statistically measured confidence
