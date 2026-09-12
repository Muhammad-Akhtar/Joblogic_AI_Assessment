from __future__ import annotations

import json

from openai import OpenAI

from desk.agent.prompts import SYSTEM_PROMPT, user_prompt
from desk.agent.tools import dispatch, tool_schemas
from desk.config import Settings
from desk.domain.record import build_record, utcnow
from desk.domain.session import CaseSession
from desk.inbound.intake import InboundCase
from desk.ops.client import OpsClient
from desk.rules.gate import execute, finalize_proposals
from desk.rules.identity import extract_hints
from desk.usage import cached_tokens_from


def run_case(inbound: InboundCase, settings: Settings, ops: OpsClient) -> CaseSession:
    hints = extract_hints(inbound.raw_text, inbound.inbound_from)
    session = CaseSession(inbound, hints)
    session.model = settings.openai_model
    started = utcnow()

    openai = OpenAI(api_key=settings.openai_api_key)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": user_prompt(
                inbound.case_id,
                inbound.raw_text,
                inbound.inbound_from,
                inbound.subject,
                inbound.received_at,
            ),
        },
    ]
    tools = tool_schemas()

    for _ in range(settings.max_tool_rounds):
        response = openai.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        usage = response.usage
        if usage:
            session.add_usage(
                usage.prompt_tokens or 0,
                usage.completion_tokens or 0,
                usage.total_tokens or 0,
                cached_tokens_from(usage),
            )
        choice = response.choices[0].message
        messages.append(choice.model_dump(exclude_unset=True))
        if not choice.tool_calls:
            if choice.content and not session.recommendation:
                session.recommendation = choice.content
            break
        for call in choice.tool_calls:
            args = _parse_args(call.function.arguments)
            result = dispatch(call.function.name, args, session, ops)
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })
        if session.finished:
            break

    finalize_proposals(session)
    execute(session, ops)
    session._started_at = started  # type: ignore[attr-defined]
    session._record = build_record(session, started_at=started)  # type: ignore[attr-defined]
    return session


def _parse_args(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}
