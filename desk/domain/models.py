from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

IdentityStatus = Literal["confirmed", "unconfirmed", "out_of_scope"]
RequestKind = Literal[
    "rebook", "refund", "compensation", "hotel", "care_receipts", "lost_property", "other"
]
ActionKind = Literal[
    "rebooking", "compensation", "goodwill", "refund", "hotel", "escalation"
]
GateDecision = Literal["allowed", "blocked", "escalated"]
CaseDecision = Literal["resolved", "partially_resolved", "escalated", "no_action"]


class IdentityAssessment(BaseModel):
    status: IdentityStatus
    method: str | None = None
    booking_ref: str | None = None
    passenger_ids: list[str] = Field(default_factory=list)
    customer_id: str | None = None
    matched_on: list[str] = Field(default_factory=list)
    notes: str = ""


class DisruptionFacts(BaseModel):
    flight_no: str | None = None
    date: str | None = None
    status: str | None = None
    cause_code: str | None = None
    origin: str | None = None
    destination: str | None = None
    source: str = ""


class PassengerRequest(BaseModel):
    kind: RequestKind
    passenger_ids: list[str] = Field(default_factory=list)
    summary: str
    superseded: bool = False


class SourceRef(BaseModel):
    method: str
    path: str
    note: str = ""


class EntitlementSummary(BaseModel):
    status: str | None = None
    compensation_status: str | None = None
    total_payable_gbp: float | None = None
    duty_of_care_triggered: bool | None = None
    reasoning: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class WriteProposal(BaseModel):
    """Queued by the model. The write gate is the only thing that may execute it."""

    kind: ActionKind
    payload: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class ProposedAction(BaseModel):
    kind: ActionKind
    payload: dict[str, Any] = Field(default_factory=dict)
    gate_decision: GateDecision
    gate_reason: str
    result: dict[str, Any] | None = None


class CaseRecord(BaseModel):
    case_id: str
    channel: str | None = None
    received_at: str | None = None
    inbound_from: str | None = None
    subject: str | None = None
    started_at: str
    finished_at: str
    identity: IdentityAssessment
    booking_ref: str | None = None
    disruption: DisruptionFacts | None = None
    passenger_requests: list[PassengerRequest] = Field(default_factory=list)
    sources_consulted: list[SourceRef] = Field(default_factory=list)
    entitlements: EntitlementSummary | None = None
    decision: CaseDecision
    recommendation: str = ""
    actions_attempted: list[ProposedAction] = Field(default_factory=list)
    successful_writes: list[ProposedAction] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    escalation: dict[str, Any] | None = None
    human_follow_up: list[str] = Field(default_factory=list)
    model: str = ""
    token_usage: dict[str, Any] = Field(default_factory=dict)
