from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Published list prices, USD per 1M tokens. Cached input is typically half of input.
# Unknown models fall back to gpt-4o and are flagged on the report.
# There is no remaining-credit API for a normal project key (admin-only Costs API).
# `python -m desk usage` reports desk-recorded tokens and estimated USD only.
_RATES: dict[str, tuple[float, float, float]] = {
    # model: (input, output, cached_input)
    "gpt-4o": (2.50, 10.00, 1.25),
    "gpt-4o-mini": (0.15, 0.60, 0.075),
    "gpt-4.1": (2.00, 8.00, 0.50),
    "gpt-4.1-mini": (0.40, 1.60, 0.10),
    "gpt-4.1-nano": (0.10, 0.40, 0.025),
    "gpt-4-turbo": (10.00, 30.00, 5.00),
}

LEDGER_NAME = "usage.jsonl"


@dataclass
class UsageSnapshot:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cached_tokens: int = 0
    rounds: int = 0
    estimated_usd: float = 0.0
    model: str = ""
    rate_key: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UsageEntry:
    at: str
    case_id: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cached_tokens: int = 0
    rounds: int = 0
    estimated_usd: float = 0.0
    rate_key: str = ""
    source: str = "ledger"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class UsageReport:
    entries: list[UsageEntry] = field(default_factory=list)
    latest: list[UsageEntry] = field(default_factory=list)

    @property
    def prompt_tokens(self) -> int:
        return sum(e.prompt_tokens for e in self.entries)

    @property
    def completion_tokens(self) -> int:
        return sum(e.completion_tokens for e in self.entries)

    @property
    def total_tokens(self) -> int:
        return sum(e.total_tokens for e in self.entries)

    @property
    def estimated_usd(self) -> float:
        return sum(e.estimated_usd for e in self.entries)

    def as_dict(self) -> dict[str, Any]:
        return {
            "runs": len(self.entries),
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated_usd": round(self.estimated_usd, 6),
            "entries": [e.as_dict() for e in self.entries],
            "latest_per_case": [e.as_dict() for e in self.latest],
            "note": (
                "Desk-recorded usage from chat.completions `usage` objects. "
                "Remaining account credit is not available without an OpenAI admin key."
            ),
        }


def cached_tokens_from(usage: Any) -> int:
    details = getattr(usage, "prompt_tokens_details", None)
    if details is None:
        return 0
    return int(getattr(details, "cached_tokens", 0) or 0)


def rates_for(model: str) -> tuple[str, tuple[float, float, float]]:
    key = (model or "").strip().lower()
    ranked = sorted(_RATES.items(), key=lambda item: len(item[0]), reverse=True)
    for name, rates in ranked:
        if key == name or key.startswith(f"{name}-"):
            return name, rates
    return "gpt-4o", _RATES["gpt-4o"]


def estimate_usd(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
) -> float:
    _, (in_rate, out_rate, cached_rate) = rates_for(model)
    cached = max(0, min(int(cached_tokens), int(prompt_tokens)))
    billed_prompt = max(int(prompt_tokens) - cached, 0)
    usd = (
        billed_prompt * in_rate
        + cached * cached_rate
        + int(completion_tokens) * out_rate
    ) / 1_000_000
    return round(usd, 6)


def snapshot_from_totals(
    *,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    total_tokens: int | None = None,
    cached_tokens: int = 0,
    rounds: int = 0,
) -> UsageSnapshot:
    rate_key, _ = rates_for(model)
    prompt = int(prompt_tokens or 0)
    completion = int(completion_tokens or 0)
    total = int(total_tokens if total_tokens is not None else prompt + completion)
    cached = int(cached_tokens or 0)
    return UsageSnapshot(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_tokens=cached,
        rounds=int(rounds or 0),
        estimated_usd=estimate_usd(model, prompt, completion, cached),
        model=model,
        rate_key=rate_key,
    )


def ledger_path(output_dir: Path) -> Path:
    return Path(output_dir) / LEDGER_NAME


def append_ledger(output_dir: Path, entry: UsageEntry) -> Path:
    path = ledger_path(output_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry.as_dict(), ensure_ascii=True) + "\n")
    return path


def entry_from_record(payload: dict[str, Any], *, source: str) -> UsageEntry | None:
    usage = payload.get("token_usage")
    if isinstance(usage, dict):
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        cached = int(usage.get("cached_tokens") or 0)
        rounds = int(usage.get("rounds") or 0)
        usd = usage.get("estimated_usd")
        rate_key = str(usage.get("rate_key") or "")
        model = str(payload.get("model") or usage.get("model") or "")
    else:
        prompt = int(payload.get("prompt_tokens") or 0)
        completion = int(payload.get("completion_tokens") or 0)
        total = int(payload.get("total_tokens") or (prompt + completion))
        cached = int(payload.get("cached_tokens") or 0)
        rounds = int(payload.get("rounds") or 0)
        usd = payload.get("estimated_usd")
        rate_key = str(payload.get("rate_key") or "")
        model = str(payload.get("model") or "")
    if prompt == 0 and completion == 0 and total == 0:
        return None
    if usd is None:
        usd = estimate_usd(model, prompt, completion, cached)
    if not rate_key:
        rate_key = rates_for(model)[0]
    return UsageEntry(
        at=str(payload.get("finished_at") or payload.get("at") or ""),
        case_id=str(payload.get("case_id") or ""),
        model=model,
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total,
        cached_tokens=cached,
        rounds=rounds,
        estimated_usd=float(usd),
        rate_key=rate_key,
        source=source,
    )


def load_ledger(output_dir: Path) -> list[UsageEntry]:
    path = ledger_path(output_dir)
    if not path.is_file():
        return []
    entries: list[UsageEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        entry = entry_from_record(payload, source="ledger")
        if entry:
            entries.append(entry)
    return entries


def load_case_records(output_dir: Path) -> list[UsageEntry]:
    root = Path(output_dir)
    if not root.is_dir():
        return []
    entries: list[UsageEntry] = []
    for path in sorted(root.glob("*.json")):
        if path.name == LEDGER_NAME:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        entry = entry_from_record(payload, source=path.name)
        if entry:
            entries.append(entry)
    return entries


def collect_report(output_dir: Path) -> UsageReport:
    ledger = load_ledger(output_dir)
    latest = load_case_records(output_dir)
    entries = ledger or latest
    return UsageReport(entries=entries, latest=latest)


def format_usd(amount: float) -> str:
    return f"${amount:.4f}"


def format_report(report: UsageReport) -> str:
    lines = ["OpenAI usage (from this desk, not the OpenAI billing console)", ""]
    if report.latest:
        lines.append("Latest case records in output/")
        lines.append(_table(report.latest))
        lines.append("")
    if report.entries and report.entries is not report.latest:
        lines.append("Cumulative ledger (every run, including re-runs)")
        lines.append(_table(report.entries, include_when=True))
        lines.append("")
    elif not report.entries:
        lines.append("No OpenAI usage recorded yet. Work a case first:")
        lines.append("  python -m desk run cases/case-01")
        return "\n".join(lines)

    lines.append(
        f"Total  {report.prompt_tokens:>10} in / {report.completion_tokens} out / "
        f"{report.total_tokens} tokens   {format_usd(report.estimated_usd)}   "
        f"({len(report.entries)} run(s))"
    )
    lines.append(
        "Account remaining credit is not readable with this API key "
        "(OpenAI Costs API requires an admin key). These figures are this desk's recorded usage."
    )
    unknown = {e.model for e in report.entries if e.model and e.rate_key == "gpt-4o" and not e.model.lower().startswith("gpt-4o")}
    if unknown:
        lines.append("Priced as gpt-4o (unknown model): " + ", ".join(sorted(unknown)))
    return "\n".join(lines)


def _table(entries: list[UsageEntry], *, include_when: bool = False) -> str:
    rows = []
    header = ["case_id", "model", "rounds", "in", "out", "total", "USD"]
    if include_when:
        header = ["when", *header]
    rows.append(header)
    for entry in entries:
        row = [
            entry.case_id or "-",
            entry.model or "-",
            str(entry.rounds or "-"),
            str(entry.prompt_tokens),
            str(entry.completion_tokens),
            str(entry.total_tokens),
            format_usd(entry.estimated_usd),
        ]
        if include_when:
            row = [entry.at or "-", *row]
        rows.append(row)
    widths = [max(len(r[i]) for r in rows) for i in range(len(header))]
    out = []
    for i, row in enumerate(rows):
        line = "  ".join(cell.ljust(widths[j]) for j, cell in enumerate(row))
        out.append(line)
        if i == 0:
            out.append("  ".join("-" * w for w in widths))
    return "\n".join(out)


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
