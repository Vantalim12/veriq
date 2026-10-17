"""Validate source traceability independently of static workflow verdicts."""

from .ingestion import InputError
from .sop import document_reference, validate_span

UNAVAILABLE = "SOP source unavailable; citation is unvalidated"


def source_evidence(rule, policy, document):
    result = {"citation": rule.source, "document": policy.source_document, "validated": False}
    if document is None:
        return result, UNAVAILABLE
    if policy.source_document != document_reference(document):
        raise InputError("policy source document identity does not match the supplied SOP extraction")
    if rule.source is None:
        return result, "Rule has no SOP source span; traceability needs review"
    validate_span(rule.source, document)
    result["validated"] = True
    return result, "; ".join(document["limitations"]) or None


def matrix(findings):
    return [{"rule_id": f["rule_id"], "source": f.get("source"), "verdict": f["verdict"],
             "regression": f["regression"], "evidence": f["evidence"], "limitations": f["limitations"]}
            for f in findings]
