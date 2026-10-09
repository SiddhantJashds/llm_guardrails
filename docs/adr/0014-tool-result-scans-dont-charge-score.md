# 0014. Tool-result scans redact but don't charge score

Status: Accepted
Date: 2026-10-09

## Context

Every `/governance/compliance-check` with violations did two things:
redacted the text *and* docked the acting agent's authority score. That is
correct for prompts and completions (agent- or user-authored text), but wrong
for tool results: the PHI there lives in retrieved DATA the agent was
authorized to read (a `read_database`/`list_patients` result the tool-check
just allowed). Charging the retriever `-20` per turnaround for the database's
own contents meant legitimate read-then-use workflows bled out on their own:
GuardRailBench scenario 1's `data_agent` fell below the `read_database`
threshold purely from handling allowed results, and the "normal workflow"
failed with denials nobody earned.

Alternatives considered: lowering thresholds until the bleed fits (fragile —
any extra low-confidence NER hit re-breaks it, and it concedes the principle);
exempting tool results from scanning entirely (loses the redaction the
downstream LLM/agent demonstrably needs — the RAG scenario passes *because*
retrieved rows are masked before they travel onward).

## Decision

`ComplianceCheckRequest` gains `apply_score: bool = True`. When `False`,
the route still redacts and still writes the receipt (audit trail intact),
but skips trust-state creation and signal application entirely. The bench
bridge (`bench_bridge/main.py`) sets it `False` for `on_tool_result` only;
prompt/completion/handoff paths keep the default. Exfiltration protection
does not rest on this penalty: outbound text is still redacted, out-of-scope
tools still denied, and prompt/completion violations still drain scores.

## Consequences

- Penalty policy now distinguishes *agent-authored/emitted* text (prompts,
  completions, handoffs — penalized) from *authorized retrieved* text (tool
  results — redacted, recorded, not penalized).
- Any future caller scanning third-party content (retriever chunks, webhook
  payloads) should reach for `apply_score=False` for the same reason; anyone
  scanning text the agent itself produced must leave the default on.
