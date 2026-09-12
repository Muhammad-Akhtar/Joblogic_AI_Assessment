from pathlib import Path

from desk.inbound.intake import infer_requests, load_case

ROOT = Path(__file__).resolve().parent.parent


def test_case_01_loads_raw_text_and_meta():
    case = load_case(ROOT / "cases" / "case-01")
    assert case.case_id == "case-01"
    assert case.channel == "email"
    assert "AER-4K2P9X" in case.raw_text
    assert "Priya Raghunathan" in (case.inbound_from or "")
    assert "Barcelona" in (case.subject or "")


def test_case_01_infers_rebook_and_receipts():
    case = load_case(ROOT / "cases" / "case-01")
    kinds = {r.kind for r in case.inferred_requests}
    assert "rebook" in kinds
    assert "care_receipts" in kinds


def test_infer_requests_from_raw_file(tmp_path: Path):
    inbound = tmp_path / "stray.txt"
    inbound.write_text("Hello\nI want a refund please\n", encoding="utf-8")
    case = load_case(inbound)
    assert case.case_id == "stray"
    assert any(r.kind == "refund" for r in infer_requests(case.raw_text))


def test_case_09_sitting_in_airport_is_not_care_receipts():
    case = load_case(ROOT / "cases" / "case-09")
    kinds = {r.kind for r in case.inferred_requests}
    assert "hotel" in kinds
    assert "rebook" in kinds
    assert "care_receipts" not in kinds
