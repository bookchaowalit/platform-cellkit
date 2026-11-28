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
# 1.2.4: every question names where it acts; TOKEN is not a JWT, so a fingerprint.
WHERE = f"\nWhere: {kit_mcp.token_scope(TOKEN)}."
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
    assert message == "Delete kit-sample part 9? This cannot be undone." + WHERE
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
    assert ctx.asked[0][0] == "Purge widgets before 2026-01-01?" + WHERE
    run(server, "kit-sample.echo", {"before": "x"}, ctx)
    assert len(ctx.asked) == 1
    assert [r.url.path for r in seen] == ["/v1/widgets"]


def test_an_extension_tool_without_confirm_is_unchanged(monkeypatch):
    server, seen = make_server(extension_cell(monkeypatch))
    ctx = FakeContext(DeclinedElicitation())
    run(server, "kit-sample.purge", {"before": "2026-01-01"}, ctx)
    assert ctx.asked == []
    assert [r.url.path for r in seen] == ["/v1/widgets/purge"]


def test_a_confirmed_extension_tool_must_name_its_target(monkeypatch):
    with pytest.raises(kit_mcp.ConfigError, match="needs a confirm_message"):
        make_server(extension_cell(monkeypatch, confirm=True))


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
    assert shown == ["Delete kit-sample part 9? This cannot be undone." + WHERE]
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


def sealed_run(server, token, arguments, context):
    """call_tool as the transport runs it: CaptureSealedState saw this sealed token."""

    async def main():
        async def call_next(_ctx):
            return await server.call_tool("kit-sample.part.delete", arguments, context)

        params = {"name": "kit-sample.part.delete", "requestState": token}
        return await kit_mcp.CaptureSealedState()(
            types.SimpleNamespace(params=params), call_next
        )

    return asyncio.run(main())


def test_a_replayed_sealed_round_is_refused_until_the_token_expires(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(kit_mcp.time, "time", lambda: clock[0])
    server, seen = make_server()
    answer, state = answered_round(server)
    sealed_run(server, "mcp1.token-A", {"id": 9}, RoundContext(answer, state))
    with pytest.raises(ToolError, match="confirmation already used"):
        sealed_run(server, "mcp1.token-A", {"id": 9}, RoundContext(answer, state))
    assert server.used_round_ttl == 600.0 + kit_mcp.USED_ROUND_MARGIN
    clock[0] += server.used_round_ttl + 1
    sealed_run(server, "mcp1.token-A", {"id": 9}, RoundContext(answer, state))
    assert [r.method for r in seen] == ["DELETE", "DELETE"]


def test_a_new_call_for_the_same_record_gets_a_new_round():
    """E.g. the first DELETE answered 409; the person confirms again right away."""
    server, seen = make_server()
    answer, state = answered_round(server)
    sealed_run(server, "mcp1.token-A", {"id": 9}, RoundContext(answer, state))
    answer, state = answered_round(
        server
    )  # same plaintext, but the SDK seals a new token
    sealed_run(server, "mcp1.token-B", {"id": 9}, RoundContext(answer, state))
    assert [r.method for r in seen] == ["DELETE", "DELETE"]


def test_end_to_end_the_round_is_keyed_by_the_sealed_token(monkeypatch):
    server, seen = make_server()
    keys: list[str | None] = []
    real = kit_mcp.CallState

    def spy(**kwargs):
        keys.append(kwargs.get("sealed"))
        return real(**kwargs)

    monkeypatch.setattr(kit_mcp, "CallState", spy)

    async def on_elicit(context, params):
        return mcp_types.ElicitResult(action="accept", content={"confirm": True})

    async def main():
        async with Client(server, elicitation_callback=on_elicit) as client:
            for _ in range(2):
                await client.call_tool("kit-sample.part.delete", {"id": 9})

    asyncio.run(main())
    sealed = [k for k in keys if k is not None]
    assert len(sealed) == 2
    assert sealed[0] != sealed[1]  # a new token per round, never the plaintext
    assert all("outcomes" not in k for k in sealed)
    assert [r.method for r in seen] == ["DELETE", "DELETE"]


def test_the_question_is_built_only_when_asking(monkeypatch):
    def broken(_arguments):
        raise LookupError("no label for this id")

    def register(ext: kit_mcp.Extension) -> None:
        ext.add(
            "kit-sample.purge",
            PurgeArgs,
            "Purge.",
            lambda a: ext.call("POST", "/v1/widgets/purge", json=a),
            confirm=True,
            confirm_message=broken,
        )

    module = types.ModuleType("kit_broken_hook")
    module.register_mcp = register
    monkeypatch.setitem(sys.modules, "kit_broken_hook", module)
    server, seen = make_server(
        replace(load(FIXTURE_SPEC), mcp_extend="kit_broken_hook")
    )
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "off")
    run(server, "kit-sample.purge", {"before": "x"}, FakeContext(accept(True)))
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "ask")
    run(server, "kit-sample.purge", {"before": "x"}, FakeContext(capabilities=None))
    assert [r.url.path for r in seen] == ["/v1/widgets/purge"] * 2


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


def test_a_full_memory_refuses_instead_of_forgetting(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(kit_mcp.time, "time", lambda: clock[0])
    monkeypatch.setattr(kit_mcp, "USED_ROUNDS_KEPT", 2)
    server, _ = make_server()
    spent = [server.spend_round(k) for k in ("a", "b", "c")]
    assert spent == ["ok", "ok", "full"]
    assert server.spend_round("a") == "used"  # the oldest is still remembered
    clock[0] += server.used_round_ttl + 1
    assert server.spend_round("c") == "ok"  # expired keys make room
    assert list(server.used_rounds) == ["c"]


def test_a_full_memory_refuses_the_call(monkeypatch):
    monkeypatch.setattr(kit_mcp, "USED_ROUNDS_KEPT", 0)
    server, seen = make_server()
    answer, state = answered_round(server)
    with pytest.raises(ToolError, match="too many recent confirmations"):
        run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    assert seen == []


# --- Codex review of ddc038a -----------------------------------------------------------------------


class NoFormRound(RoundContext):
    def __init__(self, responses=None, state=None):
        super().__init__(responses, state)
        self.client_capabilities = (
            None  # a later round that does not repeat its capabilities
        )


def test_a_later_round_without_capabilities_is_decided_by_its_answer():
    server, seen = make_server()
    first = run(server, "kit-sample.part.delete", {"id": 9}, RoundContext())
    (key,) = first.input_requests
    declined = {key: mcp_types.ElicitResult(action="decline")}
    with pytest.raises(ToolError, match="cancelled: not confirmed"):
        run(
            server,
            "kit-sample.part.delete",
            {"id": 9},
            NoFormRound(declined, first.request_state),
        )
    assert seen == []
    accepted = {key: mcp_types.ElicitResult(action="accept", content={"confirm": True})}
    run(
        server,
        "kit-sample.part.delete",
        {"id": 9},
        NoFormRound(accepted, first.request_state),
    )
    assert [r.method for r in seen] == ["DELETE"]


def test_a_replay_with_changed_echo_is_still_a_replay():
    server, seen = make_server()
    answer, state = answered_round(server)
    run(server, "kit-sample.part.delete", {"id": 9}, RoundContext(answer, state))
    (key,) = answer
    reworded = json.dumps(json.loads(state), indent=2)
    with_meta = {
        key: mcp_types.ElicitResult(
            action="accept", content={"confirm": True}, _meta={"client": "retry"}
        )
    }
    with pytest.raises(ToolError, match="confirmation already used"):
        run(
            server,
            "kit-sample.part.delete",
            {"id": 9},
            RoundContext(with_meta, reworded),
        )
    assert [r.method for r in seen] == ["DELETE"]


def test_the_handler_gets_the_payload_the_question_was_built_from(monkeypatch):
    counter = iter(range(100))
    got: list[dict] = []

    class Stamped(Strict):
        """A time-like default: every validation stamps a new value."""

        stamp: int | None = None

        @pydantic.model_validator(mode="after")
        def stamped(self) -> Stamped:
            if self.stamp is None:
                self.stamp = next(counter)
            return self

    def purge(arguments: dict) -> dict:
        got.append(arguments)
        return {"ok": True}

    def register(ext: kit_mcp.Extension) -> None:
        ext.add(
            "kit-sample.stamp",
            Stamped,
            "Purge up to a stamp.",
            purge,
            confirm=True,
            confirm_message=lambda a: f"Purge up to {a.get('stamp')}?",
        )

    module = types.ModuleType("kit_stamp_hook")
    module.register_mcp = register
    monkeypatch.setitem(sys.modules, "kit_stamp_hook", module)
    server, _ = make_server(replace(load(FIXTURE_SPEC), mcp_extend="kit_stamp_hook"))
    ctx = FakeContext(accept(True))
    run(server, "kit-sample.stamp", {}, ctx)
    assert ctx.asked[0][0] == f"Purge up to {got[0]['stamp']}?" + WHERE
    assert got[0]["stamp"] is not None


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
    assert ctx.asked[0][0] == f"Purge {json.dumps(got[0], sort_keys=True)}?" + WHERE


def test_an_error_after_the_yes_is_not_reported_as_cancelled():
    def reply(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json", request=request)

    client = httpx.Client(base_url=API, transport=httpx.MockTransport(reply))
    server = kit_mcp.build_server(load(FIXTURE_SPEC), client, lambda: TOKEN)
    with pytest.raises(
        ToolError, match=r"^Error executing tool kit-sample\.part\.delete$"
    ):
        run(server, "kit-sample.part.delete", {"id": 9}, FakeContext(accept(True)))


# --- Codex review of 3803b86 -----------------------------------------------------------------------


def test_off_on_a_2026_round_spends_nothing(monkeypatch):
    """A client may send inputResponses: {} without requestState; no form was shown."""
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "off")
    server, seen = make_server()
    for record in (9, 10):
        run(server, "kit-sample.part.delete", {"id": record}, RoundContext({}, None))
    assert [r.url.path for r in seen] == ["/v1/parts/9", "/v1/parts/10"]
    assert server.used_rounds == {}


def test_the_no_form_shortcut_spends_nothing():
    server, seen = make_server()
    first = run(server, "kit-sample.part.delete", {"id": 9}, NoFormRound())
    assert [r.method for r in seen] == ["DELETE"]
    assert first is not None
    assert server.used_rounds == {}


def test_a_clock_set_back_keeps_the_spent_token(monkeypatch):
    wall, mono = [10_000.0], [500.0]
    monkeypatch.setattr(kit_mcp.time, "time", lambda: wall[0])
    monkeypatch.setattr(kit_mcp.time, "monotonic", lambda: mono[0])
    server, seen = make_server()
    answer, state = answered_round(server)
    sealed_run(server, "mcp1.token-A", {"id": 9}, RoundContext(answer, state))
    # 700 s pass, but the wall clock was set back an hour: the SDK (wall-clock exp) still takes it.
    mono[0] += 700
    wall[0] += 700 - 3600
    with pytest.raises(ToolError, match="confirmation already used"):
        sealed_run(server, "mcp1.token-A", {"id": 9}, RoundContext(answer, state))
    assert [r.method for r in seen] == ["DELETE"]


# --- Codex review of the cell bumps to 1.2.2 -----------------------------------------------------------


def test_empty_input_responses_without_state_is_a_first_round_for_a_formless_client(
    monkeypatch,
):
    """inputResponses: {} answers nothing: a client without forms keeps the 1.1.x delete under ask."""
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "ask")
    server, seen = make_server()
    run(server, "kit-sample.part.delete", {"id": 9}, NoFormRound({}, None))
    assert [r.method for r in seen] == ["DELETE"]
    assert server.used_rounds == {}


def test_empty_input_responses_without_state_under_require_is_refused(monkeypatch):
    monkeypatch.setenv("EMPIRE_MCP_CONFIRM", "require")
    server, seen = make_server()
    with pytest.raises(ToolError, match="cancelled: confirmation unavailable"):
        run(server, "kit-sample.part.delete", {"id": 9}, NoFormRound({}, None))
    assert seen == []


def test_empty_input_responses_without_state_asks_a_form_client():
    server, seen = make_server()
    first = run(server, "kit-sample.part.delete", {"id": 9}, RoundContext({}, None))
    assert first.result_type == "input_required"
    assert seen == []


# --- 1.2.4: the confirmation is bound to the workspace the question named ---------------------------

WS_A = "11111111-1111-4111-8111-111111111111"
WS_B = "22222222-2222-4222-8222-222222222222"


def jwt_for(ws: str, tail: str) -> str:
    """An unsigned JWT-shaped token with a ws claim (the kit reads it for display only)."""
    import base64

    def seg(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    return f"{seg({'alg': 'none'})}.{seg({'ws': ws, 'sub': ws})}.{tail}"


def swapping_server():
    """A server whose token can be swapped mid-call, like an edited EMPIRE_TOKEN_FILE."""
    current = [jwt_for(WS_A, "sigA")]
    seen: list[httpx.Request] = []

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204, request=request)

    client = httpx.Client(base_url=API, transport=httpx.MockTransport(reply))
    server = kit_mcp.build_server(load(FIXTURE_SPEC), client, lambda: current[0])
    return server, seen, current


def test_the_question_names_the_tokens_workspace_never_the_token():
    server, _, current = swapping_server()
    ctx = FakeContext(accept(True))
    run(server, "kit-sample.part.delete", {"id": 9}, ctx)
    message = ctx.asked[0][0]
    assert message.endswith(f"\nWhere: {kit_mcp.token_scope(current[0])}.")
    assert f"workspace {WS_A}, token " in message
    assert current[0] not in message
    assert "sigA" not in message


def test_a_token_swapped_while_the_form_is_open_is_not_used():
    server, seen, current = swapping_server()

    class Swapping(FakeContext):
        async def elicit(self, message, schema):
            current[0] = jwt_for(
                WS_B, "sigB"
            )  # the token file changes while the person reads
            return await super().elicit(message, schema)

    run(server, "kit-sample.part.delete", {"id": 9}, Swapping(accept(True)))
    assert [r.headers["Authorization"] for r in seen] == [
        f"Bearer {jwt_for(WS_A, 'sigA')}"
    ]


def test_a_2026_answer_for_another_workspace_is_asked_again():
    server, seen, current = swapping_server()
    first = run(server, "kit-sample.part.delete", {"id": 9}, RoundContext())
    (key,) = first.input_requests
    answer = {key: mcp_types.ElicitResult(action="accept", content={"confirm": True})}
    current[0] = jwt_for(WS_B, "sigB")
    again = run(
        server,
        "kit-sample.part.delete",
        {"id": 9},
        RoundContext(answer, first.request_state),
    )
    assert seen == []
    assert again.result_type == "input_required"
    (new_key,) = again.input_requests
    assert f"workspace {WS_B}" in again.input_requests[new_key].params.message


def test_a_2026_answer_for_the_same_workspace_sends_with_that_token():
    server, seen, _ = swapping_server()
    first = run(server, "kit-sample.part.delete", {"id": 9}, RoundContext())
    (key,) = first.input_requests
    answer = {key: mcp_types.ElicitResult(action="accept", content={"confirm": True})}
    run(
        server,
        "kit-sample.part.delete",
        {"id": 9},
        RoundContext(answer, first.request_state),
    )
    assert [r.headers["Authorization"] for r in seen] == [
        f"Bearer {jwt_for(WS_A, 'sigA')}"
    ]


def test_a_2026_answer_under_another_token_in_the_same_workspace_is_asked_again():
    server, seen, current = swapping_server()
    first = run(server, "kit-sample.part.delete", {"id": 9}, RoundContext())
    (key,) = first.input_requests
    answer = {key: mcp_types.ElicitResult(action="accept", content={"confirm": True})}
    current[0] = jwt_for(WS_A, "another-user")
    again = run(
        server,
        "kit-sample.part.delete",
        {"id": 9},
        RoundContext(answer, first.request_state),
    )
    assert seen == []
    assert again.result_type == "input_required"


@pytest.mark.parametrize("token", ["opaque-token-value", "a.!!!.c", "a.e30.c", ""])
def test_token_scope_falls_back_to_a_fingerprint(token):
    scope = kit_mcp.token_scope(token)
    assert scope.startswith("token ")
    assert len(scope) == len("token ") + 12
    assert token == "" or token not in scope
