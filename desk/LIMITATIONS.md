# Limitations

The desk works all twelve fixtures through the same path: intake → tool loop → write gate.
Deterministic rules (identity, party split, thread latest-wins, entitlements overwrite,
goodwill cap, hotel stock) are covered by `pytest` without calling OpenAI.

## Live OpenAI

A full `python -m desk run-all` still spends tokens. Prefer `gpt-4o-mini` for that sweep.
`python -m desk usage` reports this desk's recorded tokens and estimated USD. Remaining
account credit is not readable with a normal project key (OpenAI's Costs API is admin-only).

## Intentionally deferred

- Partner rebooking as a desk confirm (supervisor-only under §12.1).
- A meals/receipt reimbursement write — the ops API has no such endpoint.
- Passenger-facing reply emails, UI, RAG, LangChain.
- Auto-starting the ops server from the runner.

## Known gaps

- Availability inventory is generated and often has no zero-fare economy seat. The desk
  escalates rather than invent a booking or exceed authority.
- The first own-carrier availability call is expected to 503; the client retries.
- Live model behaviour on an unseen inbound can still waste tool rounds; the gate is the stop.
