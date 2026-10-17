"""Located, bounded SOP text and source-backed draft authoring."""

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import re
from typing import Annotated, Literal
from zipfile import ZipFile

from pydantic import Field

from .contracts import Approval, Contract, Identifier, Policy
from .ingestion import InputError, digest, load_json, read_bytes

EXTRACTION_VERSION = "sop-1"
MAX_SOP_BYTES = 10 * 1024 * 1024
MAX_EXPANDED_BYTES = 40 * 1024 * 1024
MAX_TEXT = 120_000
MAX_PARAGRAPHS = 3000
MAX_CANDIDATES = 100
Hash = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]


class SourceSpan(Contract):
    document_hash: Hash
    extraction_version: str
    block_id: str
    start: Annotated[int, Field(ge=0)]
    end: Annotated[int, Field(gt=0)]
    quote: Annotated[str, Field(min_length=1, max_length=4000)]
    page: int | None = None
    paragraph: int | None = None
    section: str | None = None


class Candidate(Contract):
    id: Identifier
    status: Literal["draft"] = "draft"
    source: SourceSpan
    actor: str | None = None
    action: str | None = None
    trigger: str | None = None
    condition: str | None = None
    ordering: str | None = None
    exceptions: str | None = None
    interpretation: Annotated[str, Field(max_length=4000)]
    review_questions: list[str] = Field(default_factory=lambda: [
        "Review actor, trigger, conditions, ordering and exceptions; map supported behavior to stable node IDs.",
        "Does this require external/manual evidence rather than a machine-checkable rule?",
    ])


class Draft(Contract):
    schema_version: Literal[1] = 1
    status: Literal["draft"] = "draft"
    document: dict
    generator: str
    candidates: Annotated[list[Candidate], Field(max_length=MAX_CANDIDATES)]

    @property
    def content_hash(self):
        return digest(self.model_dump())


class Decision(Contract):
    candidate_id: Identifier
    decision: Literal["approve", "reject", "review_only"]
    reason: Annotated[str, Field(min_length=1, max_length=4000)]
    rule: dict | None = None


class Review(Contract):
    schema_version: Literal[1]
    draft_hash: Hash
    policy_id: Identifier
    policy_version: Annotated[int, Field(ge=1)]
    fields: dict = Field(default_factory=dict)
    approved: Approval
    decisions: Annotated[list[Decision], Field(min_length=1, max_length=MAX_CANDIDATES)]


def read_sop(path: Path):
    raw = read_bytes(path, MAX_SOP_BYTES)
    blocks = []
    warnings = []
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            import pymupdf
            parser = "PyMuPDF:" + pymupdf.VersionBind
            with pymupdf.open(stream=raw, filetype="pdf") as doc:
                if doc.needs_pass or not 1 <= doc.page_count <= 30:
                    raise InputError("SOP PDF must be unencrypted and contain 1–30 pages")
                for index, page in enumerate(doc, 1):
                    value = page.get_text("text", sort=True)
                    if not value.strip():
                        raise InputError("PDF has a page without extractable text; provide a text-based SOP (no OCR)")
                    blocks.append({"id": f"page-{index}", "page": index, "paragraph": None, "section": None, "text": value})
                    if sum(len(b["text"]) for b in blocks) > MAX_TEXT:
                        raise InputError("SOP exceeds the 120,000-character text limit")
        elif suffix == ".docx":
            from docx import Document
            from docx.oxml.ns import qn
            from docx.text.paragraph import Paragraph
            import docx
            parser = "python-docx:" + docx.__version__
            with ZipFile(BytesIO(raw)) as archive:
                entries = archive.infolist()
                if (len(entries) > 1000 or len({e.filename for e in entries}) != len(entries)
                        or sum(e.file_size for e in entries) > MAX_EXPANDED_BYTES):
                    raise InputError("DOCX exceeds the 1000-part/40 MiB decompression budget or has duplicate parts")
                for entry in entries:
                    if entry.flag_bits & 1 or any(s in entry.filename.lower() for s in ("vbaproject", "embeddings/")):
                        raise InputError("encrypted DOCX, macros and embedded files are unsupported")
                    if entry.filename.endswith((".xml", ".rels")):
                        xml = archive.read(entry)
                        if b"<!DOCTYPE" in xml.replace(b"\x00", b"").upper() or b"<!ENTITY" in xml.replace(b"\x00", b"").upper():
                            raise InputError("DOCX XML declarations/entities are unsupported")
                if any(e.filename.startswith(("word/header", "word/footer", "word/footnotes", "word/endnotes")) for e in entries):
                    warnings.append("Only document body and table paragraphs are extracted; headers, footers, footnotes and endnotes are excluded.")
            doc = Document(BytesIO(raw))
            body = doc.element.body
            if any(next(body.iter(qn("w:" + tag)), None) is not None for tag in ("altChunk", "txbxContent", "ins", "del")):
                raise InputError("DOCX text boxes, tracked changes and imported content must be flattened before extraction")
            if any(next(body.iter(qn("w:" + tag)), None) is not None for tag in ("fldSimple", "fldChar", "instrText")):
                raise InputError("DOCX fields must be flattened to plain text before extraction")
            if next(body.iter(qn("w:sdt")), None) is not None:
                raise InputError("DOCX content controls must be flattened to plain text before extraction")
            section = None
            for index, element in enumerate(body.iter(qn("w:p")), 1):
                if index > MAX_PARAGRAPHS:
                    raise InputError("DOCX exceeds the 3000-paragraph limit; no rendered page count is inferred")
                paragraph = Paragraph(element, doc)
                value = paragraph.text
                if paragraph.style and paragraph.style.name.startswith("Heading"):
                    section = value
                if value.strip():
                    blocks.append({"id": f"paragraph-{index}", "page": None, "paragraph": index, "section": section, "text": value})
                if sum(len(b["text"]) for b in blocks) > MAX_TEXT:
                    raise InputError("SOP exceeds the 120,000-character text limit")
        else:
            raise InputError("SOP must be a text-based .pdf or .docx file")
    except ImportError as exc:
        raise InputError("SOP support requires installation with 'veriq[sop]'") from exc
    except InputError:
        raise
    except Exception as exc:
        raise InputError("unreadable or unsupported SOP document") from exc
    if not blocks:
        raise InputError("SOP has no extractable text")
    return {"document_hash": "sha256:" + sha256(raw).hexdigest(), "format": suffix[1:],
            "extraction_version": EXTRACTION_VERSION, "parser": parser, "blocks": blocks, "limitations": warnings}


def document_reference(document):
    return {key: document[key] for key in ("document_hash", "format", "extraction_version", "parser", "limitations")}


def span_for(document, block, start, end):
    return SourceSpan(document_hash=document["document_hash"], extraction_version=EXTRACTION_VERSION,
                      block_id=block["id"], start=start, end=end, quote=block["text"][start:end],
                      **{key: block[key] for key in ("page", "paragraph", "section")})


def validate_span(value, document):
    span = SourceSpan.model_validate(value)
    block = next((b for b in document["blocks"] if b["id"] == span.block_id), None)
    if (span.document_hash != document["document_hash"] or span.extraction_version != document["extraction_version"]
            or block is None or not span.start < span.end <= len(block["text"])
            or block["text"][span.start:span.end] != span.quote
            or any(getattr(span, key) != block[key] for key in ("page", "paragraph", "section"))):
        raise InputError("SOP citation does not match the supplied document, location and exact quote")
    return span


def draft_requirements(document, model=None):
    candidates = []
    if model:
        from .local_model import propose
        proposals = [(proposal, None) for proposal in propose(document, model)]
    else:
        proposals = []
        for block in document["blocks"]:
            for match in re.finditer(r".+?(?:[.!?](?=\s|$)|$)", block["text"], re.S):
                quote = match.group().strip()
                if re.search(r"\b(must|shall|required?|only if|unless|before)\b", quote, re.I):
                    start = match.start() + match.group().index(quote)
                    proposals.append(({"block_id": block["id"], "quote": quote, "interpretation": quote}, start))
    if len(proposals) > MAX_CANDIDATES:
        raise InputError("more than 100 requirement candidates; split the SOP into smaller documents")
    for proposal, start in proposals:
        if not isinstance(proposal, dict) or set(proposal) != {"block_id", "quote", "interpretation"}:
            raise InputError("invalid model candidate shape")
        block = next((b for b in document["blocks"] if b["id"] == proposal["block_id"]), None)
        quote = proposal["quote"]
        if (block is None or not isinstance(quote, str) or not quote.strip()
                or (start is None and block["text"].count(quote) != 1)):
            raise InputError("candidate quote is absent or ambiguous in its source block")
        if start is None:
            start = block["text"].index(quote)
        span = span_for(document, block, start, start + len(quote))
        validate_span(span.model_dump(), document)
        candidates.append(Candidate(id=f"CAND-{len(candidates) + 1:03}", source=span, interpretation=proposal["interpretation"]))
    return Draft(document=document_reference(document), generator=f"ollama:{model}" if model else "heuristic-1", candidates=candidates)


def approve_draft(draft, review, document):
    if draft.document != document_reference(document):
        raise InputError("draft belongs to a different document or parser revision")
    if review.draft_hash != draft.content_hash:
        raise InputError("review belongs to a different draft; review the current source and interpretation before approving")
    candidates = {c.id: c for c in draft.candidates}
    if len(candidates) != len(draft.candidates) or {d.candidate_id for d in review.decisions} != set(candidates) or len(review.decisions) != len(candidates):
        raise InputError("review must decide every unique candidate exactly once")
    rules = []
    for decision in review.decisions:
        source = validate_span(candidates[decision.candidate_id].source.model_dump(), document)
        if not decision.reason.strip():
            raise InputError("review decision requires a nonblank reason")
        if decision.decision == "approve":
            if decision.rule is None or "approved" in decision.rule or "source" in decision.rule:
                raise InputError("approved decision needs a rule mapping; source and reviewer are attached by Veriq")
            rules.append({**decision.rule, "approved": review.approved.model_dump(), "source": source.model_dump()})
        elif decision.rule is not None:
            raise InputError("rejected/review-only candidates cannot supply enforceable rules")
    if not rules:
        raise InputError("review contains no machine-checkable approvals; retain the review file without creating a policy")
    return Policy.model_validate({"schema_version": 1, "policy_id": review.policy_id, "policy_version": review.policy_version,
                                  "fields": review.fields, "source_document": document_reference(document), "rules": rules})


def read_draft(path):
    return Draft.model_validate(load_json(read_bytes(path)))


def read_review(path):
    return Review.model_validate(load_json(read_bytes(path)))
