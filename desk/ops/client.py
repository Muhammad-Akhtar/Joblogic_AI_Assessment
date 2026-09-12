from __future__ import annotations

import time
from typing import Any

import httpx


class OpsError(Exception):
    def __init__(self, status: int, error: str, message: str, payload: dict | None = None):
        super().__init__(f"{status} {error}: {message}")
        self.status = status
        self.error = error
        self.message = message
        self.payload = payload or {}

    @classmethod
    def from_response(cls, response: httpx.Response) -> "OpsError":
        try:
            data = response.json()
        except Exception:
            data = {"error": "unknown", "message": response.text[:300]}
        return cls(
            status=response.status_code,
            error=str(data.get("error") or "unknown"),
            message=str(data.get("message") or response.text[:300]),
            payload=data if isinstance(data, dict) else {},
        )


class OpsClient:
    """Authenticated client for every route in env/API.md.

    Read and write methods take case-driven values (booking_ref, passenger_ids,
    dates, amounts). Nothing here is hard-coded to a fixture. Retries only the
    documented transient failures (429/503). Writes still go through the gate.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        default_timeout: float = 8.0,
        availability_timeout: float = 20.0,
        max_retries: int = 3,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.default_timeout = default_timeout
        self.availability_timeout = availability_timeout
        self.max_retries = max_retries
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"X-Ops-Key": api_key, "Content-Type": "application/json"},
            timeout=default_timeout,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> "OpsClient":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def health(self) -> dict[str, Any]:
        # /health does not require the ops key.
        r = httpx.get(f"{self.base_url}/health", timeout=5.0)
        r.raise_for_status()
        return r.json()

    def search_bookings(self, q: str) -> dict[str, Any]:
        return self._get("/bookings/search", params={"q": q})

    def get_booking(self, booking_ref: str) -> dict[str, Any]:
        return self._get(f"/bookings/{booking_ref}")

    def get_flight(self, flight_no: str, date: str) -> dict[str, Any]:
        return self._get(f"/flights/{flight_no}", params={"date": date})

    def search_availability(
        self,
        origin: str,
        destination: str,
        date: str,
        *,
        after: str | None = None,
        booking_ref: str | None = None,
        page: int = 1,
        page_size: int = 100,
        partners: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "from": origin,
            "to": destination,
            "date": date,
            "page": page,
            "page_size": min(page_size, 100),
        }
        if after:
            params["after"] = after
        if booking_ref:
            params["booking_ref"] = booking_ref
        path = "/flights/availability/partners" if partners else "/flights/availability"
        return self._get(path, params=params, timeout=self.availability_timeout)

    def search_policy(self, q: str, limit: int = 5) -> dict[str, Any]:
        return self._get("/policy/search", params={"q": q, "limit": min(limit, 20)})

    def get_customer_history(self, customer_id: str) -> dict[str, Any]:
        return self._get(f"/customers/{customer_id}/history")

    def calculate_entitlements(
        self, booking_ref: str, passenger_id: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"booking_ref": booking_ref}
        if passenger_id:
            params["passenger_id"] = passenger_id
        return self._get("/entitlements/calculate", params=params)

    def get_hotel_allocation(self, station: str, night: str) -> dict[str, Any]:
        return self._get(f"/stations/{station}/hotel-allocation", params={"night": night})

    def get_policy_document(self) -> dict[str, Any]:
        return self._get("/policy/document")

    def get_disruption_feed(self) -> dict[str, Any]:
        return self._get("/disruption/feed")

    def get_audit(self) -> dict[str, Any]:
        return self._get("/_audit")

    def reset(self) -> dict[str, Any]:
        return self._post("/_reset", {})

    def create_rebooking(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/rebooking", body)

    def cancel_rebooking(self, rebooking_id: str) -> dict[str, Any]:
        return self._post(f"/rebooking/{rebooking_id}/cancel", {})

    def create_compensation(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/payments/compensation", body)

    def create_goodwill(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/payments/goodwill", body)

    def create_refund(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/refunds", body)

    def create_hotel_voucher(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/vouchers/hotel", body)

    def create_escalation(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._post("/escalations", body)

    def _get(self, path: str, params: dict | None = None, timeout: float | None = None) -> dict:
        return self._request("GET", path, params=params, timeout=timeout)

    def _post(self, path: str, body: dict[str, Any]) -> dict:
        return self._request("POST", path, json=body)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        attempts = self.max_retries + 1
        for attempt in range(attempts):
            try:
                response = self._http.request(
                    method,
                    path,
                    params=params,
                    json=json,
                    timeout=timeout or self.default_timeout,
                )
            except httpx.TimeoutException as exc:
                last_error = exc
                if attempt == attempts - 1:
                    raise OpsError(503, "timeout", f"Timed out calling {method} {path}") from exc
                continue
            if response.status_code in (429, 503) and attempt < attempts - 1:
                if response.status_code == 429:
                    time.sleep(0.4 * (2 ** attempt))
                continue
            if response.status_code >= 400:
                raise OpsError.from_response(response)
            return response.json()
        raise OpsError(503, "service_unavailable", f"Retries exhausted for {method} {path}") from last_error
