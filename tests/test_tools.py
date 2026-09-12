from __future__ import annotations

import json
from typing import Any

from desk.agent.tools import dispatch, tool_schemas
from desk.domain.session import CaseSession
from desk.inbound.intake import InboundCase
from desk.rules.identity import ContactHints


class _FakeOps:
    def __init__(self) -> None:
        self.cancelled: list[str] = []

    def get_policy_document(self) -> dict[str, Any]:
        return {
            "document_ref": "APCP-2026-04",
            "version": "11.3",
            "characters": 32075,
            "content": "x" * 32075,
        }

    def cancel_rebooking(self, rebooking_id: str) -> dict[str, Any]:
        self.cancelled.append(rebooking_id)
        raise AssertionError("desk must not POST /rebooking/{id}/cancel")


def _session() -> CaseSession:
    return CaseSession(InboundCase(case_id="t", raw_text="test"), ContactHints())


def test_tool_schemas_include_policy_document_and_cancel():
    names = {item["function"]["name"] for item in tool_schemas()}
    assert "get_policy_document" in names
    assert "cancel_rebooking" in names


def test_get_policy_document_does_not_dump_the_markdown():
    raw = dispatch("get_policy_document", {}, _session(), _FakeOps())  # type: ignore[arg-type]
    payload = json.loads(raw)
    assert payload["document_ref"] == "APCP-2026-04"
    assert "content" not in payload
    assert "search_policy" in payload["note"]


def test_cancel_rebooking_does_not_post():
    fake = _FakeOps()
    raw = dispatch("cancel_rebooking", {"rebooking_id": "RBK-1"}, _session(), fake)  # type: ignore[arg-type]
    payload = json.loads(raw)
    assert payload["error"] == "not_at_desk"
    assert fake.cancelled == []
