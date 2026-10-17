# Use a deterministic verifier and human-reviewed rules

Veriq combines automation regression testing with SOP interpretation, but an AI interpretation can change between runs and cannot establish workflow path semantics. Use one deterministic Python verification library for the CLI, GitHub Actions, and later read-only MCP tools; AI may propose requirement candidates, while humans approve the version-controlled policy that the verifier enforces. This trades automatic interpretation and immediate dashboard development for reproducible evidence, an inspectable local workflow, and an explicit boundary between a proposal and an enforceable rule.

The initial release uses files for inputs, policies, and reports. A hosted application, shared database, and authenticated approval service are later product decisions; reviewer metadata in a policy is a recorded claim supported by the team's review process, not a cryptographic approval mechanism.

Source: [engineering plan](../../context/veriq-plan.md), sections 0, 3–7, and 13. The CLI-first sequence was confirmed during documentation review on 2026-10-16.
