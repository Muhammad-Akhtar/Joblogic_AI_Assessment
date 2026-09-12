from __future__ import annotations

from typing import Any

from desk.inbound.intake import InboundCase
from desk.domain.models import (
    DisruptionFacts,
    EntitlementSummary,
    IdentityAssessment,
    PassengerRequest,
    ProposedAction,
    SourceRef,
    WriteProposal,
)
from desk.ops.types import AvailabilityOption, BookingRecord
from desk.rules.identity import ContactHints, SearchHit


class CaseSession:
    """In-process facts the model cannot overwrite. The write gate reads this, not the prompt."""

    def __init__(self, inbound: InboundCase, hints: ContactHints):
        self.inbound = inbound
        self.hints = hints
        self.identity = IdentityAssessment(status="unconfirmed", notes="Not yet assessed.")
        self.search_hits: list[SearchHit] = []
        self.booking: dict[str, Any] | None = None
        self.booking_record: BookingRecord | None = None
        self.flight: dict[str, Any] | None = None
        self.disruption: DisruptionFacts | None = None
        self.entitlements: EntitlementSummary | None = None
        self.customer: dict[str, Any] | None = None
        self.options: dict[str, AvailabilityOption] = {}
        self.hotel_checks: dict[str, dict[str, Any]] = {}
        self.sources: list[SourceRef] = []
        self.proposals: list[WriteProposal] = []
        self.actions: list[ProposedAction] = []
        self.passenger_requests: list[PassengerRequest] = list(inbound.inferred_requests)
        self.recommendation: str = ""
        self.uncertainty: list[str] = []
        self.human_follow_up: list[str] = []
        self.token_usage: dict[str, Any] = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cached_tokens": 0,
            "rounds": 0,
            "estimated_usd": 0.0,
            "model": "",
            "rate_key": "",
        }
        self.model: str = ""
        self.finished: bool = False

    @property
    def booking_ref(self) -> str | None:
        if self.identity.booking_ref:
            return self.identity.booking_ref
        if self.booking:
            return str(self.booking.get("booking_ref") or "").upper() or None
        return None

    def add_source(self, method: str, path: str, note: str = "") -> None:
        self.sources.append(SourceRef(method=method, path=path, note=note))

    def add_search_hits(self, hits: list[SearchHit]) -> None:
        known = {h.booking_ref for h in self.search_hits}
        for hit in hits:
            if hit.booking_ref not in known:
                self.search_hits.append(hit)
                known.add(hit.booking_ref)

    def remember_options(self, rows: list[dict[str, Any]], *, partners: bool = False) -> None:
        for row in rows:
            option = AvailabilityOption.model_validate(row)
            option.partners = partners
            self.options[option.option_id] = option

    def eligible_rebook_options(self) -> list[AvailabilityOption]:
        booked_cabin = self._booked_cabin()
        out = []
        for opt in self.options.values():
            if opt.seats_available <= 0:
                continue
            if opt.fare_gbp != 0:
                continue
            if opt.partners:
                continue
            if booked_cabin and opt.cabin != booked_cabin:
                continue
            out.append(opt)
        out.sort(key=lambda o: (o.date, o.departure_local, o.arrival_local))
        return out

    def _booked_cabin(self) -> str | None:
        if not self.booking:
            return None
        passengers = self.booking.get("passengers") or []
        if not passengers:
            return None
        return passengers[0].get("cabin_booked")

    def passenger_ids_on_booking(self) -> set[str]:
        if not self.booking:
            return set()
        return {p["passenger_id"] for p in self.booking.get("passengers") or []}

    def add_usage(
        self,
        prompt: int,
        completion: int,
        total: int,
        cached: int = 0,
    ) -> None:
        from desk.usage import snapshot_from_totals

        self.token_usage["prompt_tokens"] += prompt
        self.token_usage["completion_tokens"] += completion
        self.token_usage["total_tokens"] += total
        self.token_usage["cached_tokens"] += cached
        self.token_usage["rounds"] = int(self.token_usage.get("rounds") or 0) + 1
        snap = snapshot_from_totals(
            model=self.model,
            prompt_tokens=int(self.token_usage["prompt_tokens"]),
            completion_tokens=int(self.token_usage["completion_tokens"]),
            total_tokens=int(self.token_usage["total_tokens"]),
            cached_tokens=int(self.token_usage["cached_tokens"]),
            rounds=int(self.token_usage["rounds"]),
        )
        self.token_usage.update(snap.as_dict())
