from __future__ import annotations

from datetime import datetime, timezone

from desk.domain.models import CaseRecord, ProposedAction
from desk.domain.session import CaseSession


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(session: CaseSession, *, started_at: str, finished_at: str | None = None) -> CaseRecord:
    successful = [
        a for a in session.actions
        if a.gate_decision == "allowed" and a.result is not None
    ]
    escalation = _escalation_payload(session.actions)
    decision = _decision(session, successful, escalation)
    recommendation = session.recommendation or _default_recommendation(session, decision)
    return CaseRecord(
        case_id=session.inbound.case_id,
        channel=session.inbound.channel,
        received_at=session.inbound.received_at,
        inbound_from=session.inbound.inbound_from,
        subject=session.inbound.subject,
        started_at=started_at,
        finished_at=finished_at or utcnow(),
        identity=session.identity,
        booking_ref=session.identity.booking_ref or session.booking_ref,
        disruption=session.disruption,
        passenger_requests=session.passenger_requests,
        sources_consulted=session.sources,
        entitlements=session.entitlements,
        decision=decision,
        recommendation=recommendation,
        actions_attempted=session.actions,
        successful_writes=successful,
        uncertainty=session.uncertainty,
        escalation=escalation,
        human_follow_up=session.human_follow_up,
        model=session.model,
        token_usage=session.token_usage,
    )


def _escalation_payload(actions: list[ProposedAction]) -> dict | None:
    for action in actions:
        if action.gate_decision == "escalated" and action.result:
            return {
                "id": action.result.get("escalation_id"),
                "queue": action.payload.get("queue") or action.result.get("queue"),
                "reason": action.gate_reason,
                "requested_decision": action.payload.get("requested_decision"),
                "result": action.result,
            }
        if action.kind == "escalation" and action.gate_decision == "allowed" and action.result:
            return {
                "id": action.result.get("escalation_id"),
                "queue": action.payload.get("queue") or action.result.get("queue"),
                "reason": action.gate_reason,
                "requested_decision": action.payload.get("requested_decision"),
                "result": action.result,
            }
    return None


def _decision(session: CaseSession, successful: list[ProposedAction], escalation: dict | None) -> str:
    kinds = {a.kind for a in successful}
    resolving = kinds & {"rebooking", "compensation", "refund", "hotel", "goodwill"}
    if resolving and (session.human_follow_up or escalation):
        return "partially_resolved"
    if resolving:
        return "resolved"
    if escalation:
        return "escalated"
    return "no_action"


def _default_recommendation(session: CaseSession, decision: str) -> str:
    if decision == "resolved":
        return "Case actioned against the operational record and entitlements service."
    if decision == "partially_resolved":
        return (
            "Primary disruption action taken. Residual items are recorded for a human "
            "(see human_follow_up / escalation)."
        )
    if decision == "escalated":
        return session.identity.notes or "Handed to a human team."
    return "No authorised write was possible."
