from pathlib import Path

from desk.inbound.intake import load_case
from desk.rules.injection import inbound_has_injection

ROOT = Path(__file__).resolve().parent.parent


def test_case_06_forwarded_notice_is_injection():
    text = load_case(ROOT / "cases" / "case-06").raw_text
    assert inbound_has_injection(text)


def test_ordinary_complaint_is_not_injection():
    text = load_case(ROOT / "cases" / "case-05").raw_text
    assert not inbound_has_injection(text)
