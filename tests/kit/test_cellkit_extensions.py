"""Opt-in cell.yaml keys merged into the kit from platform-intake-api: ``extra_roles`` and ``mcp_extend``."""

from __future__ import annotations

import asyncio
import sys
import types
from dataclasses import replace

import httpx
import pytest
from cellkit_support import FIXTURE_SPEC

from cellkit import mcp as kit_mcp
from cellkit.db import Names
from cellkit.mcp import Strict
from cellkit.spec import SpecError, _extra_roles, load, parse


def minimal(**top) -> dict:
    return {
        "cell": "kit",
        "resources": {"tag": {"fields": {"key": {"type": "text"}}}},
        **top,
    }


def test_extra_roles_default_to_none_and_are_validated():
    assert parse(minimal()).extra_roles == ()
    assert parse(minimal(extra_roles=["relay"])).extra_roles == ("relay",)
    assert _extra_roles(["relay", "reader"]) == ("relay", "reader")
    for bad in ("relay", ["Relay"], ["api"], ["migrator"], [1], ["x" * 22]):
        with pytest.raises(SpecError):
            _extra_roles(bad)


def test_runtime_roles_include_the_extra_roles():
    cell = parse(minimal(extra_roles=["relay"]))
    assert Names(cell).runtime_roles == (
        cell.role("api"),
        cell.role("publisher"),
        cell.role("relay"),
    )
    assert Names(parse(minimal())).runtime_roles == (
        cell.role("api"),
        cell.role("publisher"),
    )


class EchoArgs(Strict):
    text: str
    note: str | None = None


def test_mcp_extend_registers_extra_tools_that_reach_the_api(monkeypatch):
    seen: list[httpx.Request] = []
    got: dict = {}

    def register(ext: kit_mcp.Extension) -> None:
        got["read_only"] = ext.read_only
        got["cell"] = ext.cell.name

        def handler(args: dict) -> object:
            got["args"] = args
            return ext.call("GET", "/v1/widgets")

        ext.add("kit-sample.echo", EchoArgs, "Echo through the API.", handler)

    module = types.ModuleType("kit_ext_hook")
    module.register_mcp = register
    monkeypatch.setitem(sys.modules, "kit_ext_hook", module)

    def reply(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"items": []}, request=request)

    cell = replace(load(FIXTURE_SPEC), mcp_extend="kit_ext_hook")
    client = httpx.Client(
        base_url="https://api.example", transport=httpx.MockTransport(reply)
    )
    server = kit_mcp.build_server(
        cell, client, lambda: "tok-test-1234567890", read_only=False
    )

    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "kit-sample.echo" in names
    asyncio.run(server.call_tool("kit-sample.echo", {"text": "hi"}))
    assert got == {"read_only": False, "cell": cell.name, "args": {"text": "hi"}}
    assert [r.url.path for r in seen] == ["/v1/widgets"]
    assert seen[0].headers["authorization"] == "Bearer tok-test-1234567890"


def test_cells_without_mcp_extend_get_only_the_generated_tools():
    cell = load(FIXTURE_SPEC)
    assert cell.mcp_extend is None
    client = httpx.Client(
        base_url="https://api.example",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, request=r)),
    )
    server = kit_mcp.build_server(
        cell, client, lambda: "tok-test-1234567890", read_only=True
    )
    assert all(
        t.name.startswith("kit-sample.") for t in asyncio.run(server.list_tools())
    )
    assert "kit-sample.echo" not in {t.name for t in asyncio.run(server.list_tools())}
