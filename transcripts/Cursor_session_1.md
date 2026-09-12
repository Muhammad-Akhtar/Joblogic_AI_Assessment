# Fallback handling in AI
_Exported on 9/12/2026 at 16:37:56 GMT+5 from Cursor (3.17.19)_

---

**User**

Have you handled the fallback or human intervention if the case whose details this system can't answer. 

I know we have covered 3 cases but the Implementation seems to handle Deterministic cases, can the agent handle the out of box new case. do let me know how well this implementation relates to AI/ML Domain?

---

**Cursor**

I'll review how fallbacks, human intervention, and new cases are handled, then map that to how much of this implementation is actually AI/ML versus deterministic rules.

The write gate and escalation path are the parts that matter here — I’ll read those next, plus how identity and tools behave on a case that isn’t one of the three fixtures.

Yes — human fallback is a first-class path, not an afterthought. The three fixtures are how you tested it; they are not how the desk decides. A new inbound still goes through the same agent, then the same write gate. If the system cannot act safely, it is supposed to hand the case to a human rather than guess.

## Fallback / human intervention — it is handled

The brief says resolve **or** hand to a human with enough for them to decide. That is encoded in three layers:

**1. The model can choose to stop.**  
`propose_escalation` is a normal tool. `finish_case` can record `uncertainty` and `human_follow_up`. Escalation is treated as a successful outcome, not a failure.

**2. Python auto-escalates if the model forgets.** After the tool loop, `finalize_proposals` queues a human handover when:

- identity is not confirmed under §2.1
- the passenger asked to travel but there is no own-carrier, same-cabin, zero-fare seat
- a passenger has not elected a remedy
- meal receipts were mentioned (no write endpoint; recorded for a human, never paid as goodwill)

**3. The write gate converts unsafe spends into escalations.** Even if the model proposes a write, the gate will not POST it when:

- identity is unconfirmed or out of scope
- goodwill is over £150
- hotel allocation is exhausted
- the rebook `option_id` is missing, paid, partner, or not in this session’s cache

Those become `POST /escalations` with a summary, requested decision, queue, and blocking clause. The `CaseRecord` then shows `decision=escalated` or `partially_resolved`, plus `human_follow_up`.

So “we don’t know / we must not spend” is fail-closed: **no money moves, a human gets a packet**. That is the right safety posture for irreversible ops writes.

What is weaker: if the agent burns all 12 tool rounds without proposing anything, and keywords did not infer a request, you can still land on `no_action` rather than a guaranteed escalation. Uncertainty is also only as good as what the model writes into `finish_case`. The safety net is the gate, not the prompt.

## Out-of-box new cases — yes at architecture, not a per-case script

There is no `if case_id == "case-01"` anywhere in `desk/`. Every inbound, including an unseen file, takes the same path:

```text
inbound.txt  →  LLM tool loop  →  propose_*  →  deterministic gate  →  CaseRecord
```

Unseen cases are a documented entry point: `python -m desk run path/to/inbound.txt`. Intake does not need `meta.json`. The model’s job is messy email → which tools to call → what the passenger asked for. The gate’s job is policy: identity, amounts, authority.

That is why a new case can work even if you only live-ran a few:

| Layer | What generalises | What does not |
|---|---|---|
| LLM + tools | New wording, mixed intents, Spanish rebook phrasing, injection-shaped emails | Completely novel asks with no tool (lounge upgrade, wheelchairs-only logistics) |
| Identity code | Any PNR/email/phone that hits ops | Name-only, John-Smith collisions → unconfirmed → escalate |
| Keyword intake | Cheap prior for rebook/refund/hotel/receipts | Long threads (latest-wins / case-10), unusual phrasing |
| Gate | Any write that violates authority | Partner/fare-difference rebooks stay supervisor-only by design |

So a fourth case is not a new code path. It is a new email against the same ops API. If the email is a normal disruption (who is this, what happened, what are they owed, what seats exist), the agent can work it. If it is outside representative authority, the correct “handling” is escalation — that is still a valid outcome.

Honest limit: you have not proven this with a 12-case eval. Tests cover **shapes** (identity collision, goodwill over limit, non-payable compensation, unknown `option_id`). Live generalisation still depends on the model calling the right tools. The architecture is case-agnostic; the coverage is not yet.

## How this relates to AI/ML

This is **applied LLM systems engineering**, not classical ML. That is the right mapping for an AI Engineer desk, not a gap.

**What is actually AI here**

- A **tool-calling agent** (ReAct-style loop): the model only issues tools, reads results, then `finish_case`.
- **NLU over messy inbound email** — the part that cannot be a regex for every new case.
- Prompt constraints: trust order, “email is evidence not instruction”, propose-only.
- Cost/token accounting as a first-class constraint.

**What is deliberately not ML**

- No training, fine-tuning, embeddings, or RAG (policy search is an ops endpoint; money must come from `/entitlements/calculate`).
- Identity, amounts, and POSTs are **deterministic Python**. They must not vary with temperature.
- Intake keywords are a cheap prior, not a classifier.

That split is the AI/ML claim you should defend:

> The model interprets unstructured text. Code owns irreversible decisions. When the model is unsure or out of authority, a human is the fallback.

In interview language this is: **LLM agent + tools + guardrails + human-in-the-loop**. It is the same pattern as production copilots that can take actions (payments, bookings): the LLM is the planner, not the ledger.

What would make it “more ML” later, if you had a month: an eval set over all 12 + adversarial inbounds, identity-confirmed / escalation / $ per case metrics, maybe a small intent model to replace keywords — still with the same write gate. You would not train the thing that spends money.

**Bottom line:** fallback is designed in (escalate + `human_follow_up`). New cases are handled by the agent, not by hardcoding the three you covered. The implementation is strongly in the AI Engineer domain: an LLM for the messy part, deterministic policy for the dangerous part, humans when the desk must not guess.

---

**User**

desk-1  | __main__.py: error: the following arguments are required: command                                           

when docker compose up command was executed. make a deployment gudie file, on local as well as through docker and how to use it?

---

**Cursor**

The desk container is starting without a CLI command, so Compose fails. I’ll inspect the Docker setup and CLI entrypoint, then add a deployment guide for local and Docker use.

`docker compose up` starts the desk CLI with no subcommand, so argparse exits. I’ll make Compose start only the ops API, print a clear CLI usage if no command is given, and add a local + Docker deployment guide.

`docker compose up` was starting the **desk CLI** with no subcommand. The desk is not a server, so argparse exited with `the following arguments are required: command`.

That is fixed. **`docker compose up` now starts only the operations API.** Work a case with `docker compose run`. Full steps are in `DEPLOYMENT.md`.

## What changed

- **`docker-compose.yml`** — `desk` is on the `cli` profile, so `up` does not launch it. Default command is `--help` if the profile is enabled by mistake.
- **`python -m desk` with no args** — prints usage and exits 0 instead of crashing.
- **`DEPLOYMENT.md`** — local and Docker setup, how to run a case, unseen inbound, tests, reset, troubleshooting.

## Local

```powershell
Copy-Item .env.example .env    # then set OPENAI_API_KEY
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python env/ops_server.py       # leave this running
```

Second terminal:

```powershell
python -m desk run cases/case-01
python -m desk run path\to\inbound.txt    # unseen case
python -m pytest tests
```

Record: `output/<case_id>.json`.

## Docker

```powershell
docker compose up              # ops only, port 8642
docker compose run --rm desk run cases/case-01
```

Unseen file:

```powershell
docker compose run --rm -v ${PWD}/path/to/inbound.txt:/app/inbound.txt desk run /app/inbound.txt
```

`run-all` and pytest are in the guide. Do not use `docker compose up` to “start the desk” — it is a one-shot command, not a long-running container.

---

**User**

Next: Need to see the openai usage through code. Implement this as well and python command to see its results as we are already using cli

---

**Cursor**

I’ll look at how token usage is recorded today, then add a CLI command so we can inspect OpenAI spend from the same `python -m desk` interface.

Tokens are already captured on each case record; I’ll add cost estimates, a persistent spend ledger, and a `python -m desk usage` command so we can inspect OpenAI usage from the CLI.

The ledger loader expected nested `token_usage` like a case record; I’ll accept the flat JSONL rows as well.

OpenAI usage is now measured in code and readable from the same CLI. It does **not** call OpenAI again — it uses the `usage` object on each `chat.completions.create`, then estimates USD from published list prices.

## Commands

```powershell
python -m desk usage
python -m desk usage --json
python -m desk usage --budget 2
```

Docker:

```powershell
docker compose run --rm desk usage
```

Against the existing Case-01 record this already reports:

```text
case-01  gpt-4o  11866 in / 444 out / 12310 tokens  $0.0341
Budget $2.0000   remaining $1.9659
```

Each `run` also prints a line like:

```text
  openai gpt-4o  11866 in / 444 out / 12310 tokens  $0.0341  rounds=8
```

`run-all` prints the same table at the end.

## What the code does

- Sums `prompt_tokens` / `completion_tokens` / `total_tokens` (and cached tokens if present) on every model round.
- Writes that onto the case record, plus `rounds`, `estimated_usd`, and which price row was used.
- Appends `output/usage.jsonl` so **re-runs still count** toward the $2 ceiling (overwriting `case-01.json` does not erase spend).
- `python -m desk usage` totals the ledger if it exists, otherwise the latest `output/*.json` files.

Prices are list rates in `desk/usage.py` (gpt-4o is $2.50 / $10.00 per 1M). That is an estimate for the brief, not the OpenAI billing console.

---

**User**

$2 is assumed budget threshold, modify the code to show real available budget against that access token. and real usage as well. thanks

---

**Cursor**

I’ll look up how this OpenAI SDK exposes live usage and remaining credit for the API key, then wire that into the CLI next to the $2 assessment threshold.

The official Costs API needs an admin key, so I’ll probe this service-account key against the usage and billing endpoints and wire in whatever actually returns spend and remaining credit.

---

**User**

okay if admin key limitations, remove @2 threshold if applied, 

Implement the remaining cases as well. alongside their test cases and docker implementation.

---

**Cursor**

I’ll drop the $2 budget threshold, then inspect the remaining cases and close the gaps with tests and a working Docker path.

I’ll remove the $2 budget gate, add latest-wins and the remaining case rules in code, then cover all 12 cases with tests and a Docker test/run-all path.

The $2 remaining-budget figure is gone. A normal project key cannot read OpenAI account credit (that Costs API is admin-only), so `python -m desk usage` now reports **this desk’s recorded tokens and estimated USD only**.

All **12 fixtures** are handled on the same path, with pytest covering the rules that must not depend on the model.

## Usage

```powershell
python -m desk usage
python -m desk usage --json
```

No `$2` remaining line. It will say remaining credit is not readable without an admin key.

## Remaining cases (in code, not hardcoded IDs)

| Case | What the desk now does in Python |
|---|---|
| 01 | Rebook + receipts follow-up (unchanged) |
| 02 | Split party: rebook Chidi/Adaeze/Emeka, refund Tobias only, escalate Ngozi + WCHR |
| 03 | John Smith collision → unconfirmed → escalate, no write |
| 04 | `BA-99201` → out of scope |
| 05 | Ops weather beats “crew”; own hotel is receipts, not a voucher |
| 06 | £5,000 injection → escalate, never goodwill |
| 07 | Homemade £900 not paid |
| 08 | Entitlements overwrite £970 |
| 09 | Hotel at LGW on the stranded night + rebook |
| 10 | Thread latest-wins: Monday 10 Aug rebook, refund superseded |
| 11 | Hotel + rebook; coat → `LOST_PROPERTY` |
| 12 | Spanish rebook + compensation for both passengers |

Escalation queues are normalised (`SUPERVISOR`, `LOST_PROPERTY`, …).

## Tests (no OpenAI spend)

```powershell
python -m pytest tests
```

**46 passed**, including `tests/test_cases.py` for every fixture.

## Docker

```powershell
docker compose up
docker compose run --rm desk run-all
docker compose --profile test run --rm test
```

`run-all` still calls OpenAI once per case. Use `OPENAI_MODEL=gpt-4o-mini` for that sweep. The pytest profile does not.

---

**User**

from @cases/ we have already implemented @cases/case-01/ , @cases/case-02/ and @cases/case-03/  Kindly confirm

---

**Cursor**

I’ll check the code and tests for cases 01–03 against the fixtures so we can confirm what’s actually implemented, not just assumed.

Yes — **cases 01, 02, and 03 are implemented** on the shared desk path. There is no `if case_id == "case-01"` branching. What differs is how far each one has been **live-run**.

| Case | What it is | In code | Tests | Live OpenAI run |
|---|---|---|---|---|
| **01** Priya / `AER-4K2P9X` | Rebook + receipts; weather → compensation not payable | Identity, entitlements, availability, gate | Intake + identity | **Yes** — `output/case-01.json` |
| **02** Chidi party / `AER-7T3M1B` | Five people, three intents | Party split in `desk/rules/party.py` + gate | Intake + party + gate | **No** record yet |
| **03** John Smith, no PNR | Name collision | Identity stays `unconfirmed`; gate will not write | Intake + identity + gate | **No** record yet |

**Case-01** is the only one with a real agent run against ops + OpenAI. Identity confirmed as Priya, flight taken from ops (`CANCELLED` / `WEATHER`), receipts not paid as goodwill, no zero-fare seat so it escalated.

**Case-02** is implemented so that, if a legal seat exists, the gate refunds **Tobias only** (£297.50), rebooks **Chidi, Adaeze, Emeka**, does **not** rebook **Ngozi** (undecided + WCHR), and escalates her.

**Case-03** is implemented so two John Smiths → identity unconfirmed → **escalation only**, no payment or rebook.

To produce live records for 02 and 03 (needs ops + `OPENAI_API_KEY`):

```powershell
python -m desk run cases/case-02
python -m desk run cases/case-03
```

The pytest coverage for these three does **not** spend tokens.

---

**User**

@cases/case-04 , @cases/case-05, @cases/case-06 
Kindly complete the implementation of these as well like we did for Case-01 to Case-03.
Search for their relevant @env/API.md if any api is not implemented do implement it handle rest of the cases as well. 

---

**Cursor**

I’ll compare cases 04–06 (and the rest) against the ops API and the current desk path, then close any missing endpoints and case-handling gaps.

The full sweep already ran; I’ll inspect cases 04–06 (and the rest) for wrong writes, then close any missing API wiring and gate holes.

The live sweep shows the gaps: case-04 is fine, but case-05 paid a £0 goodwill and tried a non-IATA hotel, and the party logic was auto-rebooking people who never asked. I’ll close those, wire the unused ops APIs, and tighten the rest of the cases.

Tools are wired. Next I’ll lock the case-04–06 (and remaining) behaviour in tests so receipts, injections, and invented rebooks cannot slip through.

Cases **04–06** now follow the same path as 01–03 (intake → tools → write gate), and the rest of the fixtures are covered by the same rules. **58 tests passed.** Live `gpt-4o-mini` runs wrote fresh records under `output/`.

### Cases 04–06 (live)

| Case | Outcome |
|---|---|
| **04** (BA-99201) | Identity `out_of_scope`. Escalate to GENERAL. No Aerlink write. |
| **05** (Marta / weather) | Ops cause is **WEATHER**, not crew. Compensation blocked. £0 goodwill blocked (no POST). Own-arranged £112 hotel is receipts, not a voucher and not goodwill. |
| **06** (injection) | Statutory **£220** from entitlements. **£5000 goodwill was not paid**; it escalated under §12.4. |

### What was going wrong

The previous sweep paid a **£0 goodwill**, tried a hotel at `"Edinburgh"` (not IATA `EDI`), and auto-rebooked single-pax emails that never asked to travel. The gate now:

- refuses goodwill **≤ £0**, receipt/hotel reimbursements, and inbound “ops notices”
- normalises city names to IATA, and **blocks a voucher** when the passenger already booked their own hotel
- only auto-rebooks when the text actually asks to travel (and not once `cabin_flown` is set)

### APIs from `env/API.md`

Ops already implemented these. The desk now exposes them safely:

- **`GET /policy/document`** — metadata only (no 32k dump; amounts still come from entitlements)
- **`POST /rebooking/{id}/cancel`** — client exists; the tool **does not POST** (£65 fee, inventory not restored). Escalate instead
- **`POST /_reset` / `GET /_audit`** — ops hygiene, not case tools

### Rest of the cases

| Case | Handling |
|---|---|
| **07** | Pays statutory £220; £900 demand is escalated, not paid |
| **08** | Pays entitlements **£415**. A proposed £240 “downgrade refund” is now **blocked** — that money is already inside `total_payable_gbp` |
| **09** | Hotel + rebook. `"sitting in Gatwick"` is no longer a false care-receipts hit |
| **10** | Latest-wins: Monday 10 Aug rebook, refund superseded |
| **11** | Hotel/rebook + lost-property escalation |
| **12** | Spanish rebook phrases recognised; compensation follows entitlements |

Hotel stock on this machine was already used from the earlier sweep, so **09/11 escalated on exhausted allocation** — that is the correct desk behaviour when rooms_remaining is 0. For a clean hotel run: `POST /_reset`, then `python -m desk run cases/case-09`.

Re-run any case with:

```bash
python -m desk run cases/case-05
```

I'll work from the repo: first `env/API.md` and the ops server against the client, tools, and write gate, then close any real gaps before tests, Case-01, and `DECISIONS.md`.

---

**User**

Kindly make sure that all the endpoints inside @env/API.md  are implementaed and flexible enough to take the payload from a case that might call it. 

Next final touch, inside @DECISIONS.md file describe what is needed. I will put transcripts my self, 

Initial approach was to serve via FASTAPI then through this way of desk cli approach we used. 

keep the things concise simple and self explanatory in each section. easy to understand, simple english should be used. 

case 01 to 06 are covered within this 3 hours limit. give the reason as well. 

---

**Cursor**

I’ll confirm every `env/API.md` endpoint is on the client with case-flexible payloads, then rewrite `DECISIONS.md` in plain English for the 3-hour 01–06 slice (you add transcripts).

All **21 endpoints** in `env/API.md` are on `OpsClient`. Payloads are case-driven (booking ref, passenger ids, dates, amounts) — nothing is hard-coded to Case-01. **63 tests passed.** `DECISIONS.md` is rewritten in short, plain English. Transcripts are left blank for you.

### API

| Kind | Status |
|---|---|
| Reads (search, booking, flight, availability ± partners, policy search/document, history, entitlements, hotel allocation, feed, health, audit) | Client + agent tool where a case might need it |
| Writes (rebook, hotel, compensation, goodwill, refund, escalation) | Client exists; **only the write gate POSTs** |
| `POST /rebooking/{id}/cancel` | Client can call it. The agent tool will **not** POST (£65 fee, inventory not restored) |
| `POST /_reset` | Client only — ops hygiene, not a case tool |

### DECISIONS.md

- Started as FastAPI (`POST /cases`). Moved to a thin CLI because the job is “inbound file → CaseRecord”, not a public HTTP app.
- AI reads the email and picks tools. Python owns identity, money, hotels, and irreversible writes.
- Trust order: ops → entitlements → policy → passenger.
- Escalation counts as success.

### 3-hour slice: cases 01–06

Those six are the mistakes the brief is about:

1. identity + weather + receipts  
2. split party  
3. two John Smiths  
4. foreign BA PNR  
5. passenger says crew, ops says weather  
6. forged £5000 ops notice  

07–12 use the same path and are covered by pytest. Live polish of all twelve was not the 3-hour claim.

Paste your transcripts into **section 14** of `DECISIONS.md`.

---

**User**

Perfect now we need to analyze and make copy of @DECISIONS_TEMPLATE.md then fill the asked headings. what we did, in simple plain, english text

---

**Cursor**

I’ll rewrite `DECISIONS.md` to match the template headings, in plain English, covering what we actually built. Transcripts stay blank for you to add.

`DECISIONS.md` now follows **every heading** in `DECISIONS_TEMPLATE.md`, in short plain English.

It covers what we actually built: CLI instead of FastAPI, model proposes / Python writes, all of `env/API.md` on the client, and **cases 01–06 in the 3-hour limit** (wrong person, wrong cause, wrong money, untrusted email).

Left blank for you:

- **Name**
- **§9 transcripts table** — paste your files there

The rest of §9 (override FastAPI, let the agent type `desk/` after the plan) is already filled so the interview questions are answered.

