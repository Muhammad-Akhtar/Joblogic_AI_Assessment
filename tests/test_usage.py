import json
from pathlib import Path

from desk.usage import (
    append_ledger,
    collect_report,
    estimate_usd,
    format_report,
    rates_for,
    snapshot_from_totals,
)


def test_gpt4o_case01_tokens_match_published_rate():
    # Case-01 live run: 11866 in / 444 out. $2.50 / $10.00 per 1M.
    usd = estimate_usd("gpt-4o", 11866, 444)
    assert round(usd, 4) == 0.0341


def test_gpt4o_mini_is_cheaper_than_gpt4o():
    assert estimate_usd("gpt-4o-mini", 10_000, 1_000) < estimate_usd("gpt-4o", 10_000, 1_000)


def test_dated_model_name_uses_family_rate():
    key, _ = rates_for("gpt-4o-2024-08-06")
    assert key == "gpt-4o"
    mini, _ = rates_for("gpt-4o-mini-2024-07-18")
    assert mini == "gpt-4o-mini"


def test_cached_tokens_are_billed_at_the_cached_rate():
    full = estimate_usd("gpt-4o", 1000, 0, cached_tokens=0)
    cached = estimate_usd("gpt-4o", 1000, 0, cached_tokens=1000)
    assert cached < full
    assert cached == round(1000 * 1.25 / 1_000_000, 6)


def test_snapshot_fills_estimated_usd_and_rounds():
    snap = snapshot_from_totals(
        model="gpt-4o",
        prompt_tokens=11866,
        completion_tokens=444,
        total_tokens=12310,
        rounds=8,
    )
    assert snap.rounds == 8
    assert snap.estimated_usd == estimate_usd("gpt-4o", 11866, 444)
    assert snap.rate_key == "gpt-4o"


def test_collect_report_reads_case_records_without_ledger(tmp_path: Path):
    payload = {
        "case_id": "case-01",
        "finished_at": "2026-09-12T10:00:00Z",
        "model": "gpt-4o",
        "token_usage": {
            "prompt_tokens": 11866,
            "completion_tokens": 444,
            "total_tokens": 12310,
        },
    }
    (tmp_path / "case-01.json").write_text(json.dumps(payload), encoding="utf-8")
    report = collect_report(tmp_path)
    assert len(report.entries) == 1
    assert report.entries[0].case_id == "case-01"
    assert report.estimated_usd == estimate_usd("gpt-4o", 11866, 444)
    text = format_report(report)
    assert "case-01" in text
    assert "$0.0341" in text
    assert "admin key" in text.lower() or "recorded usage" in text.lower()


def test_ledger_totals_include_reruns(tmp_path: Path):
    from desk.usage import UsageEntry

    first = UsageEntry(
        at="2026-09-12T10:00:00Z",
        case_id="case-01",
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=10,
        total_tokens=110,
        estimated_usd=estimate_usd("gpt-4o", 100, 10),
        source="run",
    )
    second = UsageEntry(
        at="2026-09-12T11:00:00Z",
        case_id="case-01",
        model="gpt-4o",
        prompt_tokens=100,
        completion_tokens=10,
        total_tokens=110,
        estimated_usd=estimate_usd("gpt-4o", 100, 10),
        source="run",
    )
    append_ledger(tmp_path, first)
    append_ledger(tmp_path, second)
    report = collect_report(tmp_path)
    assert len(report.entries) == 2
    assert report.prompt_tokens == 200
    assert report.estimated_usd == estimate_usd("gpt-4o", 100, 10) * 2
