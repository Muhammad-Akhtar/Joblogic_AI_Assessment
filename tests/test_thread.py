from pathlib import Path

from desk.inbound.intake import load_case
from desk.rules.thread import resolve_thread

ROOT = Path(__file__).resolve().parent.parent


def test_case_10_thread_latest_is_monday_rebook():
    text = load_case(ROOT / "cases/case-10").raw_text
    intent = resolve_thread(text)
    assert intent is not None
    assert intent.rebook is True
    assert intent.refund is False
    assert intent.travel_date == "2026-08-10"


def test_plain_email_is_not_a_thread():
    text = load_case(ROOT / "cases/case-01").raw_text
    assert resolve_thread(text) is None
