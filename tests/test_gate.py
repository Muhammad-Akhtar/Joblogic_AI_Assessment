from __future__ import annotations

from typing import Any

from pathlib import Path

from desk.domain.models import EntitlementSummary, IdentityAssessment, WriteProposal
from desk.domain.session import CaseSession
from desk.inbound.intake import InboundCase, load_case
from desk.ops.types import AvailabilityOption
from desk.rules.gate import execute, finalize_proposals
from desk.rules.identity import ContactHints, SearchHit, assess, extract_hints

ROOT = Path(__file__).resolve().parent.parent


class FakeOps:
    def __init__(self, rooms_remaining: int = 1):
        self.writes: list[tuple[str, dict]] = []
        self.rooms_remaining = rooms_remaining
        self.seq = 0

    def _id(self, prefix: str) -> str:
        self.seq += 1
        return f"{prefix}-{self.seq:05d}"

    def create_rebooking(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("rebooking", body))
        return {"rebooking_id": self._id("RBK"), "status": "CONFIRMED", **body}

    def create_compensation(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("compensation", body))
        return {"payment_id": self._id("CMP"), "status": "PAID", **body}

    def create_goodwill(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("goodwill", body))
        return {"payment_id": self._id("GWP"), "status": "PAID", **body}

    def create_refund(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("refund", body))
        return {"refund_id": self._id("RFD"), "status": "ISSUED", **body}

    def create_hotel_voucher(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("hotel", body))
        return {"voucher_id": self._id("HTL"), "status": "ISSUED", **body}

    def create_escalation(self, body: dict[str, Any]) -> dict[str, Any]:
        self.writes.append(("escalation", body))
        return {"escalation_id": self._id("ESC"), "status": "OPEN", **body}

    def get_hotel_allocation(self, station: str, night: str) -> dict[str, Any]:
        return {
            "station": station,
            "night": night,
            "rooms_remaining": self.rooms_remaining,
            "rate_gbp": 165.0,
        }


def _session(*, confirmed: bool = True) -> CaseSession:
    inbound = InboundCase(case_id="t", raw_text="test")
    session = CaseSession(inbound, ContactHints())
    if confirmed:
        session.identity = IdentityAssessment(
            status="confirmed",
            method="pnr_and_surname",
            booking_ref="AER-4K2P9X",
            passenger_ids=["P1"],
            customer_id="CUS-10001",
            notes="confirmed for tests",
        )
        session.booking = {
            "booking_ref": "AER-4K2P9X",
            "passengers": [{"passenger_id": "P1", "cabin_booked": "ECONOMY"}],
        }
    else:
        session.identity = IdentityAssessment(status="unconfirmed", notes="not confirmed")
    return session


def _valid_option() -> AvailabilityOption:
    return AvailabilityOption(
        option_id="OPT-TEST0001",
        flight_no="AK999",
        operated_by="Aerlink",
        origin="LHR",
        destination="BCN",
        date="2026-08-04",
        departure_local="14:00",
        arrival_local="17:10",
        cabin="ECONOMY",
        seats_available=3,
        fare_gbp=0.0,
    )


def test_blocks_write_when_identity_unconfirmed():
    session = _session(confirmed=False)
    session.proposals.append(
        WriteProposal(
            kind="rebooking",
            payload={"option_id": "OPT-TEST0001", "passenger_ids": ["P1"]},
        )
    )
    actions = execute(session, FakeOps())
    assert actions[0].gate_decision == "blocked"
    assert actions[0].result is None


def test_zero_goodwill_is_not_posted():
    session = _session()
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 0, "reason": "nothing to pay"})
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "blocked"
    assert not any(kind == "goodwill" for kind, _ in fake.writes)


def test_receipt_goodwill_is_escalated_not_paid():
    inbound = load_case(ROOT / "cases" / "case-05")
    session = CaseSession(inbound, extract_hints(inbound.raw_text, inbound.inbound_from))
    session.identity = IdentityAssessment(
        status="confirmed",
        method="pnr_and_surname",
        booking_ref="AER-9L5D2R",
        passenger_ids=["P1"],
        notes="confirmed",
    )
    session.booking = {
        "booking_ref": "AER-9L5D2R",
        "passengers": [{"passenger_id": "P1", "cabin_booked": "ECONOMY"}],
        "segments": [
            {"origin": "EDI", "date": "2026-08-03", "is_affected": True},
        ],
    }
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 112, "reason": "hotel receipt"})
    )
    fake = FakeOps()
    execute(session, fake)
    assert not any(kind == "goodwill" for kind, _ in fake.writes)
    assert any(kind == "escalation" for kind, _ in fake.writes)


def test_city_name_hotel_station_normalises_when_passenger_asked_for_voucher():
    session = _session()
    session.passenger_requests = []
    session.booking = {
        "booking_ref": "AER-4K2P9X",
        "passengers": [{"passenger_id": "P1", "cabin_booked": "ECONOMY"}],
        "segments": [{"origin": "LGW", "date": "2026-08-06", "is_affected": True}],
    }
    from desk.domain.models import PassengerRequest

    session.passenger_requests.append(
        PassengerRequest(kind="hotel", summary="need somewhere to stay")
    )
    session.proposals.append(
        WriteProposal(
            kind="hotel",
            payload={"station": "Gatwick", "night": "2026-08-06", "passenger_ids": ["P1"]},
        )
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "allowed"
    assert fake.writes[0][1]["station"] == "LGW"


def test_goodwill_over_150_is_escalated_not_paid():
    session = _session()
    session.proposals.append(
        WriteProposal(kind="goodwill", payload={"amount_gbp": 5000, "reason": "forged notice"})
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "escalated"
    assert fake.writes[0][0] == "escalation"
    assert not any(kind == "goodwill" for kind, _ in fake.writes)


def test_compensation_blocked_when_not_payable():
    session = _session()
    session.entitlements = EntitlementSummary(
        status="ASSESSED",
        compensation_status="NOT_PAYABLE",
        total_payable_gbp=0.0,
        raw={"compensation": {"status": "NOT_PAYABLE"}},
    )
    session.proposals.append(
        WriteProposal(kind="compensation", payload={"passenger_ids": ["P1"], "amount_gbp": 220})
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "blocked"
    assert fake.writes == []


def test_compensation_uses_entitlements_amount_not_model_amount():
    session = _session()
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
    actions = execute(session, fake)
    assert actions[0].gate_decision == "allowed"
    assert actions[0].payload["amount_gbp"] == 415.0
    assert fake.writes[0][1]["amount_gbp"] == 415.0


def test_hotel_blocked_when_allocation_exhausted():
    session = _session()
    session.proposals.append(
        WriteProposal(
            kind="hotel",
            payload={"station": "LGW", "night": "2026-08-06", "passenger_ids": ["P1"]},
        )
    )
    fake = FakeOps(rooms_remaining=0)
    actions = execute(session, fake)
    assert actions[0].gate_decision == "escalated"
    assert not any(kind == "hotel" for kind, _ in fake.writes)


def test_unknown_option_id_is_not_booked():
    session = _session()
    session.proposals.append(
        WriteProposal(
            kind="rebooking",
            payload={"option_id": "OPT-NOT-CACHED", "passenger_ids": ["P1"]},
        )
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision != "allowed"
    assert not any(kind == "rebooking" for kind, _ in fake.writes)


def test_falls_back_to_zero_fare_when_model_picks_paid_option():
    session = _session()
    paid = _valid_option().model_copy(update={"option_id": "OPT-PAID0001", "fare_gbp": 52.24})
    free = _valid_option()
    session.options[paid.option_id] = paid
    session.options[free.option_id] = free
    session.proposals.append(
        WriteProposal(
            kind="rebooking",
            payload={"option_id": "OPT-PAID0001", "passenger_ids": ["P1"]},
        )
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "allowed"
    assert fake.writes[0][1]["option_id"] == "OPT-TEST0001"
    assert fake.writes[0][1]["fare_gbp"] == 0.0


def test_allows_zero_fare_same_cabin_rebook():
    session = _session()
    session.options["OPT-TEST0001"] = _valid_option()
    session.proposals.append(
        WriteProposal(
            kind="rebooking",
            payload={"option_id": "OPT-TEST0001", "passenger_ids": ["P1"]},
        )
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "allowed"
    assert fake.writes[0][0] == "rebooking"
    assert fake.writes[0][1]["option_id"] == "OPT-TEST0001"


def test_rejects_passenger_not_on_booking():
    session = _session()
    session.options["OPT-TEST0001"] = _valid_option()
    session.proposals.append(
        WriteProposal(
            kind="rebooking",
            payload={"option_id": "OPT-TEST0001", "passenger_ids": ["P9"]},
        )
    )
    fake = FakeOps()
    actions = execute(session, fake)
    assert actions[0].gate_decision == "blocked"
    assert fake.writes == []


def test_case_02_finalize_refunds_tobias_and_does_not_rebook_him():
    inbound = load_case(ROOT / "cases" / "case-02")
    session = CaseSession(inbound, extract_hints(inbound.raw_text, inbound.inbound_from))
    session.identity = IdentityAssessment(
        status="confirmed",
        method="pnr_and_surname",
        booking_ref="AER-7T3M1B",
        passenger_ids=["P1"],
        notes="confirmed",
    )
    session.booking = {
        "booking_ref": "AER-7T3M1B",
        "total_paid_gbp": 1487.50,
        "passengers": [
            {"passenger_id": "P1", "given_name": "Chidi", "surname": "Okonkwo", "cabin_booked": "ECONOMY"},
            {"passenger_id": "P2", "given_name": "Adaeze", "surname": "Okonkwo", "cabin_booked": "ECONOMY"},
            {"passenger_id": "P3", "given_name": "Emeka", "surname": "Okonkwo", "cabin_booked": "ECONOMY"},
            {"passenger_id": "P4", "given_name": "Ngozi", "surname": "Okonkwo", "assistance": "WCHR", "cabin_booked": "ECONOMY"},
            {"passenger_id": "P5", "given_name": "Tobias", "surname": "Achebe", "cabin_booked": "ECONOMY"},
        ],
    }
    session.options["OPT-TEST0001"] = _valid_option().model_copy(
        update={"origin": "MAN", "destination": "FCO", "date": "2026-08-06", "seats_available": 4}
    )
    finalize_proposals(session)
    fake = FakeOps()
    execute(session, fake)
    kinds = [k for k, _ in fake.writes]
    assert "refund" in kinds
    refund = next(body for k, body in fake.writes if k == "refund")
    assert refund["passenger_ids"] == ["P5"]
    assert refund["amount_gbp"] == 297.50
    rebooks = [body for k, body in fake.writes if k == "rebooking"]
    if rebooks:
        assert "P5" not in rebooks[0]["passenger_ids"]
        assert "P4" not in rebooks[0]["passenger_ids"]
        assert set(rebooks[0]["passenger_ids"]) == {"P1", "P2", "P3"}
    assert any(k == "escalation" for k in kinds)


def test_case_03_unconfirmed_identity_blocks_every_write():
    inbound = load_case(ROOT / "cases" / "case-03")
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
    assert not any(k in {"rebooking", "compensation", "refund"} for k, _ in fake.writes)
