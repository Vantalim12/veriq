import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("docx")

from veriq.cli import main
from veriq.ingestion import InputError, MAX_BYTES, MAX_ITEMS, check_tree
from veriq.sop import approve_draft, draft_requirements, read_draft, read_review, read_sop

ROOT = Path(__file__).resolve().parents[1]


def test_approval_rejects_policy_that_exceeds_reader_item_limit(tmp_path, capsys):
    source = ROOT / "examples/procurement-sop.docx"
    document = read_sop(source)
    draft = draft_requirements(document)
    draft_path = tmp_path / "draft.json"
    draft_path.write_text(draft.model_dump_json(), encoding="utf-8")
    review = json.loads((ROOT / "examples/procurement-review.json").read_text())
    review["draft_hash"] = draft.content_hash
    stack = [review]
    items = 0
    while stack:
        value = stack.pop()
        items += 1
        if isinstance(value, dict):
            stack.extend(value.values())
        elif isinstance(value, list):
            stack.extend(value)
    review["fields"].update({f"field{index}": "number" for index in range(MAX_ITEMS - items)})
    check_tree(review)
    review_path = tmp_path / "review.json"
    review_path.write_text(json.dumps(review), encoding="utf-8")
    assert draft_path.stat().st_size <= MAX_BYTES
    assert review_path.stat().st_size <= MAX_BYTES
    policy = approve_draft(read_draft(draft_path), read_review(review_path), document)
    payload = yaml.safe_dump(policy.model_dump(exclude_none=True), sort_keys=False, allow_unicode=True)
    assert len(payload.encode("utf-8")) <= MAX_BYTES
    with pytest.raises(InputError, match="item limit"):
        check_tree(policy.model_dump(exclude_none=True))

    output = tmp_path / "output/policy.yaml"
    assert main(["rules", "approve", "--sop", str(source), "--draft", str(draft_path),
                 "--review", str(review_path), "--output", str(output)]) == 2
    assert "item limit" in capsys.readouterr().err
    assert not output.parent.exists()
