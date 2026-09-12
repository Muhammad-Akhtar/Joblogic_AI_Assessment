from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AvailabilityOption(BaseModel):
    option_id: str
    flight_no: str
    operated_by: str = ""
    origin: str
    destination: str
    date: str
    departure_local: str
    arrival_local: str
    cabin: str
    seats_available: int
    fare_gbp: float
    arrival_delay_vs_original_minutes: int | None = None
    partners: bool = False


class Passenger(BaseModel):
    passenger_id: str
    given_name: str = ""
    surname: str = ""
    passenger_type: str | None = None
    age: int | None = None
    assistance: str | None = None
    cabin_booked: str | None = None
    cabin_flown: str | None = None


class Segment(BaseModel):
    segment_id: str
    flight_no: str
    date: str
    origin: str
    destination: str
    segment_fare_gbp: float | None = None
    cabin: str | None = None
    is_affected: bool = False


class BookingRecord(BaseModel):
    booking_ref: str
    customer_id: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    tier: str | None = None
    total_paid_gbp: float | None = None
    special_requests: str = ""
    passengers: list[Passenger] = Field(default_factory=list)
    segments: list[Segment] = Field(default_factory=list)
    final_destination: str | None = None
    disruption: dict[str, Any] | None = None
