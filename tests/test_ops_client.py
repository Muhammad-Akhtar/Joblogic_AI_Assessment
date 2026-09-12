"""Every env/API.md route is callable through OpsClient with case-driven payloads."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from desk.ops.client import OpsClient, OpsError


class _Recorder:
    """Stand-in for httpx.Client.request. Records calls; returns canned JSON."""

    def __init__(self, status: int = 200, body: dict[str, Any] | None = None):
        self.status = status
        self.body = body if body is not None else {"ok": True}
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, path: str, params=None, json=None, timeout=None):
        self.calls.append(
            {"method": method, "path": path, "params": params, "json": json}
        )
        return httpx.Response(self.status, json=self.body)

    def close(self) -> None:
        return None


def _client(recorder: _Recorder) -> OpsClient:
    client = OpsClient("http://ops.test", "test-key")
    client._http = recorder  # type: ignore[assignment]
    return client


def test_client_covers_every_documented_read_and_write():
    rec = _Recorder()
    ops = _client(rec)

    ops.search_bookings("Smith")
    ops.get_booking("AER-7T3M1B")
    ops.search_availability("MAN", "FCO", "2026-08-05", after="06:00", booking_ref="AER-7T3M1B")
    ops.search_availability("LHR", "LIS", "2026-08-08", partners=True, page=2, page_size=20)
    ops.get_flight("AK808", "2026-08-03")
    ops.search_policy("goodwill authority", limit=5)
    ops.get_policy_document()
    ops.get_customer_history("CUS-10008")
    ops.calculate_entitlements("AER-3B7Y5K")
    ops.calculate_entitlements("AER-7T3M1B", passenger_id="P5")
    ops.get_hotel_allocation("LGW", "2026-08-06")
    ops.get_disruption_feed()
    ops.create_rebooking(
        {
            "booking_ref": "AER-7T3M1B",
            "passenger_ids": ["P1", "P2"],
            "option_id": "OPT-3F91A2C0DE",
            "flight_no": "AK318",
            "date": "2026-08-05",
            "cabin": "ECONOMY",
            "fare_gbp": 0.0,
        }
    )
    ops.cancel_rebooking("RBK-00001")
    ops.create_hotel_voucher(
        {
            "booking_ref": "AER-8N4V6J",
            "station": "LGW",
            "night": "2026-08-06",
            "passenger_ids": ["P1"],
        }
    )
    ops.create_compensation(
        {
            "booking_ref": "AER-3B7Y5K",
            "amount_gbp": 415.0,
            "passenger_ids": ["P1"],
        }
    )
    ops.create_goodwill(
        {"booking_ref": "AER-2Q8W4N", "amount_gbp": 50.0, "reason": "delay"}
    )
    ops.create_refund(
        {
            "booking_ref": "AER-7T3M1B",
            "passenger_ids": ["P5"],
            "amount_gbp": 297.5,
        }
    )
    ops.create_escalation(
        {
            "summary": "Need a human",
            "requested_decision": "Confirm identity",
            "queue": "GENERAL",
        }
    )
    ops.get_audit()
    ops.reset()

    paths = {(c["method"], c["path"]) for c in rec.calls}
    assert paths == {
        ("GET", "/bookings/search"),
        ("GET", "/bookings/AER-7T3M1B"),
        ("GET", "/flights/availability"),
        ("GET", "/flights/availability/partners"),
        ("GET", "/flights/AK808"),
        ("GET", "/policy/search"),
        ("GET", "/policy/document"),
        ("GET", "/customers/CUS-10008/history"),
        ("GET", "/entitlements/calculate"),
        ("GET", "/stations/LGW/hotel-allocation"),
        ("GET", "/disruption/feed"),
        ("POST", "/rebooking"),
        ("POST", "/rebooking/RBK-00001/cancel"),
        ("POST", "/vouchers/hotel"),
        ("POST", "/payments/compensation"),
        ("POST", "/payments/goodwill"),
        ("POST", "/refunds"),
        ("POST", "/escalations"),
        ("GET", "/_audit"),
        ("POST", "/_reset"),
    }


def test_write_payloads_are_forwarded_as_given_not_reshaped():
    rec = _Recorder()
    ops = _client(rec)
    body = {
        "booking_ref": "AER-7T3M1B",
        "passenger_ids": ["P1", "P2", "P3"],
        "option_id": "OPT-CASE02",
        "flight_no": "AK318",
        "date": "2026-08-06",
        "notes": "three of five travelling",
    }
    ops.create_rebooking(body)
    sent = rec.calls[-1]["json"]
    assert sent["passenger_ids"] == ["P1", "P2", "P3"]
    assert sent["date"] == "2026-08-06"
    assert sent["notes"] == "three of five travelling"


def test_availability_query_uses_api_param_names():
    rec = _Recorder()
    ops = _client(rec)
    ops.search_availability("EDI", "AMS", "2026-08-04", after="18:00", booking_ref="AER-9L5D2R")
    params = rec.calls[-1]["params"]
    assert params["from"] == "EDI"
    assert params["to"] == "AMS"
    assert params["date"] == "2026-08-04"
    assert params["after"] == "18:00"
    assert params["booking_ref"] == "AER-9L5D2R"


def test_ops_error_surfaces_status_and_message():
    rec = _Recorder(status=404, body={"error": "not_found", "message": "No booking AER-0000."})
    ops = _client(rec)
    with pytest.raises(OpsError) as exc:
        ops.get_booking("AER-0000")
    assert exc.value.status == 404
    assert exc.value.error == "not_found"
    assert "AER-0000" in exc.value.message


def test_unauthorized_is_an_ops_error():
    rec = _Recorder(status=401, body={"error": "unauthorized", "message": "Missing or incorrect X-Ops-Key header."})
    ops = _client(rec)
    with pytest.raises(OpsError) as exc:
        ops.get_disruption_feed()
    assert exc.value.status == 401
    assert exc.value.error == "unauthorized"
