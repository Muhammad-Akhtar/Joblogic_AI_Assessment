from __future__ import annotations

from typing import Any, Protocol

from desk.domain.models import ProposedAction, WriteProposal
from desk.domain.session import CaseSession
from desk.ops.client import OpsError
from desk.ops.types import AvailabilityOption
from desk.rules.injection import inbound_has_injection
from desk.rules.party import apply_party_requests, refund_share_gbp, resolve_party_intents
from desk.rules.thread import apply_latest_wins

CABIN_RANK = {"ECONOMY": 0, "PREMIUM": 1, "BUSINESS": 2, "FIRST": 3}
GOODWILL_DESK_LIMIT_GBP = 150.0
CANON_QUEUES = {
    "SUPERVISOR",
    "YTP",
    "SPECIAL_ASSISTANCE",
    "OPS_LIAISON",
    "CUSTOMER_CONDUCT",
    "LOST_PROPERTY",
    "GENERAL",
}
STATION_ALIASES = {
    "edi": "EDI",
    "edinburgh": "EDI",
    "lgw": "LGW",
    "gatwick": "LGW",
    "lhr": "LHR",
    "heathrow": "LHR",
    "man": "MAN",
    "manchester": "MAN",
    "bcn": "BCN",
    "barcelona": "BCN",
    "ams": "AMS",
    "amsterdam": "AMS",
    "dub": "DUB",
    "dublin": "DUB",
    "fco": "FCO",
    "rome": "FCO",
    "mad": "MAD",
    "madrid": "MAD",
    "dxb": "DXB",
    "dubai": "DXB",
    "gva": "GVA",
    "geneva": "GVA",
    "lis": "LIS",
    "lisbon": "LIS",
}


class GateClient(Protocol):
    def create_rebooking(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def create_compensation(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def create_goodwill(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def create_refund(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def create_hotel_voucher(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def create_escalation(self, body: dict[str, Any]) -> dict[str, Any]: ...
    def get_hotel_allocation(self, station: str, night: str) -> dict[str, Any]: ...


def finalize_proposals(session: CaseSession) -> None:
    """Deterministic proposals the model may have forgotten. Still go through the gate."""
    session.passenger_requests = apply_latest_wins(
        session.passenger_requests, session.inbound.raw_text
    )
    if session.identity.status != "confirmed":
        if not any(p.kind == "escalation" for p in session.proposals):
            out_of_scope = session.identity.status == "out_of_scope"
            session.proposals.append(
                WriteProposal(
                    kind="escalation",
                    payload={
                        "summary": session.identity.notes or "Identity not confirmed under §2.",
                        "requested_decision": (
                            "Advise that this is not an Aerlink booking."
                            if out_of_scope
                            else (
                                "Confirm the passenger's identity or advise that no action "
                                "can be taken until §2.1 is met."
                            )
                        ),
                        "queue": "GENERAL" if out_of_scope else "SUPERVISOR",
                        "recommendation": (
                            "No action on any Aerlink booking."
                            if out_of_scope
                            else "Do not act on any booking until identity is confirmed."
                        ),
                        "blocking_clause": "S2.2 out of scope" if out_of_scope else "S2.2",
                    },
                    notes="Auto-queued: identity not confirmed.",
                )
            )
        return

    if session.booking:
        intents = resolve_party_intents(session.inbound.raw_text, session.booking)
        if intents:
            session.passenger_requests = apply_party_requests(session.passenger_requests, intents)
        session.passenger_requests = apply_latest_wins(
            session.passenger_requests, session.inbound.raw_text
        )

    rebook_ids = _request_ids(session, "rebook") or (
        _default_passenger_ids(session)
        if any(r.kind == "rebook" and not r.superseded for r in session.passenger_requests)
        else []
    )
    refund_ids = _request_ids(session, "refund")
    undecided_ids = _request_ids(session, "other")

    already_rebook = any(p.kind == "rebooking" for p in session.proposals)
    already_refund = any(p.kind == "refund" for p in session.proposals)
    already_hotel = any(p.kind == "hotel" for p in session.proposals)
    already_compensation = any(p.kind == "compensation" for p in session.proposals)
    already_escalation = any(p.kind == "escalation" for p in session.proposals)

    if refund_ids and not already_refund and session.booking:
        session.proposals.append(
            WriteProposal(
                kind="refund",
                payload={
                    "passenger_ids": refund_ids,
                    "amount_gbp": refund_share_gbp(session.booking, refund_ids),
                    "reason": "Passenger elected a refund under S6.1 / S7.3.",
                },
                notes="Auto-queued: per-passenger refund (not the whole booking).",
            )
        )

    if rebook_ids and not already_rebook:
        notes = _rebook_notes(session, rebook_ids)
        if session.eligible_rebook_options():
            session.proposals.append(
                WriteProposal(
                    kind="rebooking",
                    payload={"passenger_ids": rebook_ids, "option_id": None},
                    notes=notes or "Auto-queued: passenger asked to travel.",
                )
            )
        elif not already_escalation:
            session.proposals.append(
                WriteProposal(
                    kind="escalation",
                    payload={
                        "summary": (
                            "Passenger asked to travel but no own-carrier same-cabin "
                            "zero-fare seat is cached."
                        ),
                        "requested_decision": (
                            "Authorise a fare-difference or partner re-route, or contact the passenger."
                        ),
                        "queue": "SUPERVISOR",
                        "recommendation": "Do not confirm a speculative paid re-route at desk level.",
                        "blocking_clause": "S12.1 / S6.3",
                    },
                    notes="Auto-queued: no representative-authorised rebook option.",
                )
            )
            already_escalation = True

    if undecided_ids and not already_escalation:
        names = _names_for(session, undecided_ids)
        session.proposals.append(
            WriteProposal(
                kind="escalation",
                payload={
                    "summary": (
                        f"{names} asked to see options before deciding. "
                        "Do not rebook them speculatively."
                    ),
                    "requested_decision": f"Confirm whether {names} will travel or take a refund.",
                    "queue": "SPECIAL_ASSISTANCE",
                    "recommendation": "Present own-metal options; keep booked assistance if they travel (S14.4).",
                    "blocking_clause": "S6.4",
                },
                notes="Auto-queued: passenger has not elected a remedy.",
            )
        )
        already_escalation = True

    wants_hotel = any(r.kind == "hotel" and not r.superseded for r in session.passenger_requests)
    hotel_target = _hotel_from_booking(session)
    if wants_hotel and not already_hotel and hotel_target:
        station, night = hotel_target
        session.proposals.append(
            WriteProposal(
                kind="hotel",
                payload={
                    "station": station,
                    "night": night,
                    "passenger_ids": _default_passenger_ids(session),
                },
                notes="Auto-queued: passenger asked for overnight accommodation.",
            )
        )

    wants_comp = any(
        r.kind == "compensation" and not r.superseded for r in session.passenger_requests
    )
    ents = session.entitlements
    if wants_comp and ents and ents.compensation_status == "PAYABLE" and not already_compensation:
        session.proposals.append(
            WriteProposal(
                kind="compensation",
                payload={
                    "passenger_ids": _default_passenger_ids(session),
                    "amount_gbp": ents.total_payable_gbp,
                    "reason": "Statutory compensation per entitlements service (S10.2).",
                },
                notes="Auto-queued: entitlements service says payable. Passenger arithmetic ignored.",
            )
        )
    elif wants_comp and ents and ents.compensation_status != "PAYABLE":
        note = (
            f"Entitlements service: compensation {ents.compensation_status} "
            f"(£{ents.total_payable_gbp}). Passenger figures are ignored (S10.2). "
            "Flight cause is taken from the operational record, not the passenger's story."
        )
        if note not in session.human_follow_up:
            session.human_follow_up.append(note)

    wants_receipts = any(
        r.kind == "care_receipts" and not r.superseded for r in session.passenger_requests
    )
    if wants_receipts:
        note = (
            "§4.4 meal/refreshment or own-arranged hotel reimbursement against receipts. "
            "No meals write endpoint exists; do not pay this as goodwill (§4.3)."
        )
        if note not in session.human_follow_up:
            session.human_follow_up.append(note)

    wants_lost = any(
        r.kind == "lost_property" and not r.superseded for r in session.passenger_requests
    )
    if wants_lost:
        note = "Lost property is not a disruption write. Hand to LOST_PROPERTY; keep the coat claim separate from the rebook/hotel."
        if note not in session.human_follow_up:
            session.human_follow_up.append(note)
        if not already_escalation:
            session.proposals.append(
                WriteProposal(
                    kind="escalation",
                    payload={
                        "summary": "Passenger reported lost property alongside the disruption.",
                        "requested_decision": "Trace the item via lost property; disruption handling is separate.",
                        "queue": "LOST_PROPERTY",
                        "recommendation": "Do not withhold a hotel or rebook because of the coat claim.",
                        "blocking_clause": "S15 / lost property",
                    },
                    notes="Auto-queued: lost property is out of disruption writes.",
                )
            )


def execute(session: CaseSession, client: GateClient) -> list[ProposedAction]:
    results: list[ProposedAction] = []
    for proposal in session.proposals:
        results.append(_handle(session, client, proposal))
    session.actions = results
    return results


def _handle(session: CaseSession, client: GateClient, proposal: WriteProposal) -> ProposedAction:
    if proposal.kind == "escalation":
        return _do_escalation(session, client, proposal)

    identity_block = _require_identity(session, proposal)
    if identity_block:
        return identity_block

    handlers = {
        "rebooking": _do_rebooking,
        "compensation": _do_compensation,
        "goodwill": _do_goodwill,
        "refund": _do_refund,
        "hotel": _do_hotel,
    }
    return handlers[proposal.kind](session, client, proposal)


def _require_identity(session: CaseSession, proposal: WriteProposal) -> ProposedAction | None:
    if session.identity.status == "confirmed" and session.identity.booking_ref:
        return None
    return ProposedAction(
        kind=proposal.kind,
        payload=proposal.payload,
        gate_decision="blocked",
        gate_reason="No write unless identity is confirmed under §2.1 and a booking is attached.",
    )


def _do_rebooking(
    session: CaseSession, client: GateClient, proposal: WriteProposal
) -> ProposedAction:
    passenger_ids = _passenger_ids(session, proposal.payload.get("passenger_ids"))
    if isinstance(passenger_ids, ProposedAction):
        return passenger_ids

    option, option_error = _resolve_option(
        session, proposal.payload.get("option_id"), needed=len(passenger_ids)
    )
    if option_error:
        return _escalate_instead(
            session,
            client,
            proposal,
            summary=option_error,
            requested_decision="Authorise a re-route outside representative limits, or contact the passenger.",
            queue="SUPERVISOR",
            blocking_clause="S12.1 / S6.3",
        )

    assert option is not None
    body = {
        "booking_ref": session.identity.booking_ref,
        "passenger_ids": passenger_ids,
        "option_id": option.option_id,
        "flight_no": option.flight_no,
        "date": option.date,
        "cabin": option.cabin,
        "fare_gbp": option.fare_gbp,
        "notes": proposal.notes
        or proposal.payload.get("notes")
        or _rebook_notes(session, passenger_ids)
        or "Desk rebooking",
    }
    try:
        result = client.create_rebooking(body)
    except OpsError as exc:
        return ProposedAction(
            kind="rebooking",
            payload=body,
            gate_decision="blocked",
            gate_reason=f"Rebooking POST failed: {exc}",
        )
    return ProposedAction(
        kind="rebooking",
        payload=body,
        gate_decision="allowed",
        gate_reason="Own-carrier same-cabin zero-fare option fetched in this session.",
        result=result,
    )


def _resolve_option(
    session: CaseSession, option_id: str | None, needed: int = 1
) -> tuple[AvailabilityOption | None, str | None]:
    booked_cabin = session._booked_cabin()
    eligible = [
        o for o in session.eligible_rebook_options() if o.seats_available >= needed
    ]
    if option_id:
        option = session.options.get(option_id)
        if option is not None:
            reason = _option_ineligible(option, booked_cabin, needed)
            if reason is None:
                return option, None
        elif option is None:
            reason = f"option_id {option_id} was not returned by an availability search in this session."
        if eligible:
            return eligible[0], None
        return None, reason

    if not eligible:
        return None, (
            "No own-carrier same-cabin zero-fare seat is cached. "
            "Representative cannot confirm a fare-difference or partner re-route (S12.1)."
        )
    return eligible[0], None


def _option_ineligible(
    option: AvailabilityOption, booked_cabin: str | None, needed: int = 1
) -> str | None:
    if option.seats_available < needed:
        return f"{option.option_id} has {option.seats_available} seats; {needed} passengers need moving."
    if option.partners or option.operated_by.lower() != "aerlink":
        return f"{option.option_id} is partner metal; representative cannot confirm (S12.1)."
    if option.fare_gbp != 0:
        return f"{option.option_id} has fare_gbp {option.fare_gbp}; fare difference needs supervisor (S12.1)."
    if booked_cabin and option.cabin != booked_cabin:
        return f"{option.option_id} cabin {option.cabin} differs from booked {booked_cabin}; cabin change needs supervisor."
    return None


def _do_compensation(
    session: CaseSession, client: GateClient, proposal: WriteProposal
) -> ProposedAction:
    ents = session.entitlements
    if ents is None or not ents.raw:
        return ProposedAction(
            kind="compensation",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason="Compensation requires GET /entitlements/calculate in this session.",
        )
    if ents.compensation_status != "PAYABLE" or not ents.total_payable_gbp:
        return ProposedAction(
            kind="compensation",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason=(
                f"Entitlements service says compensation is {ents.compensation_status} "
                f"(£{ents.total_payable_gbp}). Passenger figures are ignored (S10.2)."
            ),
        )

    passenger_ids = _passenger_ids(session, proposal.payload.get("passenger_ids"))
    if isinstance(passenger_ids, ProposedAction):
        passenger_ids.kind = "compensation"
        return passenger_ids

    amount = float(ents.total_payable_gbp)
    hinted = proposal.payload.get("amount_gbp")
    note = ""
    if hinted is not None and abs(float(hinted) - amount) > 0.009:
        note = f" Model amount £{hinted} ignored; paid authoritative £{amount}."

    body = {
        "booking_ref": session.identity.booking_ref,
        "amount_gbp": amount,
        "passenger_ids": passenger_ids,
        "reason": proposal.payload.get("reason") or "Statutory compensation per entitlements service.",
    }
    try:
        result = client.create_compensation(body)
    except OpsError as exc:
        return ProposedAction(
            kind="compensation",
            payload=body,
            gate_decision="blocked",
            gate_reason=f"Compensation POST failed: {exc}",
        )
    return ProposedAction(
        kind="compensation",
        payload=body,
        gate_decision="allowed",
        gate_reason="Amount taken from /entitlements/calculate." + note,
        result=result,
    )


def _do_goodwill(
    session: CaseSession, client: GateClient, proposal: WriteProposal
) -> ProposedAction:
    try:
        amount = float(proposal.payload.get("amount_gbp"))
    except (TypeError, ValueError):
        return ProposedAction(
            kind="goodwill",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason="Goodwill proposal has no numeric amount_gbp.",
        )
    if amount <= 0:
        return ProposedAction(
            kind="goodwill",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason="Goodwill of £0 is not a payment. Do not POST /payments/goodwill.",
        )
    if inbound_has_injection(session.inbound.raw_text) or inbound_has_injection(
        str((session.booking or {}).get("special_requests") or "")
    ):
        return _escalate_instead(
            session,
            client,
            proposal,
            summary=(
                f"Goodwill of £{amount:.2f} was proposed from untrusted inbound or "
                "special_requests text (S12.4). Not paid."
            ),
            requested_decision=f"Approve or refuse goodwill of £{amount:.2f} after verifying the record.",
            queue="SUPERVISOR",
            blocking_clause="S12.4",
            original_kind="goodwill",
        )
    if _has_request(session, "care_receipts") or _looks_like_receipt_goodwill(proposal):
        return _escalate_instead(
            session,
            client,
            proposal,
            summary=(
                f"£{amount:.2f} looks like duty-of-care / own-arranged reimbursement. "
                "That is not /payments/goodwill (S4.3 vs S4.4)."
            ),
            requested_decision="Reimburse via the care process, not goodwill.",
            queue="SUPERVISOR",
            blocking_clause="S4.3 / S4.4",
            original_kind="goodwill",
        )
    if amount > GOODWILL_DESK_LIMIT_GBP:
        return _escalate_instead(
            session,
            client,
            proposal,
            summary=(
                f"Goodwill of £{amount:.2f} exceeds the £{GOODWILL_DESK_LIMIT_GBP:.0f} "
                "representative limit (S11.2 / S12.1)."
            ),
            requested_decision=f"Approve or refuse goodwill of £{amount:.2f}.",
            queue="SUPERVISOR",
            blocking_clause="S12.1 goodwill desk limit",
            original_kind="goodwill",
        )
    body = {
        "booking_ref": session.identity.booking_ref,
        "amount_gbp": amount,
        "reason": proposal.payload.get("reason") or proposal.notes or "Desk goodwill",
    }
    try:
        result = client.create_goodwill(body)
    except OpsError as exc:
        return ProposedAction(
            kind="goodwill",
            payload=body,
            gate_decision="blocked",
            gate_reason=f"Goodwill POST failed: {exc}",
        )
    return ProposedAction(
        kind="goodwill",
        payload=body,
        gate_decision="allowed",
        gate_reason=f"Goodwill £{amount:.2f} is within the £150 desk limit.",
        result=result,
    )


def _do_refund(
    session: CaseSession, client: GateClient, proposal: WriteProposal
) -> ProposedAction:
    if not _has_request(session, "refund"):
        return ProposedAction(
            kind="refund",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason=(
                "Passenger did not elect a refund (S6.1 / S7.3). "
                "Downgrade reimbursement is inside entitlements total_payable_gbp "
                "and is paid via /payments/compensation, not /refunds."
            ),
        )
    passenger_ids = _passenger_ids(session, proposal.payload.get("passenger_ids"))
    if isinstance(passenger_ids, ProposedAction):
        passenger_ids.kind = "refund"
        return passenger_ids
    try:
        amount = float(proposal.payload.get("amount_gbp"))
    except (TypeError, ValueError):
        amount = None
    if amount is None and session.booking:
        amount = refund_share_gbp(session.booking, passenger_ids)
    if amount is None:
        return ProposedAction(
            kind="refund",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason="Refund proposal has no numeric amount_gbp.",
        )
    body = {
        "booking_ref": session.identity.booking_ref,
        "passenger_ids": passenger_ids,
        "amount_gbp": amount,
        "reason": proposal.payload.get("reason") or proposal.notes or "",
    }
    try:
        result = client.create_refund(body)
    except OpsError as exc:
        return ProposedAction(
            kind="refund",
            payload=body,
            gate_decision="blocked",
            gate_reason=f"Refund POST failed: {exc}",
        )
    return ProposedAction(
        kind="refund",
        payload=body,
        gate_decision="allowed",
        gate_reason="Identity confirmed; passenger_ids on the booking.",
        result=result,
    )


def _do_hotel(
    session: CaseSession, client: GateClient, proposal: WriteProposal
) -> ProposedAction:
    if _has_request(session, "care_receipts") and not _has_request(session, "hotel"):
        return ProposedAction(
            kind="hotel",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason=(
                "Passenger already arranged their own hotel / receipts. "
                "Do not issue a voucher (S4.4). Record for a human; do not pay as goodwill."
            ),
        )
    station = _norm_station(str(proposal.payload.get("station") or ""), session)
    night = str(proposal.payload.get("night") or "")
    booked = _hotel_from_booking(session)
    if booked:
        if len(station) != 3:
            station = booked[0]
        if not night:
            night = booked[1]
    if len(station) != 3 or not night:
        return ProposedAction(
            kind="hotel",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason="Hotel proposal needs an IATA station and a night (YYYY-MM-DD).",
        )
    passenger_ids = _passenger_ids(session, proposal.payload.get("passenger_ids"))
    if isinstance(passenger_ids, ProposedAction):
        passenger_ids.kind = "hotel"
        return passenger_ids
    try:
        allocation = client.get_hotel_allocation(station, night)
    except OpsError as exc:
        return ProposedAction(
            kind="hotel",
            payload=proposal.payload,
            gate_decision="blocked",
            gate_reason=f"Hotel allocation lookup failed: {exc}",
        )
    remaining = int(allocation.get("rooms_remaining") or 0)
    if remaining <= 0:
        return _escalate_instead(
            session,
            client,
            proposal,
            summary=f"No rooms remain in the {station} allocation for {night} (S4.5).",
            requested_decision="Source additional rooms or authorise a passenger-arranged booking under S4.4.",
            queue="SUPERVISOR",
            blocking_clause="S4.5",
            original_kind="hotel",
        )
    body = {
        "booking_ref": session.identity.booking_ref,
        "station": station,
        "night": night,
        "passenger_ids": passenger_ids,
        "notes": proposal.notes or proposal.payload.get("notes") or "",
    }
    try:
        result = client.create_hotel_voucher(body)
    except OpsError as exc:
        return ProposedAction(
            kind="hotel",
            payload=body,
            gate_decision="blocked",
            gate_reason=f"Hotel voucher POST failed: {exc}",
        )
    return ProposedAction(
        kind="hotel",
        payload=body,
        gate_decision="allowed",
        gate_reason=f"Allocation at {station} on {night} had {remaining} room(s).",
        result=result,
    )


def _do_escalation(
    session: CaseSession, client: GateClient, proposal: WriteProposal
) -> ProposedAction:
    body = {
        "summary": proposal.payload.get("summary") or proposal.notes or "Desk escalation",
        "requested_decision": proposal.payload.get("requested_decision")
        or "Review and decide the next action.",
        "queue": _norm_queue(proposal.payload.get("queue")),
    }
    if session.identity.booking_ref:
        body["booking_ref"] = session.identity.booking_ref
    for key in ("recommendation", "blocking_clause"):
        if proposal.payload.get(key):
            body[key] = proposal.payload[key]
    try:
        result = client.create_escalation(body)
    except OpsError as exc:
        return ProposedAction(
            kind="escalation",
            payload=body,
            gate_decision="blocked",
            gate_reason=f"Escalation POST failed: {exc}",
        )
    return ProposedAction(
        kind="escalation",
        payload=body,
        gate_decision="allowed",
        gate_reason="Escalation is a valid successful outcome.",
        result=result,
    )


def _escalate_instead(
    session: CaseSession,
    client: GateClient,
    proposal: WriteProposal,
    *,
    summary: str,
    requested_decision: str,
    queue: str,
    blocking_clause: str,
    original_kind: str | None = None,
) -> ProposedAction:
    esc = WriteProposal(
        kind="escalation",
        payload={
            "summary": summary,
            "requested_decision": requested_decision,
            "queue": queue,
            "recommendation": proposal.notes or summary,
            "blocking_clause": blocking_clause,
        },
    )
    action = _do_escalation(session, client, esc)
    action.kind = original_kind or proposal.kind
    action.gate_decision = "escalated"
    action.gate_reason = summary
    return action


def _has_request(session: CaseSession, kind: str) -> bool:
    return any(r.kind == kind and not r.superseded for r in session.passenger_requests)


def _looks_like_receipt_goodwill(proposal: WriteProposal) -> bool:
    blob = f"{proposal.notes} {proposal.payload.get('reason') or ''}".lower()
    return any(
        tok in blob
        for tok in ("receipt", "breakfast", "coffee", "hotel", "own-arranged", "duty of care", "duty-of-care")
    )


def _norm_station(raw: str, session: CaseSession) -> str:
    token = (raw or "").strip()
    if len(token) == 3 and token.isalpha():
        return token.upper()
    mapped = STATION_ALIASES.get(token.lower())
    if mapped:
        return mapped
    booked = _hotel_from_booking(session)
    return booked[0] if booked else token.upper()


def _hotel_from_booking(session: CaseSession) -> tuple[str, str] | None:
    for seg in (session.booking or {}).get("segments") or []:
        if seg.get("is_affected") and seg.get("origin") and seg.get("date"):
            return str(seg["origin"]).upper(), str(seg["date"])
    return None


def _norm_queue(raw: Any) -> str:
    token = str(raw or "GENERAL").strip().upper().replace(" ", "_").replace("-", "_")
    if token in CANON_QUEUES:
        return token
    aliases = {
        "SUPERVISER": "SUPERVISOR",
        "SPECIALASSISTANCE": "SPECIAL_ASSISTANCE",
        "LOSTPROPERTY": "LOST_PROPERTY",
        "OPS": "OPS_LIAISON",
    }
    return aliases.get(token.replace("_", ""), "GENERAL")


def _passenger_ids(session: CaseSession, raw: Any) -> list[str] | ProposedAction:
    ids = [str(x) for x in (raw or [])]
    if not ids:
        ids = _default_passenger_ids(session)
    allowed = session.passenger_ids_on_booking()
    if allowed and any(pid not in allowed for pid in ids):
        return ProposedAction(
            kind="rebooking",
            payload={"passenger_ids": ids},
            gate_decision="blocked",
            gate_reason=f"passenger_ids {ids} are not all on booking {session.identity.booking_ref}.",
        )
    if not ids:
        return ProposedAction(
            kind="rebooking",
            payload={},
            gate_decision="blocked",
            gate_reason="No passenger_ids available on the confirmed booking.",
        )
    return ids


def _default_passenger_ids(session: CaseSession) -> list[str]:
    if session.identity.passenger_ids:
        return list(session.identity.passenger_ids)
    return sorted(session.passenger_ids_on_booking())


def _request_ids(session: CaseSession, kind: str) -> list[str]:
    ids: list[str] = []
    for req in session.passenger_requests:
        if req.kind != kind or req.superseded:
            continue
        for pid in req.passenger_ids:
            if pid not in ids:
                ids.append(pid)
    return ids


def _names_for(session: CaseSession, passenger_ids: list[str]) -> str:
    names = []
    for pax in (session.booking or {}).get("passengers") or []:
        if pax.get("passenger_id") in passenger_ids:
            names.append(f"{pax.get('given_name', '')} {pax.get('surname', '')}".strip())
    return ", ".join(names) or ", ".join(passenger_ids)


def _rebook_notes(session: CaseSession, passenger_ids: list[str]) -> str:
    bits = []
    for pax in (session.booking or {}).get("passengers") or []:
        if pax.get("passenger_id") in passenger_ids and pax.get("assistance"):
            bits.append(
                f"Re-book assistance {pax['assistance']} for "
                f"{pax.get('given_name')} {pax.get('surname')} (S14.4)."
            )
    return " ".join(bits)
