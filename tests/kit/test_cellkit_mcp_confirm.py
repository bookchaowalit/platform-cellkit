"""SPEC-003: MCP delete tools ask the person (form elicitation) before they call the cell API."""

from __future__ import annotations

import asyncio
import json
import sys
import types
from dataclasses import replace
from typing import Any

import httpx
import mcp_types
import pydantic
import pytest
from cellkit_support import FIXTURE_SPEC
from mcp.client.client import Client
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import (
    ClientCapabilities,
    ElicitationCapability,
    FormElicitationCapability,
)

from cellkit import mcp as kit_mcp
from cellkit.mcp import Strict
from cellkit.spec import load

API = "https://api.example"
TOKEN = "tok-SECRET-do-not-print-123456"
FORM = ClientCapabilities(
    elicitation=ElicitationCapability(form=FormElicitationCapability())
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv("EMPIRE_MCP_CONFIRM", raising=False)
    monkeypatch.delenv("EMPIRE_MCP_READONLY", raising=False)


class FakeContext:
    """What call_tool reads from the request context: the client's capabilities and elicit()."""

    def __init__(
        self, answer: Any = None, capabilities: ClientCapabilities | None = FORM
    ):
        self.client_capabilities = capabilities
        self.protocol_version = None  # the synchronous (pre-2026-07-28) path
        self.session = types.SimpleNamespace(can_send_request=False)
        self.request_id = "1"
        self.answer = answer
        self.asked: list[tuple[str, dict]] = []

    async def elicit(self, message: str, schema: type[pydantic.BaseModel]) -> Any:
        self.asked.append((message, schema.model_json_schema()))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def accept(confirm: bool):
    return AcceptedElicitation(data=kit_mcp.Confirm(confirm=confirm))


def make_server(cell=None):
    seen: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "DELETE":
            return httpx.Response(204, request=request)
        return httpx.Response(200, json={"items": [], "id": 1}, request=request)

    client = httpx.Client(base_url=API, transport=httpx.MockTransport(reply))
    server = kit_mcp.build_server(cell or load(FIXTURE_SPEC), client, lambda: TOKEN)
    return server, seen


def run(server, name: str, arguments: dict, context: Any = None):
    return asyncio.run(server.call_tool(name, arguments, context))


# --- AC1 / AC2: the answer decides --------------------------------------------------------------


def test_an_accepted_confirmation_sends_the_delete():
    server, seen = make_server()
    ctx = FakeContext(accept(True))
    result = run(server, "kit-sample.part.delete", {"id": 9}, ctx)
    assert json.loads(result.content[0].text) == {"deleted": True}
    assert [(r.method, r.url.path) for r in seen] == [("DELETE", "/v1/parts/9")]
    assert len(ctx.asked) == 1
    message, schema = ctx.asked[0]
    assert message == "Delete kit-sample part 9? This cannot be undone."
    assert TOKEN not in message
    assert set(schema["properties"]) == {"confirm"}


@pytest.mark.parametrize(
    "answer",
    [
        accept(False),
        DeclinedElicitation(),
        CancelledElicitation(),
        ValueError("reply does not match the form"),
        RuntimeError("transport closed"),
    ],
    ids=["confirm-false", "decline", "cancel", "invalid-reply", "error"],
)
def test_anything_but_a_ticked_accept_sends_nothing(answer):
    server, seen = make_server()
    with pytest.raises(ToolError, match=r"^cancelled: not confirmed$"):
        run(server, "kit-sample.part.delete", {"id": 9}, FakeContext(answer))
    assert seen == []


# --- AC3 / AC4 / AC5: modes ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "capabilities", [None, ClientCapabilities()], ids=["none", "no-elicitation"]
)
def test_ask_lets_a_client_that_cannot_show_a_form_delete_as_before(capabilities):
    server, seen = make_server()
    run(
        server,
        "kit-sample.part.delete",
        {"id": 9},
        FakeContext(capabilities=capabilities),
    )
    assert [r.method for r in seen] == ["DELETE"]


def test_ask_without_any_request_context_deletes_as_before():
    server, seen = make_server()
    run(server, "kit-sample.part.delete", {"id": 9})
    assert [r.method for r in seen] == ["DELETE"]


def test_url_only_elicitation_is_not_a_form():
    caps = ClientCapabilities(
        elicitation=ElicitationCapability(url=mcp_types.UrlElicitationCapability())
    )
    assert kit_mcp.can_ask(FakeContext(capabilities=caps)) is False
    legacy = ClientCapabilities(elicitation=ElicitationCapability())
    assert kit_mcp.can_ask(FakeContext(capabilities=legacy)) is True


@pytest.mark.parametrize("value", ["require", "REQUIRE", "enforce", "yes"])
def test_require_and_unknown_values_refuse_a_client_that_cannot_ask(monkeypatch, value):
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", value)
    server, seen = make_server()
    with pytest.raises(ToolError, match=r"^cancelled: confirmation unavailable$"):
        run(server, "kit-sample.part.delete", {"id": 9}, FakeContext(capabilities=None))
    assert seen == []


def test_require_still_asks_a_client_that_can(monkeypatch):
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "require")
    server, seen = make_server()
    run(server, "kit-sample.part.delete", {"id": 9}, FakeContext(accept(True)))
    assert [r.method for r in seen] == ["DELETE"]


@pytest.mark.parametrize("value", ["", "  ", "ask", "Ask"])
def test_empty_or_ask_is_the_default(monkeypatch, value):
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", value)
    assert kit_mcp.confirm_mode() == "ask"


def test_off_never_asks(monkeypatch):
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "off")
    server, seen = make_server()
    ctx = FakeContext(DeclinedElicitation())
    run(server, "kit-sample.part.delete", {"id": 9}, ctx)
    assert ctx.asked == []
    assert [r.method for r in seen] == ["DELETE"]


# --- AC6 / AC7: what asks, and when ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("kit-sample.part.list", {}),
        ("kit-sample.part.get", {"id": 9}),
        ("kit-sample.widget.create", {"title": "Alpha", "quantity": 4}),
        ("kit-sample.widget.update", {"id": 3, "title": "Beta"}),
    ],
)
def test_reads_and_writes_other_than_delete_never_ask(name, arguments):
    server, seen = make_server()
    ctx = FakeContext(DeclinedElicitation())
    run(server, name, arguments, ctx)
    assert ctx.asked == []
    assert len(seen) == 1


def test_only_delete_tools_are_marked():
    server, _ = make_server()
    assert server.confirm
    assert all(name.endswith(".delete") for name in server.confirm)


def test_invalid_arguments_are_refused_before_anything_is_asked():
    server, seen = make_server()
    ctx = FakeContext(accept(True))
    with pytest.raises(ToolError, match="invalid_arguments: id"):
        run(server, "kit-sample.part.delete", {"id": 0}, ctx)
    assert ctx.asked == []
    assert seen == []


class PurgeArgs(Strict):
    before: str


def extension_cell(monkeypatch, **add_kwargs):
    def register(ext: kit_mcp.Extension) -> None:
        ext.add(
            "kit-sample.purge",
            PurgeArgs,
            "Purge old widgets.",
            lambda a: ext.call("POST", "/v1/widgets/purge", json=a),
            **add_kwargs,
        )
        ext.add(
            "kit-sample.echo",
            PurgeArgs,
            "Echo.",
            lambda a: ext.call("GET", "/v1/widgets"),
        )

    module = types.ModuleType("kit_confirm_hook")
    module.register_mcp = register
    monkeypatch.setitem(sys.modules, "kit_confirm_hook", module)
    return replace(load(FIXTURE_SPEC), mcp_extend="kit_confirm_hook")


def test_an_extension_tool_asks_only_when_registered_with_confirm(monkeypatch):
    server, seen = make_server(
        extension_cell(
            monkeypatch,
            confirm=True,
            confirm_message=lambda a: f"Purge widgets before {a['before']}?",
        )
    )
    ctx = FakeContext(DeclinedElicitation())
    with pytest.raises(ToolError, match="cancelled: not confirmed"):
        run(server, "kit-sample.purge", {"before": "2026-01-01"}, ctx)
    assert ctx.asked[0][0] == "Purge widgets before 2026-01-01?"
    run(server, "kit-sample.echo", {"before": "x"}, ctx)
    assert len(ctx.asked) == 1
    assert [r.url.path for r in seen] == ["/v1/widgets"]


def test_an_extension_tool_without_confirm_is_unchanged(monkeypatch):
    server, seen = make_server(extension_cell(monkeypatch))
    ctx = FakeContext(DeclinedElicitation())
    run(server, "kit-sample.purge", {"before": "2026-01-01"}, ctx)
    assert ctx.asked == []
    assert [r.url.path for r in seen] == ["/v1/widgets/purge"]


def test_a_confirmed_extension_tool_gets_a_default_message(monkeypatch):
    server, _ = make_server(extension_cell(monkeypatch, confirm=True))
    ctx = FakeContext(accept(True))
    run(server, "kit-sample.purge", {"before": "2026-01-01"}, ctx)
    assert ctx.asked[0][0] == "Run kit-sample.purge? This cannot be undone."


def test_read_only_servers_register_no_tool_that_asks():
    client = httpx.Client(
        base_url=API, transport=httpx.MockTransport(lambda r: httpx.Response(200))
    )
    server = kit_mcp.build_server(
        load(FIXTURE_SPEC), client, lambda: TOKEN, read_only=True
    )
    assert server.confirm == set()


# --- AC8: a real MCP client --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode", ["auto", "legacy"], ids=["2026-07-28", "initialize-handshake"]
)
@pytest.mark.parametrize(("action", "deletes"), [("accept", True), ("decline", False)])
def test_end_to_end_the_clients_answer_decides(action, deletes, mode):
    server, seen = make_server()
    shown: list[str] = []

    async def on_elicit(context, params):
        shown.append(params.message)
        if action == "accept":
            return mcp_types.ElicitResult(action="accept", content={"confirm": True})
        return mcp_types.ElicitResult(action="decline")

    async def main():
        async with Client(server, elicitation_callback=on_elicit, mode=mode) as client:
            result = await client.call_tool("kit-sample.part.delete", {"id": 9})
            return result, client.protocol_version

    result, version = asyncio.run(main())
    assert version == ("2026-07-28" if mode == "auto" else "2025-11-25")
    assert shown == ["Delete kit-sample part 9? This cannot be undone."]
    assert bool(result.is_error) is not deletes
    assert [r.method for r in seen] == (["DELETE"] if deletes else [])
    if not deletes:
        assert "cancelled: not confirmed" in result.content[0].text


# --- Codex review of 48113f8 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "mode", ["auto", "legacy"], ids=["2026-07-28", "initialize-handshake"]
)
@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_only_a_real_boolean_true_is_a_tick(value, mode):
    server, seen = make_server()

    async def on_elicit(context, params):
        return mcp_types.ElicitResult(action="accept", content={"confirm": value})

    async def main():
        async with Client(server, elicitation_callback=on_elicit, mode=mode) as client:
            return await client.call_tool("kit-sample.part.delete", {"id": 9})

    result = asyncio.run(main())
    assert result.is_error
    assert seen == []


class RoundContext(FakeContext):
    """A 2026-07-28 request: the SDK answers with InputRequiredResult rounds."""

    def __init__(self, responses=None, state=None):
        super().__init__()
        self.protocol_version = "2026-07-28"
        self.input_responses = responses
        self.request_state = state


def answered_round(server):
    first = run(server, "kit-sample.part.delete", {"id": 9}, RoundContext())
    assert first.result_type == "input_required"
    (key,) = first.input_requests
    answer = {key: mcp_types.ElicitResult(action="accept", content={"confirm": True})}
    return answer, first.request_state


def test_an_answered_round_reaches_the_api_once():
    server, seen = make_server()
    answer, state = answered_round(server)
    run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    assert [r.method for r in seen] == ["DELETE"]
    with pytest.raises(ToolError, match=r"^cancelled: confirmation already used "):
        run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    assert [r.method for r in seen] == ["DELETE"]


def test_the_same_delete_again_waits_out_the_replay_window(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(kit_mcp.time, "monotonic", lambda: clock[0])
    server, seen = make_server()
    answer, state = answered_round(server)
    run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    answer, state = answered_round(
        server
    )  # a new call: the SDK state is the same bytes
    with pytest.raises(ToolError, match="confirmation already used"):
        run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    clock[0] += kit_mcp.USED_ROUND_TTL + 1
    run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    assert [r.method for r in seen] == ["DELETE", "DELETE"]


def test_another_record_is_its_own_round():
    server, seen = make_server()
    for record in (9, 10):
        first = run(server, "kit-sample.part.delete", {"id": record}, RoundContext())
        (key,) = first.input_requests
        answer = {
            key: mcp_types.ElicitResult(action="accept", content={"confirm": True})
        }
        run(
            server,
            "kit-sample.part.delete",
            {"id": record},
            RoundContext(answer, first.request_state),
        )
    assert [r.url.path for r in seen] == ["/v1/parts/9", "/v1/parts/10"]


def test_the_used_round_memory_is_bounded(monkeypatch):
    monkeypatch.setattr(kit_mcp, "USED_ROUNDS_KEPT", 2)
    server, _ = make_server()
    spent = [server.spend_round(k) for k in ("a", "b", "c")]
    assert spent == [True, True, True]
    assert list(server.used_rounds) == ["b", "c"]
    assert server.spend_round("c") is False


class SinceArgs(Strict):
    before: str = "2000-01-01"
    note: str | None = None


def test_the_question_shows_what_the_handler_gets(monkeypatch):
    got: list[dict] = []

    def purge(arguments: dict) -> dict:
        got.append(arguments)
        return {"ok": True}

    def register(ext: kit_mcp.Extension) -> None:
        ext.add(
            "kit-sample.purge",
            SinceArgs,
            "Purge.",
            purge,
            keep_null=True,
            confirm=True,
            confirm_message=lambda a: f"Purge {json.dumps(a, sort_keys=True)}?",
        )

    module = types.ModuleType("kit_payload_hook")
    module.register_mcp = register
    monkeypatch.setitem(sys.modules, "kit_payload_hook", module)
    server, _ = make_server(replace(load(FIXTURE_SPEC), mcp_extend="kit_payload_hook"))
    ctx = FakeContext(accept(True))
    run(server, "kit-sample.purge", {"note": None}, ctx)
    assert got == [{"note": None}]
    assert ctx.asked[0][0] == f"Purge {json.dumps(got[0], sort_keys=True)}?"


def test_an_error_after_the_yes_is_not_reported_as_cancelled():
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", request=request)

    client = httpx.Client(base_url=API, transport=httpx.MockTransport(reply))
    server = kit_mcp.build_server(load(FIXTURE_SPEC), client, lambda: TOKEN)
    with pytest.raises(
        ToolError, match=r"^Error executing tool kit-sample\.part\.delete$"
    ):
        run(server, "kit-sample.part.delete", {"id": 9}, FakeContext(accept(True)))
