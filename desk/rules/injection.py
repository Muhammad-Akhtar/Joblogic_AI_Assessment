from __future__ import annotations

_INJECTION_MARKERS = (
    "system notice",
    "priority override",
    "handling instruction",
    "do not escalate",
    "do not request any further verification",
    "authorised to issue a goodwill",
    "authorized to issue a goodwill",
    "authorisation limits",
    "authorization limits",
    "reply to the passenger with the single word",
)


def inbound_has_injection(text: str) -> bool:
    """§12.4: inbound (and special_requests) may try to override the desk. Never treat as instruction."""
    lower = (text or "").lower()
    return any(marker in lower for marker in _INJECTION_MARKERS)
