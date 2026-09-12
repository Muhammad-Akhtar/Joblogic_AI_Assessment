from pathlib import Path

from desk.inbound.intake import load_case
from desk.rules.party import refund_share_gbp, resolve_party_intents

ROOT = Path(__file__).resolve().parent.parent

CASE02_BOOKING = {
    "booking_ref": "AER-7T3M1B",
    "total_paid_gbp": 1487.50,
    "passengers": [
        {"passenger_id": "P1", "given_name": "Chidi", "surname": "Okonkwo", "assistance": None},
        {"passenger_id": "P2", "given_name": "Adaeze", "surname": "Okonkwo", "assistance": None},
        {"passenger_id": "P3", "given_name": "Emeka", "surname": "Okonkwo", "assistance": None},
        {"passenger_id": "P4", "given_name": "Ngozi", "surname": "Okonkwo", "assistance": "WCHR"},
        {"passenger_id": "P5", "given_name": "Tobias", "surname": "Achebe", "assistance": None},
    ],
}


def test_case_02_splits_rebook_refund_and_undecided():
    text = load_case(ROOT / "cases" / "case-02").raw_text
    intents = {i.passenger_id: i for i in resolve_party_intents(text, CASE02_BOOKING)}
    assert intents["P1"].action == "rebook"
    assert intents["P2"].action == "rebook"
    assert intents["P3"].action == "rebook"
    assert intents["P4"].action == "undecided"
    assert intents["P4"].assistance == "WCHR"
    assert intents["P5"].action == "refund"


def test_tobias_refund_is_equal_share_not_whole_booking():
    assert refund_share_gbp(CASE02_BOOKING, ["P5"]) == 297.50


def test_case_02_intake_sees_rebook_refund_and_care():
    case = load_case(ROOT / "cases" / "case-02")
    kinds = {r.kind for r in case.inferred_requests}
    assert "rebook" in kinds
    assert "refund" in kinds
    assert "care_receipts" in kinds


def test_case_03_intake_is_compensation_not_rebook():
    case = load_case(ROOT / "cases" / "case-03")
    kinds = {r.kind for r in case.inferred_requests}
    assert "compensation" in kinds
    assert "rebook" not in kinds


def test_single_pax_compensation_email_does_not_invent_a_rebook():
    booking = {
        "booking_ref": "AER-9L5D2R",
        "passengers": [
            {"passenger_id": "P1", "given_name": "Marta", "surname": "Kowalczyk", "cabin_flown": None},
        ],
    }
    text = load_case(ROOT / "cases" / "case-05").raw_text
    intents = resolve_party_intents(text, booking)
    assert intents == []


def test_already_flown_pax_is_not_auto_rebooked():
    booking = {
        "booking_ref": "AER-2Q8W4N",
        "passengers": [
            {
                "passenger_id": "P1",
                "given_name": "Daniel",
                "surname": "Fitzgerald",
                "cabin_flown": "ECONOMY",
            },
        ],
    }
    text = load_case(ROOT / "cases" / "case-06").raw_text
    intents = resolve_party_intents(text, booking)
    assert intents == []


def test_case_12_spanish_rebook_covers_both_passengers():
    booking = {
        "booking_ref": "AER-1F6G8P",
        "passengers": [
            {"passenger_id": "P1", "given_name": "Lucia", "surname": "Marquez-Ibanez"},
            {"passenger_id": "P2", "given_name": "Mateo", "surname": "Marquez-Ibanez"},
        ],
    }
    text = load_case(ROOT / "cases" / "case-12").raw_text
    intents = {i.passenger_id: i for i in resolve_party_intents(text, booking)}
    assert intents["P1"].action == "rebook"
    assert intents["P2"].action == "rebook"
