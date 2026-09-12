from __future__ import annotations

import re
from dataclasses import dataclass, field

from desk.domain.models import IdentityAssessment

PNR_RE = re.compile(r"\b(AER-[A-Z0-9]{6})\b", re.IGNORECASE)
FOREIGN_PNR_RE = re.compile(r"\b([A-Z]{2}-\d{4,})\b")
EMAIL_RE = re.compile(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.IGNORECASE)
FROM_RE = re.compile(r"([^<]+)<([^>]+)>")


@dataclass
class ContactHints:
    emails: list[str] = field(default_factory=list)
    phones: list[str] = field(default_factory=list)
    pnrs: list[str] = field(default_factory=list)
    foreign_refs: list[str] = field(default_factory=list)
    surnames: list[str] = field(default_factory=list)
    full_names: list[str] = field(default_factory=list)


@dataclass
class SearchHit:
    booking_ref: str
    contact_email: str = ""
    contact_phone: str = ""
    passengers: list[str] = field(default_factory=list)
    matched_on: list[str] = field(default_factory=list)
    customer_id: str | None = None
    passenger_ids: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, row: dict) -> "SearchHit":
        return cls(
            booking_ref=str(row.get("booking_ref", "")).upper(),
            contact_email=str(row.get("contact_email") or ""),
            contact_phone=str(row.get("contact_phone") or ""),
            passengers=list(row.get("passengers") or []),
            matched_on=list(row.get("matched_on") or []),
            customer_id=row.get("customer_id"),
        )


def extract_hints(raw_text: str, from_header: str | None = None) -> ContactHints:
    emails = [e.lower() for e in EMAIL_RE.findall(raw_text)]
    pnrs = [m.group(1).upper() for m in PNR_RE.finditer(raw_text)]
    foreign = [m.group(1).upper() for m in FOREIGN_PNR_RE.finditer(raw_text)]
    surnames: list[str] = []
    full_names: list[str] = []

    header = from_header or ""
    parsed = FROM_RE.search(header)
    if parsed:
        display = parsed.group(1).strip().strip('"')
        email = parsed.group(2).strip().lower()
        emails.append(email)
        if display:
            full_names.append(display)
            surnames.append(display.split()[-1])
    elif header and "@" in header:
        emails.append(header.strip().lower())

    emails = _unique(emails)
    pnrs = _unique(pnrs)
    phones = _unique(_phones(raw_text))
    return ContactHints(
        emails=emails,
        phones=phones,
        pnrs=pnrs,
        foreign_refs=_unique(foreign),
        surnames=_unique(s.lower() for s in surnames),
        full_names=full_names,
    )


def hits_from_search(payload: dict | list) -> list[SearchHit]:
    rows = payload if isinstance(payload, list) else payload.get("results") or []
    return [SearchHit.from_api(r) for r in rows]


def assess(hints: ContactHints, search_results: list[SearchHit]) -> IdentityAssessment:
    """Apply Passenger Care Policy §2.1 / §2.2. Name similarity is not identity."""
    if not search_results and hints.foreign_refs and not hints.pnrs:
        return IdentityAssessment(
            status="out_of_scope",
            notes=(
                "No Aerlink booking matched. The contact supplied a non-Aerlink "
                f"reference ({', '.join(hints.foreign_refs)}). No action on any booking."
            ),
        )

    if not search_results:
        return IdentityAssessment(
            status="unconfirmed",
            notes="No booking in the operational record matches this contact.",
        )

    candidates: dict[str, tuple[SearchHit, str, list[str]]] = {}

    for pnr in hints.pnrs:
        matches = [h for h in search_results if h.booking_ref == pnr]
        if len(matches) == 1 and _surname_on_booking(hints, matches[0]):
            _add_candidate(candidates, matches[0], "pnr_and_surname", matches[0].matched_on)
        elif len(matches) == 1:
            # PNR exists but surname does not match a named passenger — §2.2
            return IdentityAssessment(
                status="unconfirmed",
                booking_ref=matches[0].booking_ref,
                matched_on=matches[0].matched_on,
                notes=(
                    "Booking reference exists but no passenger surname on that "
                    "booking matches the contact. Partial match is not identity."
                ),
            )

    for email in hints.emails:
        matches = [
            h for h in search_results if h.contact_email.lower() == email
        ]
        if len(matches) == 1:
            _add_candidate(candidates, matches[0], "contact_email_exact", ["contact_email_exact"])
        elif len(matches) > 1:
            return IdentityAssessment(
                status="unconfirmed",
                notes="Contact email matches more than one booking. Identity is not confirmed.",
            )

    for phone in hints.phones:
        matches = [
            h for h in search_results
            if phone and _norm_phone(h.contact_phone) and phone in _norm_phone(h.contact_phone)
        ]
        if len(matches) == 1:
            _add_candidate(candidates, matches[0], "contact_phone_match", ["contact_phone_match"])
        elif len(matches) > 1:
            return IdentityAssessment(
                status="unconfirmed",
                notes="Contact telephone matches more than one booking. Identity is not confirmed.",
            )

    if len(candidates) == 1:
        hit, method, matched_on = next(iter(candidates.values()))
        passenger_ids = hit.passenger_ids or _ids_from_matched_on(hit.matched_on)
        return IdentityAssessment(
            status="confirmed",
            method=method,
            booking_ref=hit.booking_ref,
            passenger_ids=passenger_ids,
            customer_id=hit.customer_id,
            matched_on=_unique(matched_on),
            notes=f"Identity confirmed under §2.1 via {method}.",
        )

    if len(candidates) > 1:
        refs = ", ".join(sorted(candidates))
        return IdentityAssessment(
            status="unconfirmed",
            notes=f"Confirmation methods pointed at different bookings: {refs}.",
        )

    return IdentityAssessment(
        status="unconfirmed",
        notes=(
            "Search returned booking(s) but none met §2.1 (PNR+surname, unique email, "
            "or unique telephone). A name match alone is not identity."
        ),
    )


def refine_with_booking(identity: IdentityAssessment, booking: dict) -> IdentityAssessment:
    """Attach passenger ids / customer id once the full booking record is loaded."""
    if identity.status != "confirmed":
        return identity
    if booking.get("booking_ref", "").upper() != (identity.booking_ref or "").upper():
        return identity
    ids = [p["passenger_id"] for p in booking.get("passengers") or []]
    updated = identity.model_copy(deep=True)
    updated.customer_id = booking.get("customer_id") or identity.customer_id
    if not updated.passenger_ids:
        updated.passenger_ids = ids
    return updated


def _add_candidate(
    bag: dict[str, tuple[SearchHit, str, list[str]]],
    hit: SearchHit,
    method: str,
    matched_on: list[str],
) -> None:
    ref = hit.booking_ref
    if ref not in bag:
        bag[ref] = (hit, method, list(matched_on))
        return
    prev_hit, prev_method, prev_matched = bag[ref]
    bag[ref] = (
        prev_hit,
        f"{prev_method}+{method}",
        _unique(prev_matched + list(matched_on)),
    )


def _surname_on_booking(hints: ContactHints, hit: SearchHit) -> bool:
    surnames = set(hints.surnames)
    for name in hit.passengers:
        parts = name.lower().split()
        if parts and parts[-1] in surnames:
            return True
        if hints.full_names and name.lower() in {n.lower() for n in hints.full_names}:
            return True
    return False


def _ids_from_matched_on(matched_on: list[str]) -> list[str]:
    ids = []
    for item in matched_on:
        if ":" in item:
            ids.append(item.split(":")[-1])
    return _unique(ids)


def _phones(text: str) -> list[str]:
    found = re.findall(r"\+?\d[\d\s\-()]{8,}\d", text)
    return [_norm_phone(p) for p in found if len(_norm_phone(p)) >= 9]


def _norm_phone(s: str) -> str:
    return re.sub(r"[^\d]", "", s or "")


def _unique(items) -> list[str]:
    out: list[str] = []
    for item in items:
        if item and item not in out:
            out.append(item)
    return out
