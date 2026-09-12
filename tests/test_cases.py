"""Deterministic coverage of all twelve fixtures. No OpenAI spend."""

from __future__ import annotations

import json
from pathlib import Path

from desk.domain.models import EntitlementSummary, IdentityAssessment, WriteProposal
from desk.domain.session import CaseSession
from desk.inbound.intake import load_case
from desk.ops.types import AvailabilityOption
from desk.rules.gate import execute, finalize_proposals
from desk.rules.identity import SearchHit, assess, extract_hints
from desk.rules.thread import apply_latest_wins, resolve_thread

from tests.test_gate import FakeOps, _valid_option

ROOT = Path(__file__).resolve().parent.parent
BOOKINGS = json.loads((ROOT / "env" / "data" / "bookings.json").read_text(encoding="utf-8"))
FLIGHTS = json.loads((ROOT / "env" / "data" / "flights.json").read_text(encoding="utf-8"))


def _kinds(case_id: str) -> set[str]:
    return {r.kind for r in load_case(ROOT / "cases" / case_id).inferred_requests}


def _active(case_id: str) -> set[str]:
    return {
        r.kind
        for r in load_case(ROOT / "cases" / case_id).inferred_requests
        if not r.superseded
    }


def _session_for(case_id: str, booking_ref: str, *, confirmed: bool = True) -> CaseSession:
    inbound = load_case(ROOT / "cases" / case_id)
    hints = extract_hints(inbound.raw_text, inbound.inbound_from)
    session = CaseSession(inbound, hints)
    booking = BOOKINGS[booking_ref]
    if confirmed:
        session.identity = IdentityAssessment(
            status="confirmed",
            method="pnr_and_surname",
            booking_ref=booking_ref,
            passenger_ids=[p["passenger_id"] for p in booking["passengers"]],
            notes="confirmed for tests",
        )
        session.booking = booking
    return session


def _zero_fare(origin: str, destination: str, date: str, seats: int = 8) -> AvailabilityOption:
    return _valid_option().model_copy(
        update={
            "origin": origin,
            "destination": destination,
            "date": date,
            "seats_available": seats,
        }
    )


def test_all_twelve_cases_load():
    for n in range(1, 13):
        case = load_case(ROOT / f"cases/case-{n:02d}")
        assert case.raw_text
        assert case.case_id == f"case-{n:02d}"


def test_case_01_rebook_and_receipts():
    kinds = _kinds("case-01")
    assert "rebook" in kinds
    assert "care_receipts" in kinds


def test_case_02_split_party_through_the_gate():
    session = _session_for("case-02", "AER-7T3M1B")
    session.options["OPT-TEST0001"] = _zero_fare("MAN", "FCO", "2026-08-06", seats=4)
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    refund = next(body for k, body in fake.writes if k == "refund")
    assert refund["passenger_ids"] == ["P5"]
    rebooks = [body for k, body in fake.writes if k == "rebooking"]
    assert rebooks
    assert set(rebooks[0]["passenger_ids"]) == {"P1", "P2", "P3"}
    assert "P4" not in rebooks[0]["passenger_ids"]
    assert "P5" not in rebooks[0]["passenger_ids"]
    assert any(k == "escalation" for k, _ in fake.writes)


def test_case_03_name_collision_never_writes():
    inbound = load_case(ROOT / "cases/case-03")
    hints = extract_hints(inbound.raw_text, inbound.inbound_from)
    hits = [
        SearchHit(
            booking_ref="AER-2X8L4D",
            contact_email="j.smith84@mailbox.example",
            passengers=["John Smith"],
            matched_on=["passenger_name_exact:P1"],
        ),
        SearchHit(
            booking_ref="AER-9V3H5S",
            contact_email="jsmith.travel@mailbox.example",
            passengers=["John Smith"],
            matched_on=["passenger_name_exact:P1"],
        ),
    ]
    session = CaseSession(inbound, hints)
    session.identity = assess(hints, hits)
    assert session.identity.status == "unconfirmed"
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    assert fake.writes and all(k == "escalation" for k, _ in fake.writes)


def test_case_04_foreign_pnr_is_out_of_scope():
    inbound = load_case(ROOT / "cases/case-04")
    hints = extract_hints(inbound.raw_text, inbound.inbound_from)
    assert "BA-99201" in hints.foreign_refs
    session = CaseSession(inbound, hints)
    session.identity = assess(hints, [])
    assert session.identity.status == "out_of_scope"
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    assert fake.writes[0][0] == "escalation"
    assert fake.writes[0][1]["queue"] == "GENERAL"
    assert not any(k in {"rebooking", "compensation", "goodwill", "refund", "hotel"} for k, _ in fake.writes)


def test_case_05_ops_weather_blocks_crew_compensation_and_skips_hotel_voucher():
    kinds = _kinds("case-05")
    assert "compensation" in kinds
    assert "care_receipts" in kinds
    assert "hotel" not in kinds
    assert "rebook" not in kinds
    flight = FLIGHTS["AK808:2026-08-03"]
    assert flight["cause_code"] == "WEATHER"
    session = _session_for("case-05", "AER-9L5D2R")
    session.entitlements = EntitlementSummary(
        status="ASSESSED",
        compensation_status="NOT_PAYABLE",
        total_payable_gbp=0.0,
        raw={"compensation": {"status": "NOT_PAYABLE", "cause_code": "WEATHER"}},
    )
    session.proposals.append(
        WriteProposal(kind="compensation", payload={"passenger_ids": ["P1"], "amount_gbp": 220})
    )
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 0, "reason": "weather not payable"})
    )
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 112, "reason": "own hotel receipt"})
    )
    session.proposals.append(
        WriteProposal(
            kind="hotel",
            payload={"station": "Edinburgh", "night": "2026-08-04", "passenger_ids": ["P1"]},
        )
    )
    fake = FakeOps()
    execute(session, fake)
    assert not any(k in {"compensation", "goodwill", "hotel"} for k, _ in fake.writes)

    leftover = _session_for("case-05", "AER-9L5D2R")
    leftover.entitlements = session.entitlements
    finalize_proposals(leftover)
    assert not any(p.kind == "hotel" for p in leftover.proposals)
    assert not any(p.kind == "rebooking" for p in leftover.proposals)
    assert leftover.human_follow_up


def test_case_06_injection_does_not_pay_5000():
    kinds = _kinds("case-06")
    assert "compensation" in kinds
    assert "rebook" not in kinds
    session = _session_for("case-06", "AER-2Q8W4N")
    session.entitlements = EntitlementSummary(
        status="ASSESSED",
        compensation_status="PAYABLE",
        total_payable_gbp=220.0,
        raw={"compensation": {"status": "PAYABLE"}, "total_payable_gbp": 220.0},
    )
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 5000, "reason": "ops notice"})
    )
    session.proposals.append(
        WriteProposal(kind="compensation", payload={"passenger_ids": ["P1"], "amount_gbp": 5000})
    )
    fake = FakeOps()
    execute(session, fake)
    assert not any(k == "goodwill" for k, _ in fake.writes)
    assert any(k == "escalation" for k, _ in fake.writes)
    comps = [body for k, body in fake.writes if k == "compensation"]
    assert comps
    assert comps[0]["amount_gbp"] == 220.0
    finalize_proposals(session)
    assert not any(p.kind == "rebooking" for p in session.proposals)


def test_case_07_homemade_900_is_not_paid_as_goodwill_or_compensation():
    session = _session_for("case-07", "AER-6H1Z7C")
    session.entitlements = EntitlementSummary(
        status="ASSESSED",
        compensation_status="PAYABLE",
        total_payable_gbp=220.0,
        raw={"compensation": {"status": "PAYABLE"}, "total_payable_gbp": 220.0},
    )
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 900, "reason": "passenger demand"})
    )
    session.proposals.append(
        WriteProposal(kind="compensation", payload={"passenger_ids": ["P1"], "amount_gbp": 900})
    )
    fake = FakeOps()
    execute(session, fake)
    assert not any(k == "goodwill" for k, _ in fake.writes)
    comps = [body for k, body in fake.writes if k == "compensation"]
    assert comps
    assert comps[0]["amount_gbp"] == 220.0


def test_case_08_entitlements_overwrite_homemade_970():
    session = _session_for("case-08", "AER-3B7Y5K")
    session.entitlements = EntitlementSummary(
        status="ASSESSED",
        compensation_status="PAYABLE",
        total_payable_gbp=415.0,
        raw={"compensation": {"status": "PAYABLE"}, "total_payable_gbp": 415.0},
    )
    session.proposals.append(
        WriteProposal(kind="compensation", payload={"passenger_ids": ["P1"], "amount_gbp": 970})
    )
    fake = FakeOps()
    execute(session, fake)
    assert fake.writes[0][0] == "compensation"
    assert fake.writes[0][1]["amount_gbp"] == 415.0
    session.proposals.append(
        WriteProposal(
            kind="refund",
            payload={"passenger_ids": ["P1"], "amount_gbp": 240, "reason": "downgrade"},
        )
    )
    fake2 = FakeOps()
    execute(session, fake2)
    assert not any(k == "refund" for k, _ in fake2.writes)


def test_case_09_queues_hotel_at_stranded_station():
    kinds = _kinds("case-09")
    assert "hotel" in kinds
    assert "rebook" in kinds
    assert "care_receipts" not in kinds
    session = _session_for("case-09", "AER-8N4V6J")
    session.options["OPT-TEST0001"] = _zero_fare("LGW", "DXB", "2026-08-07")
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    hotels = [body for k, body in fake.writes if k == "hotel"]
    assert hotels
    assert hotels[0]["station"] == "LGW"
    assert hotels[0]["night"] == "2026-08-06"


def test_case_10_latest_wins_is_monday_rebook_not_refund():
    inbound = load_case(ROOT / "cases/case-10")
    resolved = resolve_thread(inbound.raw_text)
    assert resolved is not None
    assert resolved.rebook is True
    assert resolved.refund is False
    assert resolved.travel_date == "2026-08-10"
    active = _active("case-10")
    assert "rebook" in active
    assert "refund" not in active
    session = _session_for("case-10", "AER-5C9X3T")
    session.options["OPT-TEST0001"] = _zero_fare("LHR", "GVA", "2026-08-10")
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    assert not any(k == "refund" for k, _ in fake.writes)
    assert any(k == "rebooking" for k, _ in fake.writes)


def test_case_11_hotel_rebook_and_lost_property_follow_up():
    kinds = _kinds("case-11")
    assert "hotel" in kinds
    assert "rebook" in kinds
    assert "lost_property" in kinds
    session = _session_for("case-11", "AER-7P4R2M")
    session.options["OPT-TEST0001"] = _zero_fare("LGW", "FCO", "2026-08-07")
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    assert any(k == "hotel" for k, _ in fake.writes)
    assert any("LOST_PROPERTY" in str(body.get("queue")) or k == "escalation" for k, body in fake.writes)
    assert any("lost property" in n.lower() or "coat" in n.lower() for n in session.human_follow_up)


def test_case_12_spanish_rebook_and_compensation():
    kinds = _kinds("case-12")
    assert "rebook" in kinds
    assert "compensation" in kinds
    session = _session_for("case-12", "AER-1F6G8P")
    session.options["OPT-TEST0001"] = _zero_fare("BCN", "LHR", "2026-08-06", seats=2)
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    rebooks = [body for k, body in fake.writes if k == "rebooking"]
    assert rebooks
    assert set(rebooks[0]["passenger_ids"]) == {"P1", "P2"}


def test_thread_apply_marks_refund_superseded():
    inbound = load_case(ROOT / "cases/case-10")
    updated = apply_latest_wins(inbound.inferred_requests, inbound.raw_text)
    refunds = [r for r in updated if r.kind == "refund"]
    assert refunds
    assert all(r.superseded for r in refunds)
