# Deployment and usage

The desk is a **CLI**, not a web server. The operations API is the long-running process. Working a case is always one command that reads an inbound file and writes `output/<case_id>.json`.

Copy `.env.example` to `.env` and put your `OPENAI_API_KEY` in it before anything else.

```bash
cp .env.example .env
```

On Windows PowerShell: `Copy-Item .env.example .env`

| Variable | Default | Used by |
|---|---|---|
| `OPENAI_API_KEY` | (required) | desk |
| `OPENAI_MODEL` | `gpt-4o` in code; `.env.example` sets `gpt-4o-mini` | desk |
| `OPS_BASE_URL` | `http://127.0.0.1:8642` | desk (Compose overrides this to `http://ops:8642`) |
| `OPS_API_KEY` | `aerlink-ops-local-key` | desk and ops |

Never commit `.env`. `.env.example` is the file that belongs in git.

---

## 1. Local (host Python)

Two processes: ops stays up; the desk command runs once per case.

### Setup

```bash
python -m venv .venv
.venv\Scripts\activate          # Unix / macOS: source .venv/bin/activate
pip install -r requirements.txt
```

### Start the operations API

```bash
python env/ops_server.py
```

Leave that terminal running. Check it:

```bash
curl http://127.0.0.1:8642/health
```

PowerShell: `Invoke-WebRequest http://127.0.0.1:8642/health`

Ops-only Docker is also fine here — you can run the desk on the host against a containerised API:

```bash
docker compose up
```

That starts **ops only** on `http://127.0.0.1:8642`. Then use the `python -m desk …` commands below.

### Work a case

From a second terminal, with the venv active:

```bash
python -m desk run cases/case-01
```

Unseen inbound (any file, `meta.json` not required):

```bash
python -m desk run path\to\inbound.txt
```

Every fixture under `cases/`:

```bash
python -m desk run-all
```

OpenAI tokens and estimated USD from this desk's recorded runs (reads `output/`, does **not** call OpenAI billing — a normal project key cannot read remaining credit):

```bash
python -m desk usage
python -m desk usage --json
```

No arguments prints help and exits 0 (it does **not** spend tokens or write to ops):

```bash
python -m desk
python -m desk --help
```

### Output

A `CaseRecord` is written to `output/<case_id>.json`. The CLI also prints the decision, booking, identity status, writes, human follow-up, and that run's OpenAI tokens / estimated USD.

Every successful run appends a line to `output/usage.jsonl`. `python -m desk usage` totals that ledger (or the latest case records if the ledger is empty). Remaining OpenAI account credit is not available without an admin key, so this command does not apply a $2 remaining-budget figure.

### Tests (no OpenAI spend)

```bash
python -m pytest tests
```

### Reset ops between runs

Writes (rebook, payment, escalation) persist on the ops process until you reset. Header is `X-Ops-Key` (see `env/API.md`):

```bash
curl -X POST http://127.0.0.1:8642/_reset -H "X-Ops-Key: aerlink-ops-local-key"
```

PowerShell:

```powershell
Invoke-RestMethod -Method POST http://127.0.0.1:8642/_reset -Headers @{ "X-Ops-Key" = "aerlink-ops-local-key" }
```

---

## 2. Docker

The Compose file has three services:

| Service | What it is | When it starts |
|---|---|---|
| `ops` | Long-running operations API on port 8642 | `docker compose up` |
| `desk` | One-shot CLI (`python -m desk …`) | `docker compose run … desk …` |
| `test` | `pytest` over all twelve case fixtures | `docker compose --profile test run --rm test` |

`desk` is on the `cli` profile so **`docker compose up` starts ops only**. The desk is not a daemon.

Copy `.env.example` to `.env` before `docker compose run … desk …` (Compose reads that file for the OpenAI key).

### Start ops

From the repo root (where `docker-compose.yml` lives):

```bash
docker compose up
```

Detached: `docker compose up -d`

Wait until the healthcheck passes (`ops` healthy). First build can take a minute.

Stop: `Ctrl+C`, or `docker compose down`.

### Work a case

Compose starts ops automatically if it is not already running, then runs the CLI once and removes the desk container:

```bash
docker compose run --rm desk run cases/case-01
```

Unseen inbound — mount the file into the container:

```bash
docker compose run --rm -v /absolute/path/to/inbound.txt:/app/inbound.txt desk run /app/inbound.txt
```

PowerShell:

```powershell
docker compose run --rm -v ${PWD}/path/to/inbound.txt:/app/inbound.txt desk run /app/inbound.txt
```

All twelve cases:

```bash
docker compose run --rm desk run-all
```

OpenAI usage (no extra API call; reads `./output`):

```bash
docker compose run --rm desk usage
```

Records land in `./output` on the host (`./output` is bind-mounted).

### Tests inside Docker

No OpenAI spend:

```bash
docker compose --profile test run --rm test
```

### Ops-only image (from `env/`)

```bash
cd env
docker compose up
```

Then run the desk on the host (`python -m desk run cases/case-01`) with `OPS_BASE_URL=http://127.0.0.1:8642`.

### Standalone desk image (ops already running on the host)

```bash
docker build -t aerlink-desk .
docker run --rm --env-file .env -e OPS_BASE_URL=http://host.docker.internal:8642 -v ${PWD}/output:/app/output -v ${PWD}/cases:/app/cases aerlink-desk run cases/case-01
```

`host.docker.internal` reaches the host from Docker Desktop (Windows / macOS). On Linux, use the host gateway IP or `--network host` instead.

---

## 3. How to use it

1. Start ops (local Python **or** `docker compose up`).
2. Put `OPENAI_API_KEY` in `.env`.
3. Hand the desk a case path.
4. Read `output/<case_id>.json`.

The agent proposes actions. A deterministic write gate is the only code that POSTs to ops (rebook, payment, refund, hotel, escalation). Escalation is a valid successful outcome when identity is unconfirmed, authority is exceeded, or no legal rebook exists.

| Goal | Command |
|---|---|
| One fixture | `python -m desk run cases/case-01` or `docker compose run --rm desk run cases/case-01` |
| File assessors have not shown you | `python -m desk run path/to/inbound.txt` |
| All fixtures | `python -m desk run-all` or `docker compose run --rm desk run-all` |
| OpenAI tokens / estimated $ | `python -m desk usage` |
| Check all 12 cases without spending | `python -m pytest tests` or `docker compose --profile test run --rm test` |
| Replay cleanly | `POST /_reset` with `X-Ops-Key`, then run again |

Do not point the key at a runaway loop. `run-all` calls OpenAI once per case. Develop on one or two cases first.

---

## 4. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `the following arguments are required: command` on `docker compose up` | Old compose started the desk CLI with no subcommand | Pull this compose file: `up` starts ops only; use `docker compose run --rm desk run cases/case-01` |
| Exit 2: `OPENAI_API_KEY is not set` | Missing `.env` or empty key | Copy `.env.example` to `.env` and set the key. Compose reads `.env` from the repo root |
| Exit 3: operations API is not reachable | Ops not running, or desk pointing at the wrong URL | Start ops; locally `OPS_BASE_URL=http://127.0.0.1:8642`; in Compose it is already `http://ops:8642` |
| `env_file: .env` compose error | `.env` does not exist | `cp .env.example .env` (or `Copy-Item .env.example .env`) |
| Case already rebooked / paid | Ops state persisted from a previous run | `POST /_reset` with `X-Ops-Key`, then re-run |
| Port 8642 in use | Another ops process | Stop the other process, or change `OPS_PORT` |
| `docker compose run` hangs on desk | Ops healthcheck never passed | `docker compose logs ops` |
