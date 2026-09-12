from __future__ import annotations

import json
import sys
from pathlib import Path

from desk.agent.runner import run_case
from desk.config import Settings
from desk.inbound.intake import load_case
from desk.ops.client import OpsClient, OpsError
from desk.usage import (
    UsageEntry,
    append_ledger,
    collect_report,
    format_report,
    format_usd,
    utcnow,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent


def run_one(path: Path, settings: Settings) -> int:
    """Work one inbound case and write the CaseRecord. CLI stays thin."""
    if not settings.openai_api_key:
        print("OPENAI_API_KEY is not set. Copy .env.example to .env.", file=sys.stderr)
        return 2
    inbound = load_case(path)
    with OpsClient(settings.ops_base_url, settings.ops_api_key) as ops:
        try:
            ops.health()
        except Exception:
            print(
                "Operations API is not reachable at "
                f"{settings.ops_base_url}. Start it with: python env/ops_server.py",
                file=sys.stderr,
            )
            return 3
        try:
            session = run_case(inbound, settings, ops)
        except OpsError as exc:
            print(f"Ops API error: {exc}", file=sys.stderr)
            return 4

    record = session._record  # type: ignore[attr-defined]
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    out = settings.output_dir / f"{inbound.case_id}.json"
    out.write_text(record.model_dump_json(indent=2), encoding="utf-8")
    _record_usage(settings.output_dir, inbound.case_id, record.model, record.token_usage)
    print(f"Wrote {out}")
    print(f"decision={record.decision} booking={record.booking_ref} identity={record.identity.status}")
    if record.successful_writes:
        for action in record.successful_writes:
            result = action.result or {}
            ident = (
                result.get("rebooking_id")
                or result.get("escalation_id")
                or result.get("payment_id")
                or result.get("refund_id")
                or result.get("voucher_id")
            )
            print(f"  write {action.kind} {ident} ({action.gate_decision})")
    if record.escalation:
        print(f"  escalation {record.escalation.get('id')} {record.escalation.get('reason')}")
    for item in record.human_follow_up:
        print(f"  follow-up: {item}")
    print(f"  openai {_format_run_usage(record.model, record.token_usage)}")
    return 0


def run_all(settings: Settings) -> int:
    cases = discover_cases()
    if not cases:
        print("No cases found.", file=sys.stderr)
        return 1
    code = 0
    for path in cases:
        print(f"=== {path.name} ===")
        code = code or run_one(path, settings)
    print()
    show_usage(settings, as_json=False)
    return code


def show_usage(settings: Settings, *, as_json: bool) -> int:
    report = collect_report(settings.output_dir)
    if as_json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0
    print(format_report(report))
    return 0


def _record_usage(output_dir: Path, case_id: str, model: str, usage: dict) -> None:
    prompt = int(usage.get("prompt_tokens") or 0)
    completion = int(usage.get("completion_tokens") or 0)
    total = int(usage.get("total_tokens") or 0)
    if prompt == 0 and completion == 0 and total == 0:
        return
    append_ledger(
        output_dir,
        UsageEntry(
            at=utcnow(),
            case_id=case_id,
            model=model or str(usage.get("model") or ""),
            prompt_tokens=prompt,
            completion_tokens=completion,
            total_tokens=total,
            cached_tokens=int(usage.get("cached_tokens") or 0),
            rounds=int(usage.get("rounds") or 0),
            estimated_usd=float(usage.get("estimated_usd") or 0.0),
            rate_key=str(usage.get("rate_key") or ""),
            source="run",
        ),
    )


def _format_run_usage(model: str, usage: dict) -> str:
    rounds = usage.get("rounds") or 0
    usd = float(usage.get("estimated_usd") or 0.0)
    return (
        f"{model or '-'}  {usage.get('prompt_tokens') or 0} in / "
        f"{usage.get('completion_tokens') or 0} out / {usage.get('total_tokens') or 0} tokens  "
        f"{format_usd(usd)}  rounds={rounds}"
    )


def discover_cases() -> list[Path]:
    root = _REPO_ROOT / "cases"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir() and (p / "inbound.txt").exists())
