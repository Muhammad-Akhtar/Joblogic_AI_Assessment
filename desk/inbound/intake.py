from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field

from desk.domain.models import PassengerRequest
from desk.rules.thread import apply_latest_wins

_REBOOK_HINTS = (
    "next available",
    "put me on",
    "rebook",
    "another flight",
    "earliest",
    "need to get to",
    "still need to get",
    "want to get to",
    "need to be on",
    "tomorrow's flight",
    "tomorrows flight",
    "necesito llegar",
    "proximo vuelo",
    "próximo vuelo",
    "cual es el proximo",
    "cuál es el próximo",
)
_REFUND_HINTS = ("refund", "money back", "cancel the whole booking", "not travelling")
_COMP_HINTS = (
    "compensation",
    "compensacion",
    "compensación",
    "what i'm owed",
    "what i am owed",
    "i am owed",
    "whatever i am owed",
    "pay me",
    "i want £",
    "i want gbp",
    "derecho a alguna",
)
_HOTEL_HINTS = (
    "somewhere to stay",
    "somewhere to sleep",
    "nowhere to sleep",
    "sleep tonight",
    "sleep here",
    "need somewhere to stay",
)
_OWN_HOTEL_HINTS = (
    "booked my own hotel",
    "i booked my own",
    "own hotel",
    "hotel and it cost",
)
_RECEIPT_HINTS = ("receipt", "breakfast", "coffee", "coffees")
_CARE_HINTS = ("offered us a drink", "not offered", "nobody at the desk")
_LOST_PROPERTY_HINTS = ("overcoat", "left a", "my coat", "lost property")


class InboundCase(BaseModel):
    case_id: str
    raw_text: str
    channel: str | None = None
    received_at: str | None = None
    inbound_from: str | None = None
    subject: str | None = None
    source_path: str = ""
    inferred_requests: list[PassengerRequest] = Field(default_factory=list)


def load_case(path: str | Path) -> InboundCase:
    """Load a case directory (`inbound.txt` + optional `meta.json`) or a raw inbound file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No case at {p}")

    if p.is_dir():
        inbound_path = p / "inbound.txt"
        meta_path = p / "meta.json"
        if not inbound_path.exists():
            raise FileNotFoundError(f"No inbound.txt in {p}")
        raw = inbound_path.read_text(encoding="utf-8")
        meta: dict = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        case_id = str(meta.get("case_id") or p.name)
        return InboundCase(
            case_id=case_id,
            raw_text=raw,
            channel=meta.get("channel"),
            received_at=meta.get("received_at"),
            inbound_from=meta.get("from"),
            subject=meta.get("subject"),
            source_path=str(p),
            inferred_requests=infer_requests(raw),
        )

    raw = p.read_text(encoding="utf-8")
    return InboundCase(
        case_id=p.stem,
        raw_text=raw,
        inbound_from=_from_header(raw),
        subject=_subject_header(raw),
        source_path=str(p),
        inferred_requests=infer_requests(raw),
    )


def infer_requests(text: str) -> list[PassengerRequest]:
    """Cheap keyword pass. The model may refine; the gate only actions non-superseded asks."""
    lower = text.lower()
    found: list[PassengerRequest] = []

    def add(kind: str, summary: str) -> None:
        if any(r.kind == kind for r in found):
            return
        found.append(PassengerRequest(kind=kind, summary=summary))  # type: ignore[arg-type]

    if any(h in lower for h in _REBOOK_HINTS):
        add("rebook", "Passenger asked to be placed on another flight.")
    if any(h in lower for h in _REFUND_HINTS):
        add("refund", "Passenger asked for a refund.")
    if any(h in lower for h in _COMP_HINTS):
        add("compensation", "Passenger asked what they are owed / for compensation.")
    own_hotel = any(h in lower for h in _OWN_HOTEL_HINTS)
    if any(h in lower for h in _HOTEL_HINTS) and not own_hotel:
        add("hotel", "Passenger asked for overnight accommodation.")
    if own_hotel or any(h in lower for h in _RECEIPT_HINTS) or any(h in lower for h in _CARE_HINTS):
        add("care_receipts", "Passenger mentions duty-of-care meals, wait, or own-arranged receipts.")
    if any(h in lower for h in _LOST_PROPERTY_HINTS):
        add("lost_property", "Passenger reported lost property. Not a disruption write.")
    return apply_latest_wins(found, text)


def _from_header(raw: str) -> str | None:
    m = re.search(r"^From:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None


def _subject_header(raw: str) -> str | None:
    m = re.search(r"^Subject:\s*(.+)$", raw, re.MULTILINE | re.IGNORECASE)
    return m.group(1).strip() if m else None
