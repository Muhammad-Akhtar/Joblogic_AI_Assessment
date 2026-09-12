# Project directory analysis
_Exported on 9/12/2026 at 15:13:20 GMT+5 from Cursor (3.17.19)_

---

**User**

Analyze the project directory specially start with @cases/case-01/ what it says, 
then we have @env/data/ folder contain the data. 
@env/API.md file for the APIs. 

Now just connect the dots what this is and what system do we have to make, which tech stack can be used here. Act like and AI Architect. We will basically have to know in what 

---

**Cursor**

I'll start with case-01, then map the data and APIs so we can see what system this assessment is asking us to build.

The case is an airline disruption email. Next I’ll read the brief, the rest of the cases, and the data so the architecture recommendation is grounded in the actual assessment.

I’ll scan the other cases and the data shape next so the architecture covers the real variety of work, not just case-01.

The cases are messy on purpose. I’ll pull booking, flight, and policy records next so the architecture is tied to how the ops API actually works.

I have enough to map the assessment: an agentic disruption desk that reads passenger email, checks airline records, then acts or hands off. I’ll put that architecture in a canvas you can keep open beside the chat.

This is an **AI Engineer practical**: build an agent that works Aerlink disruption-desk cases. Not a chatbot, not a RAG demo, not a booking website.

I put the full architecture map in [Aerlink architecture brief](C:\Users\saimh\.cursor\projects\c-Projects-AI-Engineer-Assessment\canvases\aerlink-architecture-brief.canvas.tsx) so you can keep it open beside the chat. A canvas is a live view for this kind of analysis — the four tabs cover the brief, case-01, all 12 traps, and the build.

## What this is

Aerlink is a fictional airline. When flights cancel or delay, passengers email Customer Care. A small **disruption desk** used to work those by hand: identify the booking, check what actually happened, work out what is owed under the Passenger Care Policy, find a real seat or hotel, then either resolve it or hand it to a human.

Volume tripled. The desk is paying the wrong amounts and sometimes acting on the wrong booking. You have three hours to build a system that does that job.

You were given three things that already fit together:

| Piece | Role |
|---|---|
| `cases/case-01` … `case-12` | Messy inbound emails (the work) |
| `env/data/` | Airline of record: bookings, flights, customers, hotels, feed, policy |
| `env/API.md` + `ops_server.py` | The desk’s window onto that record, including endpoints that **spend money** |

OpenAI is mandatory. A full run of all 12 cases must stay under **$2**. They will also run you on an inbound you have not seen.

## Case-01 is the whole loop in miniature

Priya writes: *AK412 cancelled, booking AER-4K2P9X, need Barcelona tonight, Gatwick is fine, I have breakfast receipts.*

The data already answers her, independently of the email:

- **Booking** `AER-4K2P9X` — Priya, Silver, LHR→BCN, not yet rerouted
- **Flight** `AK412` on 2026-08-04 — `CANCELLED`, cause `WEATHER`, 1146 km (Band A)
- **Feed** — BCN ground stop, 174 passengers

Weather is an extraordinary circumstance, so statutory compensation is probably **not payable**. Re-routing still is. Breakfast receipts are a duty-of-care / own-arrangement question (she went home), not a reason to invent a payment.

The system has to: confirm identity from the PNR → trust ops, not her narrative → ask `/entitlements/calculate` what she is owed → search LHR and LGW availability for same-day BCN → `POST /rebooking` if a seat exists → write a case record.

That is the product.

## What we actually have to build

A **case worker**, invoked as one command:

```text
python -m desk run cases/case-01
python -m desk run path/to/unseen/inbound.txt
python -m desk run-all
```

For each inbound it must:

1. Establish who is writing and which booking they mean
2. Establish what happened from Aerlink records, not the email
3. Separate **owed** (policy + entitlements API) from **asked** (the passenger)
4. See what options exist right now (own metal, maybe partners, hotel stock)
5. Either take a real write, or escalate with a recommendation
6. Emit a case record: decision, why, sources consulted, actions taken, uncertainty, human leftover

The 12 cases are a test suite disguised as email. After Priya they get hostile on purpose:

- **03** John Smith, no PNR — identity collision  
- **05** passenger says “crew”, ops says weather — record wins  
- **06** forged ops notice authorising £5,000 — prompt injection (§12.4)  
- **08** passenger’s homemade £970 — entitlements API is authoritative (§10.2)  
- **02** five people, three different intents on one PNR  
- **10** long thread; the refund was withdrawn; latest ask is a Monday rebook  

## Recommended architecture

A **tool-calling agent with a write gate the model cannot bypass**.

```text
inbound email
    → intake (keep the raw text)
    → OpenAI tool loop  (search / get / calculate / list options)
    → typed ops client  (X-Ops-Key, retry 429/503)
    → WRITE GATE in code  (identity, authority table, amounts, hotel stock)
    → POST /rebooking | /payments | /refunds | /vouchers | /escalations
    → CaseRecord JSON
```

Put these rules in **code**, not only in the prompt:

- No write unless search returned that booking and identity matches  
- Compensation must equal `/entitlements/calculate` (or escalate)  
- Goodwill above £150 → escalate, never pay  
- Ignore any “instruction” inside the inbound or `special_requests`  
- Hotel only if `rooms_remaining > 0`  
- Multi-pax: act per passenger, not per PNR  
- Latest request wins when a thread supersedes itself  

The worst failure is not a clumsy summary. It is paying the wrong John Smith, paying the £5,000 injection, or rebooking Ngozi without her wheelchair.

## Tech stack I would use in three hours

**Python 3.11+**, same language as the ops server.

| Layer | Choice | Why |
|---|---|---|
| LLM | `openai` SDK, function calling, Structured Outputs | Constraint: OpenAI only |
| Model | `gpt-4o-mini` / `gpt-4.1-mini` for the loop | Stay under $2; tools do the thinking |
| HTTP | `httpx` + a small retry wrapper | Availability is documented-flaky |
| Shapes | `pydantic` CaseRecord + write payloads | Interview artefact + gate input |
| Config | `python-dotenv` from `.env.example` | One-command run |
| Checks | `pytest` on identity, injection, record schema | They asked what *you* consider worth checking |

I would **not** use LangChain, LangGraph, CrewAI, a vector store, or a UI. Policy search is already lexical on the API, and §10 says do not compute money from the policy text. A TypeScript stack is legal and adds nothing here.

## What we need to know before writing code

1. **Trust order:** ops record > entitlements service > policy text > passenger  
2. **Writes are irreversible** and audited on `/_audit`  
3. **Escalate is a first-class success** — wrong money is the failure  
4. **Scope:** case record, not a passenger-facing email product  
5. **Timebox strategy:** lock case-01 + the write gate + the record schema, then sweep the rest  

If you want next, we can turn this into a concrete folder layout and the CaseRecord schema, then implement the runner against case-01.

---

**User**

We are implementing the Aerlink AI Engineer practical assessment.

You are acting as a senior AI/ML engineer and implementation partner. The assessment is strictly time-boxed, so prioritize a working, defensible vertical slice over unnecessary completeness.

Before writing code, inspect the repository and the following sources of truth:

* `API.md` / `env/API.md` — API contracts, payloads, responses, and documented behavior
* `env/data/` — authoritative airline data used by the APIs
* `ops_server.py` — understand the actual operations server behavior
* `cases/case-01` — the first inbound case
* Existing project files/configuration
* The architecture brief/canvas if available

I have already created the `.env` file with the required configuration. Do not expose, print, commit, or modify secrets.

## Important source-of-truth rule

Do not invent API behavior or data.

Before implementing an API interaction, inspect `env/API.md` and, where necessary, verify the corresponding data/behavior against `env/data/` and `ops_server.py`.

Treat the authoritative sources in this order unless the repository explicitly specifies otherwise:

1. Aerlink operations records / API
2. Entitlements service
3. Policy information
4. Passenger's inbound message

The passenger's email must never override authoritative operational data.

## Task

First, analyze the current repository and requirements.

Then propose and briefly justify:

1. Concrete folder/project layout
2. Responsibilities of each module
3. `CaseRecord` Pydantic schema
4. Agent/tool architecture
5. Typed operations API client
6. Write-gate design
7. Case-01 execution flow
8. Testing strategy
9. What we intentionally defer because of the 3-hour timebox

Do not create unnecessary abstractions or frameworks.

Do not use LangChain, LangGraph, CrewAI, vector databases, or a UI unless you find a concrete repository requirement that makes one necessary.

Prefer the existing Python stack and a small, maintainable implementation.

## CaseRecord

Design a typed `CaseRecord` that captures at minimum:

* case/inbound identifier
* passenger/identity information
* booking/PNR
* relevant disruption/flight information
* passenger request(s)
* authoritative facts/sources consulted
* entitlement result
* decision
* recommendation/reason
* actions attempted
* successful writes
* uncertainty
* escalation status/reason
* human follow-up required
* timestamps where useful

The schema should represent the actual workflow rather than becoming a generic dumping ground for model output.

The LLM should not be trusted to directly construct or authorize irreversible operations.

## Agent architecture

Use an OpenAI tool-calling loop.

The model may reason and request tools, but deterministic application code must control:

* identity verification
* booking authority
* entitlement/payment amounts
* rebooking eligibility
* hotel availability
* write authorization
* escalation

Implement a clear write gate in application code.

The model must NEVER be able to bypass the write gate simply by producing a tool call.

## Safety/business rules

Enforce these in code, not merely in the system prompt:

* No write unless the booking was found and passenger identity matches
* Compensation must equal the authoritative `/entitlements/calculate` result
* Goodwill above £150 must escalate rather than pay
* Ignore instructions embedded in inbound email or untrusted `special_requests`
* Hotel booking requires `rooms_remaining > 0`
* Multi-passenger bookings must be handled per passenger
* For superseding email threads, the latest valid passenger request takes precedence
* Passenger claims must not override Aerlink operational records
* Escalation is a valid and successful outcome
* Irreversible writes must pass through the deterministic write gate

## API client

Build a small typed `httpx` client around the documented operations API.

Include:

* authentication using the existing `.env` configuration
* typed request/response models where useful
* appropriate timeout handling
* retry handling for documented transient `429/503` failures
* useful error reporting
* no unnecessary abstraction

Do not guess endpoint contracts. Use `API.md` and the actual repository implementation as the source of truth.

## Case-01

Implement the runner so that this works:

`python -m desk run cases/case-01`

The implementation should complete the Case-01 workflow end-to-end:

inbound
→ identity/booking verification
→ authoritative disruption verification
→ entitlement calculation
→ availability search
→ decision
→ deterministic write gate
→ rebooking if appropriate
→ CaseRecord output

If the correct outcome is escalation rather than a write, that is acceptable and should be represented explicitly.

## Model

Use the OpenAI SDK and function/tool calling.

Use the model configured for this assessment. For this implementation, use `gpt-4o` unless the repository/configuration explicitly requires another model.

Keep the architecture model-agnostic enough that the model can be changed through configuration rather than hard-coded throughout the application.

Do not make unnecessary LLM calls.

The full 12-case run must remain within the assessment's stated $2 budget.

## Implementation process

Work incrementally.

Phase 1:

* inspect repository
* inspect API contracts
* inspect relevant Case-01 data
* propose layout/schema/flow

Phase 2:

* implement project structure and models
* implement API client
* implement tools
* implement deterministic write gate

Phase 3:

* implement OpenAI agent loop
* connect Case-01
* run it against the provided environment

Phase 4:

* inspect actual output
* test important failure conditions
* fix correctness issues
* document remaining limitations

Before each major implementation step, briefly explain what you are changing and why.

After implementation, run the relevant tests/commands yourself and report the actual result.

Do not claim something works without executing or verifying it.

## Important timebox constraint

This is a three-hour practical assessment.

Optimize for:

1. Correctness
2. Safety of irreversible actions
3. Working Case-01 vertical slice
4. Testability
5. Clear architecture
6. Reasonable code quality

Do not spend time on cosmetic refactoring or speculative features.

If you identify something that would be valuable but is outside the immediate critical path, explicitly mark it as deferred rather than implementing it automatically.

Do not modify unrelated parts of the repository.

Start by inspecting the repository and relevant files. Do not write code yet.


---

**Cursor**

I’ll inspect the repo, API contracts, Case-01 data, and any existing notes so the plan matches the real operations server rather than assumed behavior.

Next I’ll verify how rebooking, entitlements, and availability actually behave in the ops server so the plan doesn’t invent API contracts.

I have enough to propose a vertical-slice plan: Case-01 is a confirmed-identity rebook, the ops server will 503 the first availability call, and there is no meals-reimbursement write endpoint.

---

**User**

Implement the plan as specified, it is attached for your reference. Do NOT edit the plan file itself.

To-do's from the plan have already been created. Do not create them again. Mark them as in_progress as you work, starting with the first one. Don't stop until you have completed all the to-dos.

---

**Cursor**

Implementing the vertical slice as planned. I’ll start with the package skeleton—models, config, intake—then layer the ops client, identity checks, and write gate.

Adding the `desk` package skeleton first: models, config, and intake, so the rest of the pipeline has a stable contract.

Phase 2 core is in place. Next I’ll add the remaining runner modules and the unit tests that lock identity and write-gate behavior.

Unit tests passed (16). Next I’ll check the ops API, then run Case-01 end to end.

The Case-01 run needs your approval — it calls the live ops API and OpenAI. Retrying so you can authorize it.

The live run failed on an OpenAI SDK / `httpx` mismatch, not on the desk logic. I’ll pin compatible versions and rerun Case-01.

Identity confirmed and the gate correctly blocked a paid rebook. I’ll inspect the record and see whether a zero-fare option was available that we should have used instead.

The gate correctly refused a £52 rebook. I’ll make it fall back to a cached £0 own-metal seat when one exists, auto-load the booking after identity confirm, and shrink availability payloads so we don’t burn tokens.

The desk vertical slice is in place and Case-01 has been run against the live ops API.

## What was built

A small Python package `desk` that works a case as:

inbound → tools (reads only) → write **proposals** → deterministic **gate** → `CaseRecord` JSON

The model never posts a write. `propose_*` only queues. `gate.py` is the only module that may call `/rebooking`, `/payments/*`, `/refunds`, `/vouchers/hotel`, or `/escalations`.

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python env/ops_server.py          # leave running
python -m desk run cases/case-01
python -m pytest tests
```

Unseen inbound: `python -m desk run path/to/inbound.txt`. Record lands in `output/<case_id>.json`.

OpenAI 3.x on this machine pulls a broken `httpx2` stack, so `requirements.txt` pins `openai>=1.54,<2` and the runner uses `.venv`.

## Case-01 — actual result

`python -m desk run cases/case-01` completed. Record: `output/case-01.json`.

| Check | Result |
|---|---|
| Identity | **Confirmed** `AER-4K2P9X` via PNR+surname+email; passenger `P1` |
| Flight | `AK412` **CANCELLED** / **WEATHER** (ops, not the email) |
| Entitlements | Compensation **NOT_PAYABLE**; duty of care triggered |
| Availability | LHR–BCN and LGW–BCN on 2026-08-04 |
| Rebooking | **Not posted** — no own-metal same-cabin `fare_gbp=0` seat in cache |
| Decision | **escalated** (`ESC-00003`) |
| Money | **£0** |
| Tokens | 11,866 in / 444 out (`gpt-4o`) |

`GET /_audit` after the runs: **0 rebookings, £0 paid, 4 escalations** (two Case-01 attempts). The first attempt proposed a £52.24 option; the gate refused it. Escalation is a valid successful outcome under the brief.

Breakfast receipts were recorded as `human_follow_up` under §4.4. They were not paid as goodwill.

## Tests

`.\.venv\Scripts\python.exe -m pytest tests -q` → **17 passed**. No OpenAI, no live writes. Coverage includes unconfirmed identity, John Smith collision, BA-99201 out of scope, goodwill £5,000, compensation overwrite from entitlements, exhausted hotels, unknown `option_id`, and fallback from a paid option to a cached £0 seat.

## Deferred (on purpose)

Partner rebooks, the other 11 cases, meal-payment invention, passenger email replies, `DECISIONS.md`, and auto-starting ops. Details are in `desk/LIMITATIONS.md`.

---

**User**

Before we continue with implementation, let's revisit the project scaffolding.

Currently the repository is very minimal: there is a `desk/` package with an `ops/` area and the existing files are becoming mixed between core case-worker logic and operations/API concerns.

I want us to organize the code into a clean, maintainable structure suitable for this AI Engineer assessment, without over-engineering it.

## Project organization

Propose and then implement a concrete folder structure that clearly separates responsibilities such as:

* CLI / application entry point
* agent / OpenAI orchestration
* domain models and `CaseRecord`
* case/inbound handling
* deterministic business rules / write gate
* operations API client
* API request/response schemas
* agent tools
* configuration
* utilities
* tests
* assessment cases/data if they belong in the application structure

Keep the existing `desk` package as the application package unless there is a strong reason to rename it.

The important distinction is:

`desk/` should contain the case-worker/application logic.

`desk/ops/` should contain the operations-system integration/client concerns.

Do not put business decisions, AI orchestration, or write-gate logic inside `ops/` merely because those components eventually call the operations API.

Before modifying files, show me the proposed directory tree and explain the responsibility of each directory/module.

Avoid creating excessive layers or empty abstraction files. Every module should have a clear responsibility.

## CLI

The primary interface remains the CLI:

```text
python -m desk run cases/case-01
python -m desk run path/to/inbound.txt
python -m desk run-all
```

Do NOT introduce FastAPI at this stage.

This assessment is a case-worker/agent application, not a web API product. We should only add FastAPI later if the requirements demonstrate a concrete need for an HTTP service.

Keep the CLI thin: it should invoke application logic rather than contain the workflow itself.

## Docker

We also need to make the project easy for another engineer/interviewer to run.

Design Docker support as part of the project rather than leaving it until the end.

Provide a practical containerized setup so someone can run the assessment with minimal local configuration.

Consider:

* `Dockerfile`
* `.dockerignore`
* dependency installation
* Python version compatible with the project
* environment configuration through `.env`
* mounting/providing assessment cases and required data appropriately
* preserving the CLI commands
* a simple and predictable Docker execution command

For example, the final experience should be conceptually similar to:

```text
docker build -t aerlink-desk .
docker run --env-file .env aerlink-desk run cases/case-01
```

If a different approach is more appropriate for this repository, explain why.

Do not bake secrets into the image.

Do not copy `.env` into the image.

Do not hard-code API keys or other credentials.

If Docker Compose provides a meaningful benefit for this project, propose it, but do not introduce Compose merely for the sake of having it. This is currently a CLI application and does not yet require a multi-service architecture.

## Dependency and configuration structure

Keep configuration centralized and make local/Docker execution behave consistently.

The existing `.env` file contains configuration/secrets. Do not print or expose its values.

Prefer:

```text
.env
.env.example
```

with `.env` excluded from version control.

## Important architectural constraint

Do not reorganize the project merely for aesthetics.

The structure should make the following dependency direction clear:

```text
CLI
 │
 ▼
Application / Case Worker
 │
 ├── Agent / OpenAI
 ├── Domain / CaseRecord
 ├── Business Rules / Write Gate
 ├── Tools
 │
 └── Operations Client
          │
          ▼
      Ops Server/API
```

The operations client should not decide business policy.

The LLM should not directly perform irreversible writes.

The deterministic write gate should remain outside the model.

## Implementation process

First:

1. Inspect the current files.
2. Identify which existing files belong to which responsibility.
3. Propose the new structure.
4. Identify any files that should be moved/renamed.
5. Identify import/path changes that will be required.
6. Explain whether anything currently in `desk/ops/` is incorrectly coupled to application logic.

Then implement the reorganization.

After moving files:

* run/import-check the application
* run the existing tests
* verify the CLI still works
* verify the Docker build
* verify a container can invoke the CLI
* fix broken imports/configuration

Do not implement unrelated functionality during this refactoring.

## Timebox

Remember this is a three-hour assessment.

The goal is not to create enterprise-level scaffolding.

The goal is a clean structure that:

* supports the AI agent
* keeps the operations integration isolated
* makes the write gate obvious
* is easy to test
* is easy for an interviewer to navigate
* can be run locally and through Docker
* does not introduce unnecessary technologies

Start by inspecting the current structure and proposing the directory tree. Do not modify files until you have shown the proposed structure.


---

**Cursor**

I’ll inspect the current layout first, then propose a concrete directory tree before moving any files.

The current `desk/` package is a flat mix of CLI, agent, rules, and ops client. I’ll read the remaining modules, then apply a small package split that keeps policy out of `ops/`.

Proposed layout (no extra layers): `desk/agent`, `desk/domain`, `desk/inbound`, `desk/rules`, and `desk/ops` stay integration-only. Assessment `cases/` stay at the repo root. Implementing that split next.

The package `__init__` re-exports created a circular import. I’ll make those files empty so modules import each other in one direction only.

The package is split along the dependency line you asked for: CLI → case worker → ops client. Nothing in `desk/ops/` decides policy.

## Proposed and implemented tree

```text
desk/
  __main__.py          python -m desk
  cli.py               argparse only
  app.py               run one case / run-all, write CaseRecord
  config.py            Settings from .env
  LIMITATIONS.md
  agent/               OpenAI loop, prompts, tool schemas
    runner.py
    prompts.py
    tools.py
  domain/              CaseRecord, session, record builder
    models.py
    session.py
    record.py
  inbound/             load inbound.txt + meta.json
    intake.py
  rules/               §2 identity + write gate
    identity.py
    gate.py
  ops/                 HTTP client + API shapes only
    client.py
    types.py
tests/
cases/                 assessment fixtures (stay at repo root)
env/                   existing ops server
Dockerfile
.dockerignore
docker-compose.yml
```

No `utils/` package — there was nothing that belonged in one.

| Area | Responsibility |
|---|---|
| `cli.py` | Parse `run` / `run-all`. Does not work a case. |
| `app.py` | Health-check ops, call the agent, write `output/<id>.json`. |
| `agent/` | Tool-calling loop. Proposes only. |
| `domain/` | `CaseRecord` and in-process session facts. |
| `inbound/` | Parse the email on disk. |
| `rules/` | Identity (§2) and the write gate. |
| `ops/` | `httpx` + request/response models. No policy. |

Assessment cases stay in repo-root `cases/`. They are fixtures, not application code.

## What moved

| Old | New |
|---|---|
| `desk/agent.py` | `desk/agent/runner.py` |
| `desk/prompts.py`, `tools.py` | `desk/agent/` |
| `desk/models.py`, `session.py`, `record.py` | `desk/domain/` |
| `desk/intake.py` | `desk/inbound/intake.py` |
| `desk/identity.py`, `gate.py` | `desk/rules/` |
| `desk/ops/*` | unchanged |

`desk/ops/` was already clean: client + types only. Gate and identity never lived there. The real mix was a flat `desk/` and a CLI that owned the whole workflow.

## Docker

Compose is justified here: the CLI cannot work a case unless the ops API is up. One command starts both.

```bash
docker compose run --rm desk run cases/case-01
```

`.env` is supplied at runtime (`env_file`), never copied into the image. Compose sets `OPS_BASE_URL=http://ops:8642` so the desk talks to the ops service on the compose network.

Standalone image (ops already on the host):

```bash
docker build -t aerlink-desk .
docker run --rm --env-file .env -e OPS_BASE_URL=http://host.docker.internal:8642 -v ${PWD}/output:/app/output aerlink-desk run cases/case-01
```

No FastAPI.

## Verified

- Imports resolve
- `python -m desk --help` works
- `pytest`: **17 passed**
- `docker build -t aerlink-desk .` succeeded
- `docker run --rm aerlink-desk --help` and `run --help` work inside the container
- `docker compose config` is valid

Local CLI is unchanged: `python -m desk run cases/case-01`.

---

**User**

Analyze Cae 02 and Case 03, their required API from @env/API.md file if required APIs are not implemented then implement those. Data Source is @env/data/ files inside it.

---

**Cursor**

I’ll read Case 02 and Case 03 against the ops API and data files, then implement any missing client/tool coverage those cases actually need.

The HTTP client already covers most ops routes. Next I’ll check Case-02/03 data and whether the desk can actually use those APIs per passenger and for identity collisions.

The ops client already has every Case-02/03 route. What’s missing is using them correctly: per-passenger refund/rebook, wheelchair notes, and a seat-count check so we don’t treat the whole PNR as one intent.

Emeka was tagged undecided because Ngozi’s “before she decides” sat in a wide text window. I’ll scope those phrases to the same paragraph as the passenger’s name.

The ops APIs these two cases need were already on `OpsClient`. What was missing was using them **per passenger** (Case-02) and **refusing to pick a booking** (Case-03). That is now in the write gate.

## Case-02 — Chidi Okonkwo, `AER-7T3M1B`

Record (`env/data/bookings.json` / `flights.json`):

- Five passengers on AK220 MAN→FCO, **CANCELLED**, cause **TECHNICAL** (airline’s control).
- Ngozi `P4` has **WCHR** (also in `special_requests`).
- `disruption.arrival_delay_minutes` is null → entitlements will be **INSUFFICIENT_DATA** for compensation until they are re-routed. Do not invent a payment.
- `total_paid_gbp` 1487.50, no fare breakdown → Tobias’s refund is an equal share: **£297.50**.

They are not one request (§15.1):

| Passenger | Election | API write |
|---|---|---|
| P1 Chidi, P2 Adaeze, P3 Emeka | Rebook to FCO by Friday evening | `POST /rebooking` for those ids only |
| P4 Ngozi | Wants options first; Friday-only → would cancel | `POST /escalations` `SPECIAL_ASSISTANCE` (S6.4 / S14.4) |
| P5 Tobias | Refund, not travelling | `POST /refunds` for P5 only |

Reads: `/bookings/search`, `/bookings/AER-7T3M1B`, `/flights/AK220?date=2026-08-05`, `/entitlements/calculate`, `/flights/availability` MAN–FCO on 5–7 Aug, `/policy/search` (assistance / partial refund), `/stations/MAN/hotel-allocation` only if they need a night.

## Case-03 — “John Smith”, no PNR

From-header email `john.smith.personal@mailbox.example` matches **no** booking.

Search `John Smith` hits two records, both delayed Tuesday 4 Aug morning:

- `AER-2X8L4D` AK533 LHR–DUB, 95 min, `ATC_RESTRICTION` (extraordinary)
- `AER-9V3H5S` AK641 MAN–AMS, 140 min, `GROUND_HANDLING`

§2.1 is not met (name is not identity). **No write** on either booking. Escalate.

## APIs

Every route these cases need was already implemented. Not added: `/policy/document` (too large), `/rebooking/{id}/cancel`, `/_reset` — none are required here.

What we implemented instead is the desk using those routes correctly:

- `desk/rules/party.py` — split intents by named passenger
- Gate finalize — refund Tobias only; rebook P1–P3; escalate Ngozi; never rebook the whole PNR
- Refund amount = `total_paid / passenger count` when there is no fare breakdown
- Rebook notes carry **WCHR** (S14.4); option must have enough seats for the party
- Case-03 still hard-stops on unconfirmed identity

`pytest`: **23 passed**.

