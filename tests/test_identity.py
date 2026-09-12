from desk.rules.identity import ContactHints, SearchHit, assess, extract_hints


PRIYA = SearchHit(
    booking_ref="AER-4K2P9X",
    contact_email="priya.raghunathan@mailbox.example",
    contact_phone="+447700900112",
    passengers=["Priya Raghunathan"],
    matched_on=["booking_reference_exact"],
    customer_id="CUS-10001",
    passenger_ids=["P1"],
)

SMITH_A = SearchHit(
    booking_ref="AER-2X8L4D",
    contact_email="j.smith84@mailbox.example",
    passengers=["John Smith"],
    matched_on=["passenger_name_exact:P1"],
)
SMITH_B = SearchHit(
    booking_ref="AER-9V3H5S",
    contact_email="jsmith.travel@mailbox.example",
    passengers=["John Smith"],
    matched_on=["passenger_name_exact:P1"],
)


def test_case_01_confirmed_by_pnr_surname_and_email():
    hints = ContactHints(
        emails=["priya.raghunathan@mailbox.example"],
        pnrs=["AER-4K2P9X"],
        surnames=["raghunathan"],
        full_names=["Priya Raghunathan"],
    )
    result = assess(hints, [PRIYA])
    assert result.status == "confirmed"
    assert result.booking_ref == "AER-4K2P9X"
    assert result.method and "pnr_and_surname" in result.method


def test_extract_hints_from_case_01_from_header():
    raw = (
        "From: Priya Raghunathan <priya.raghunathan@mailbox.example>\n"
        "My booking reference is AER-4K2P9X.\n"
    )
    hints = extract_hints(raw, "Priya Raghunathan <priya.raghunathan@mailbox.example>")
    assert "AER-4K2P9X" in hints.pnrs
    assert "priya.raghunathan@mailbox.example" in hints.emails
    assert "raghunathan" in hints.surnames


def test_john_smith_multi_match_is_unconfirmed():
    hints = ContactHints(
        emails=["john.smith.personal@mailbox.example"],
        full_names=["John Smith"],
        surnames=["smith"],
    )
    result = assess(hints, [SMITH_A, SMITH_B])
    assert result.status == "unconfirmed"
    assert result.booking_ref is None


def test_unknown_ba_reference_is_out_of_scope():
    hints = ContactHints(foreign_refs=["BA-99201"])
    result = assess(hints, [])
    assert result.status == "out_of_scope"


def test_name_alone_is_not_identity():
    hints = ContactHints(surnames=["raghunathan"], full_names=["Priya Raghunathan"])
    result = assess(hints, [PRIYA])
    assert result.status == "unconfirmed"
