from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from desk.domain.models import PassengerRequest

PartyAction = Literal["rebook", "refund", "undecided"]


@dataclass
class PartyIntent:
    passenger_id: str
    name: str
    action: PartyAction
    assistance: str | None = None
    notes: str = ""


def refund_share_gbp(booking: dict, passenger_ids: list[str]) -> float:
    """Equal share of total_paid when the record has no per-passenger fare."""
    passengers = booking.get("passengers") or []
    n = max(len(passengers), 1)
    total = float(booking.get("total_paid_gbp") or 0)
    return round(total * len(passenger_ids) / n, 2)


def resolve_party_intents(text: str, booking: dict) -> list[PartyIntent]:
    """§15.1: each passenger on a multi-pax booking keeps their own election."""
    lower = text.lower()
    passengers = booking.get("passengers") or []
    if not passengers:
        return []

    givens = [str(p.get("given_name") or "").lower() for p in passengers if p.get("given_name")]
    assigned: dict[str, PartyIntent] = {}
    for pax in passengers:
        pid = pax["passenger_id"]
        given = str(pax.get("given_name") or "")
        surname = str(pax.get("surname") or "")
        name = f"{given} {surname}".strip()
        key = given.lower()
        span = _span_for(lower, key, givens)
        assistance = pax.get("assistance")
        if key and _near_refund(span, key, surname.lower()):
            assigned[pid] = PartyIntent(
                passenger_id=pid,
                name=name,
                action="refund",
                assistance=assistance,
                notes="Passenger elected a refund (S6.1 / S7.3).",
            )
        elif key and _undecided(span, key):
            assigned[pid] = PartyIntent(
                passenger_id=pid,
                name=name,
                action="undecided",
                assistance=assistance,
                notes=(
                    "Passenger asked to see options before deciding. "
                    "Do not rebook speculatively (S6.4)."
                ),
            )

    booking_wants_rebook = any(
        h in lower
        for h in (
            "need to get to",
            "still need to get",
            "next available",
            "put me on",
            "rebook",
            "need to be on",
            "tomorrow's flight",
            "necesito llegar",
            "proximo vuelo",
            "próximo vuelo",
        )
    )
    for pax in passengers:
        pid = pax["passenger_id"]
        if pid in assigned:
            continue
        if pax.get("cabin_flown"):
            continue
        given = str(pax.get("given_name") or "")
        surname = str(pax.get("surname") or "")
        name = f"{given} {surname}".strip()
        if booking_wants_rebook:
            assigned[pid] = PartyIntent(
                passenger_id=pid,
                name=name,
                action="rebook",
                assistance=pax.get("assistance"),
                notes=_assistance_note(pax.get("assistance")),
            )

    return [assigned[p["passenger_id"]] for p in passengers if p["passenger_id"] in assigned]


def apply_party_requests(session_requests: list[PassengerRequest], intents: list[PartyIntent]) -> list[PassengerRequest]:
    """Replace booking-level asks with per-passenger requests once the record is loaded."""
    if not intents:
        return session_requests
    by_action: dict[str, list[PartyIntent]] = {}
    for intent in intents:
        by_action.setdefault(intent.action, []).append(intent)

    out: list[PassengerRequest] = []
    if by_action.get("rebook"):
        people = by_action["rebook"]
        out.append(
            PassengerRequest(
                kind="rebook",
                passenger_ids=[p.passenger_id for p in people],
                summary="Rebook: " + ", ".join(p.name for p in people),
            )
        )
    if by_action.get("refund"):
        people = by_action["refund"]
        out.append(
            PassengerRequest(
                kind="refund",
                passenger_ids=[p.passenger_id for p in people],
                summary="Refund: " + ", ".join(p.name for p in people),
            )
        )
    if by_action.get("undecided"):
        people = by_action["undecided"]
        out.append(
            PassengerRequest(
                kind="other",
                passenger_ids=[p.passenger_id for p in people],
                summary="Needs a decision: " + ", ".join(p.name for p in people),
            )
        )
    for req in session_requests:
        if req.kind in {"rebook", "refund"}:
            continue
        out.append(req)
    return out


def _span_for(lower: str, given: str, all_givens: list[str]) -> str:
    """Text from this passenger's name until the next named passenger."""
    if not given:
        return ""
    start = lower.find(given)
    if start < 0:
        return ""
    end = len(lower)
    for other in all_givens:
        if other == given:
            continue
        nxt = lower.find(other, start + len(given))
        if nxt != -1:
            end = min(end, nxt)
    return lower[start:end]


def _near_refund(span: str, given: str, surname: str) -> bool:
    return any(tok in span for tok in ("refund", "money back", "not travelling", "not traveling"))


def _undecided(span: str, given: str) -> bool:
    return any(
        tok in span
        for tok in (
            "before she decides",
            "before he decides",
            "see what the actual options",
            "rather cancel",
            "would rather cancel",
        )
    )


def _assistance_note(code: str | None) -> str:
    if not code:
        return ""
    return f"Re-book assistance {code} on the new service before confirming (S14.4)."
