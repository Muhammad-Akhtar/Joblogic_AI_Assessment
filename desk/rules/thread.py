from __future__ import annotations

import re
from dataclasses import dataclass

from desk.domain.models import PassengerRequest

_THREAD_MARKERS = (
    "forwarded conversation",
    "oldest first",
    "action the latest",
    "action the most recent",
    "please read to the end",
)
_REBOOK = (
    "put me on",
    "rebook",
    "next available",
    "earliest",
    "need to get",
    "still need to get",
    "get back",
    "necesito llegar",
)
_REFUND = ("refund me", "refund", "cancel the whole booking", "money back")
_WITHDRAW_REFUND = (
    "disregard the refund",
    "do not refund",
    "don't refund",
    "do not refund the booking",
    "no refund will be issued",
    "refund request has been withdrawn",
)
_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


@dataclass
class ThreadIntent:
    rebook: bool = False
    refund: bool = False
    travel_date: str | None = None
    note: str = ""


def looks_like_thread(text: str) -> bool:
    lower = text.lower()
    if any(marker in lower for marker in _THREAD_MARKERS):
        return True
    return lower.count("from:") >= 4


def resolve_thread(text: str) -> ThreadIntent | None:
    """§15.2: the latest passenger ask wins. Earlier refund/rebook elections are withdrawn."""
    if not looks_like_thread(text):
        return None
    intent = ThreadIntent(note="Thread latest-wins (S15.2).")
    year = _year_in(text) or 2026
    for chunk in _passenger_chunks(text):
        lower = chunk.lower()
        if any(tok in lower for tok in _WITHDRAW_REFUND):
            intent.refund = False
        elif any(tok in lower for tok in _REFUND):
            intent.refund = True
            intent.rebook = False
        if any(tok in lower for tok in _REBOOK):
            intent.rebook = True
        date = _travel_date(chunk, default_year=year)
        if date:
            intent.travel_date = date
    if not intent.rebook and not intent.refund:
        return None
    return intent


def apply_latest_wins(requests: list[PassengerRequest], text: str) -> list[PassengerRequest]:
    resolved = resolve_thread(text)
    if resolved is None:
        return requests

    out: list[PassengerRequest] = []
    for req in requests:
        if req.kind == "refund" and resolved.rebook and not resolved.refund:
            out.append(
                req.model_copy(
                    update={
                        "superseded": True,
                        "summary": req.summary + " Superseded by a later message (S15.2).",
                    }
                )
            )
            continue
        if req.kind == "rebook" and resolved.refund and not resolved.rebook:
            out.append(
                req.model_copy(
                    update={
                        "superseded": True,
                        "summary": req.summary + " Superseded by a later message (S15.2).",
                    }
                )
            )
            continue
        if req.kind == "rebook" and resolved.travel_date:
            out.append(
                req.model_copy(
                    update={
                        "summary": (
                            f"Latest ask: rebook onto the earliest suitable service "
                            f"on {resolved.travel_date}."
                        )
                    }
                )
            )
            continue
        out.append(req)

    active = {r.kind for r in out if not r.superseded}
    if resolved.rebook and "rebook" not in active:
        summary = "Passenger's latest message asks to travel."
        if resolved.travel_date:
            summary = f"Latest ask: rebook on {resolved.travel_date}."
        out.append(PassengerRequest(kind="rebook", summary=summary))
    if resolved.refund and "refund" not in active:
        out.append(PassengerRequest(kind="refund", summary="Latest ask: refund the booking."))
    return out


def _passenger_chunks(text: str) -> list[str]:
    parts = re.split(r"\n\s*-{8,}\s*\n", text)
    chunks: list[str] = []
    for part in parts:
        match = re.search(r"^[\s>]*From:\s*(.+)$", part, re.MULTILINE | re.IGNORECASE)
        if not match:
            continue
        who = match.group(1).lower()
        if "aerlink" in who:
            continue
        chunks.append(part)
    return chunks


def _year_in(text: str) -> int | None:
    years = [int(y) for y in re.findall(r"\b(20\d{2})\b", text)]
    return years[-1] if years else None


def _travel_date(text: str, *, default_year: int) -> str | None:
    iso = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    named = re.search(
        r"(?:(?:mon|tues|wednes|thurs|fri|satur|sun)day\s+)?"
        r"(\d{1,2})\s+"
        r"(january|february|march|april|may|june|july|august|september|october|november|december)"
        r"(?:\s+(20\d{2}))?",
        text,
        re.IGNORECASE,
    )
    if not named:
        return None
    day = int(named.group(1))
    month = _MONTHS[named.group(2).lower()]
    year = int(named.group(3)) if named.group(3) else default_year
    return f"{year:04d}-{month:02d}-{day:02d}"
