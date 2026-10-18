"""Regression cases for the synthetic SOP uploaded in the hosted pilot."""

from pathlib import Path
import re

import pytest

pytest.importorskip("pymupdf")

from veriq.ingestion import digest
from veriq.sop import Draft, draft_requirements, read_sop, validate_span

FIXTURE = Path(__file__).parent / "fixtures/purchasing-approval-sop.pdf"
EXPECTED = {
    "REQ-001": "REQ-001 | Required fields: If requestId, requesterEmail, or vendorName is missing/empty, or amount is not a positive number, the request MUST be rejected before processing.",
    "REQ-002": "REQ-002 | Duplicate prevention: If isDuplicate=true, the request MUST be rejected and MUST NOT reach Process Purchase.",
    "REQ-003": "REQ-003 | High-value approval: For amount > PHP 10,000, managerApproved MUST be true AND managerId MUST be nonempty before the request reaches Process Purchase.",
    "REQ-004": "REQ-004 | Unapproved high-value request: A high-value request without valid manager approval MUST be held, not processed. The final status MUST be held_for_approval.",
    "REQ-005": "REQ-005 | Standard-value processing: For 0 < amount <= PHP 10,000 and complete, nonduplicate inputs, the request MAY be processed without requiring manager approval.",
    "REQ-006": "REQ-006 | Audit preparation: Every path that reaches Process Purchase MUST subsequently pass through Prepare Audit Entry before Final Status Output. The prepared audit data MUST include requestId, amount, managerApproved, and managerId. This fixture requires preparation only, not external persistence.",
    "REQ-007": "REQ-007 | Terminal status: Every handled request MUST reach Final Status Output with a finalStatus equal to processed, rejected, or held_for_approval.",
    "REQ-008": "REQ-008 | Approval identity: For high-value purchases, managerId alone is insufficient; managerApproved=true alone is also insufficient. Both must be present together before processing.",
}


def test_uploaded_purchasing_pdf_preserves_all_eight_requirements():
    document = read_sop(FIXTURE)
    assert document["document_hash"] == "sha256:51b8f6990fd2d96ad9a7eb7652ea4f6967f7721e0ce1b26e4907f5c7409cd0b7"
    draft = draft_requirements(document)
    assert len(draft.candidates) == 8
    assert [candidate.requirement_id for candidate in draft.candidates] == list(EXPECTED)
    assert draft.generator == "heuristic-2"
    for candidate in draft.candidates:
        assert re.sub(r"\s+", " ", candidate.source.quote) == EXPECTED[candidate.requirement_id]
        assert candidate.source.page == 1
        assert validate_span(candidate.source.model_dump(), document) == candidate.source
        assert candidate.status == "draft"
        assert all(getattr(candidate, field) is None for field in
                   ("actor", "action", "trigger", "condition", "ordering", "exceptions"))
    assert [instruction.page for instruction in draft.verification_instructions] == [1, 2, 2]
    assert "Veriq must inspect reachability" in draft.verification_instructions[-1].quote
    for instruction in draft.verification_instructions:
        assert validate_span(instruction.model_dump(), document) == instruction


def document_with(text):
    return {"document_hash": "sha256:" + "0" * 64, "format": "pdf", "extraction_version": "sop-1",
            "parser": "test", "limitations": [], "blocks": [{"id": "page-1", "page": 1, "paragraph": None,
            "section": None, "text": text}]}


def test_labeled_requirements_keep_context_without_blank_lines_and_without_modal_keywords():
    text = ("Purchases must be logged.\nREQ-01: A standard purchase may proceed. Manager approval is optional.\n"
            "REQ-02 | Both must be present. The exception applies only to emergencies.\n"
            "req-03 | Preparation only, not external persistence.")
    document = document_with(text)
    draft = draft_requirements(document)
    assert [candidate.requirement_id for candidate in draft.candidates] == [None, "REQ-01", "REQ-02", "req-03"]
    assert draft.candidates[1].source.quote.endswith("Manager approval is optional.")
    assert draft.candidates[2].source.quote.endswith("The exception applies only to emergencies.")
    assert draft.candidates[3].source.quote.endswith("not external persistence.")
    assert not draft.verification_instructions
    for candidate in draft.candidates:
        validate_span(candidate.source.model_dump(), document)


@pytest.mark.parametrize("word", ["MAY", "can", "permitted", "allowed", "unless", "except", "requires"])
def test_unlabeled_permissions_and_exceptions_are_candidates(word):
    text = f"Standard purchases {word} follow the documented exception."
    draft = draft_requirements(document_with(text))
    assert len(draft.candidates) == 1 and draft.candidates[0].requirement_id is None
    assert draft.candidates[0].source.quote == text


def test_verifier_instructions_are_separate_from_business_audit_requirements():
    text = ("The auditor must approve purchases. The verification engine must inspect branch conditions. "
            "Every processed purchase must contain audit fields. Veriq should NOT infer authentic approval.")
    document = document_with(text)
    draft = draft_requirements(document)
    assert [candidate.source.quote for candidate in draft.candidates] == [
        "The auditor must approve purchases.", "Every processed purchase must contain audit fields."]
    assert len(draft.verification_instructions) == 2
    for source in draft.verification_instructions:
        validate_span(source.model_dump(), document)


@pytest.mark.parametrize("text", [
    "Purchases must be blocked until Veriq can verify manager approval.",
    "Customers must approve the request before the verifier can mark it complete.",
    "When purchases are approved, the verification engine must record the approval.",
])
def test_business_requirements_mentioning_the_verifier_stay_review_candidates(text):
    document = document_with(text)
    draft = draft_requirements(document)
    assert [candidate.source.quote for candidate in draft.candidates] == [text]
    assert not draft.verification_instructions
    validate_span(draft.candidates[0].source.model_dump(), document)


def test_docx_labeled_paragraphs_keep_all_sentences_and_source_locations(tmp_path):
    docx = pytest.importorskip("docx")
    source = docx.Document()
    source.add_heading("Purchase controls", 1)
    text = "REQ-001 | Standard purchases MAY proceed. Manager approval is optional unless flagged."
    source.add_paragraph(text)
    source.add_heading("Verification instructions", 1)
    source.add_paragraph("Veriq must identify unsupported behavior.")
    path = tmp_path / "labeled.docx"
    source.save(path)
    document = read_sop(path)
    draft = draft_requirements(document)
    assert len(draft.candidates) == 1
    candidate = draft.candidates[0]
    assert candidate.requirement_id == "REQ-001" and candidate.source.quote == text
    assert candidate.source.paragraph == 2 and candidate.source.section == "Purchase controls"
    assert draft.verification_instructions[0].paragraph == 4
    assert draft.verification_instructions[0].section == "Verification instructions"


def test_legacy_draft_hashes_remain_valid_and_new_context_is_bound_to_review():
    draft = draft_requirements(document_with("Purchases must receive approval."))
    legacy = draft.model_dump(exclude={"verification_instructions"})
    legacy["generator"] = "heuristic-1"
    for candidate in legacy["candidates"]:
        candidate.pop("requirement_id")
    loaded = Draft.model_validate(legacy)
    assert loaded.content_hash == digest(legacy)
    before = loaded.content_hash
    loaded.candidates[0].requirement_id = "REQ-001"
    assert loaded.content_hash != before
    before = loaded.content_hash
    loaded.verification_instructions.append(loaded.candidates[0].source)
    assert loaded.content_hash != before
