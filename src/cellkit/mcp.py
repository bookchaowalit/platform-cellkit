"""MCP adapter for a cell: tools made from the cell's declared resources.

Every tool calls the cell's HTTP API with the caller's own token, so MCP has
exactly the authorization the API has: no tool reads the database, and no tool
accepts an actor, workspace, delegation or token argument. Unknown arguments
are rejected (strict pydantic models, ``extra="forbid"``), so a model cannot
change who it acts as by adding fields to a tool call.

Per resource ``<cell>.<resource>.<operation>``::

    list    filters declared in the spec, <date field>_from/_to,
            limit, offset, order                                 GET    /v1/<plural>
    get     id                                                   GET    /v1/<plural>/{id}
    create  the resource's fields                                POST   /v1/<plural>
    update  id, expected_version, the resource's fields          PATCH  /v1/<plural>/{id}
    delete  id                                                   DELETE /v1/<plural>/{id}

Configuration follows the other clients (ops-toolkit ``cell_store.py``, mcp-aggregator ``cell-store.ts``)::

    EMPIRE_<CELL>_API=https://...        env, else the owner-only ~/.config/empire-platform/client.env
    EMPIRE_TOKEN=...                     the bearer, else
    EMPIRE_TOKEN_FILE=/path/x.jwt        a token file (mode 600), else the automation token
    EMPIRE_MCP_AUTOMATION=owner-mcp      EMPIRE_AUTOMATION_TOKEN_<NAME> or ~/.config/empire-platform/tokens/<name>.jwt
    EMPIRE_MCP_READONLY=1                register only list and get
    EMPIRE_MCP_CONFIRM=ask|require|off   SPEC-003: ask the person before a delete (default ask)

    <cell>-mcp                           stdio server (see .mcp.json)

SPEC-003: a delete tool (and an extension tool added with ``confirm=True``) asks the person
through form elicitation after its arguments validate and before it calls the API; only an
accept with ``confirm: true`` goes through. ``ask`` skips the question for a client that cannot
show a form (the 1.1.x behaviour), ``require`` refuses it, ``off`` never asks, and any other
value counts as ``require``.
"""

from __future__ import annotations

import contextvars
import importlib
import inspect
import os
import re
import sys
import urllib.parse
import uuid
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from mcp.server.elicitation import AcceptedElicitation, ElicitationResult
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.mcpserver.resolve import Elicit, Resolve
from mcp_types import Tool as MCPTool
from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    create_model,
)
from pydantic import (
    Field as PydanticField,
)

from cellkit.app import _constraints, _python_type
from cellkit.spec import Cell, Field, Resource

OPERATIONS = ("list", "get", "create", "update", "delete")
READ_ONLY = ("list", "get")
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
MAX_LIMIT = 200
# Names that would let a caller choose who it acts as; never exposed as tool arguments, even if a resource has them.
IDENTITY_NAMES = frozenset(
    {
        "actor",
        "actor_id",
        "workspace",
        "workspace_id",
        "tenant",
        "tenant_id",
        "delegation",
        "token",
        "authorization",
        "owner_id",
    }
)
IDEMPOTENCY_KEY = r"^[A-Za-z0-9._:-]{8,128}$"
AUTOMATION = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
# Tool errors carry the HTTP status and one of these fixed words, never upstream text.
STATUS_WORDS = {
    400: "invalid",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    412: "conflict",
    422: "invalid",
    429: "rate_limited",
}


# The arguments exactly as the caller sent them: the framework fills defaults, but "unset" and "null" differ.
# The default is never mutated: call_tool() sets a fresh dict per call and handlers only read it.
sent: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "sent",
    default={},  # noqa: B039
)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolFailed(ToolError):
    """Reaches the MCP client as a tool error carrying only the API's error code."""


class ConfigError(RuntimeError):
    pass


# --- SPEC-003: confirmation before a destructive call ---------------------------------------------


class Confirm(BaseModel):
    """The elicitation form: one box the person ticks."""

    confirm: bool = PydanticField(
        description="Tick to go ahead. Leave it unticked, decline or cancel to stop."
    )


ConfirmMode = Literal["ask", "require", "off"]


def confirm_mode(environ: Any = None) -> ConfirmMode:
    environ = os.environ if environ is None else environ
    value = (environ.get("EMPIRE_MCP_CONFIRM") or "").strip().lower()
    if value in ("", "ask"):
        return "ask"
    if value == "off":
        return "off"
    return "require"  # "require" and every unknown value: fail closed


def can_ask(context: Any) -> bool:
    """True when the client declared form elicitation (an empty elicitation object means form)."""
    if context is None:
        return False
    try:
        capabilities = context.client_capabilities
    except (AssertionError, AttributeError, LookupError, ValueError):
        return False  # no request context (a direct call_tool, as in tests)
    elicitation = getattr(capabilities, "elicitation", None)
    if elicitation is None:
        return False
    return elicitation.form is not None or elicitation.url is None


# Set inside a confirm tool's body once the person said yes: an error before it means "not confirmed".
confirmed: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "confirmed", default=False
)


def confirmation_resolver(
    model: type[BaseModel], question: Callable[[dict[str, Any]], str]
) -> Callable[..., Any]:
    """The SDK resolver that asks (``Elicit``) or decides without asking.

    Resolvers work on both protocol eras: a standalone ``elicitation/create`` request mid-call
    before 2026-07-28, an ``InputRequiredResult`` round after it (``ctx.elicit()`` alone cannot).
    """

    async def resolve_confirmation(ctx: Context) -> Any:
        mode = confirm_mode()
        if mode == "off":
            return Confirm(confirm=True)
        if not can_ask(ctx):
            if mode == "require":
                raise ToolFailed("cancelled: confirmation unavailable")
            return Confirm(
                confirm=True
            )  # ask: a client without forms keeps the 1.1.x behaviour
        arguments = model.model_validate(sent.get()).model_dump(mode="json")
        return Elicit(question(arguments), Confirm)

    return resolve_confirmation


# --- configuration ------------------------------------------------------------------------------


def api_key(cell: str) -> str:
    return f"EMPIRE_{cell.upper().replace('-', '_')}_API"


def _client_file(environ: Any) -> dict[str, str]:
    override = (environ.get("EMPIRE_CLIENT_CONFIG") or "").strip()
    path = (
        Path(override).expanduser()
        if override
        else Path.home() / ".config" / "empire-platform" / "client.env"
    )
    try:
        mode = path.stat().st_mode
    except FileNotFoundError:
        return {}
    if mode & 0o077:
        raise ConfigError(
            f"refusing client config {path}: group/world accessible; run chmod 600"
        )
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("'\"")
    return values


def api_url(cell: str, environ: Any = None) -> str:
    environ = os.environ if environ is None else environ
    key = api_key(cell)
    value = (environ.get(key) or "").strip() or _client_file(environ).get(key, "")
    if not value:
        raise ConfigError(
            f"the {cell} API is not configured: set {key} (env or client.env)"
        )
    try:
        parts = urllib.parse.urlsplit(value)
        host = (parts.hostname or "").lower()
        parts.port  # noqa: B018 - raises ValueError on a bad port
    except ValueError:
        raise ConfigError(f"{key} is not a valid URL") from None
    if (
        parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or "?" in value
        or "#" in value
        or "@" in parts.netloc
    ):
        raise ConfigError(f"{key} must not carry userinfo, a query or a fragment")
    if not (parts.scheme == "https" and host) and not (
        parts.scheme == "http" and host in LOOPBACK
    ):
        raise ConfigError(
            f"{key} must be https (http only for 127.0.0.1, ::1 or localhost)"
        )
    return value


def _read_token_file(path: Path) -> str:
    if path.stat().st_mode & 0o077:
        raise ConfigError(
            f"token file {path} must be readable by its owner only (chmod 600)"
        )
    return path.read_text(encoding="utf-8").strip()


def _checked(token: str) -> str:
    token = token.strip()
    if not token or re.search(r"[\s\x00-\x1f\x7f]", token) or not token.isascii():
        raise ConfigError(
            "the token is empty or contains whitespace, control or non-ASCII characters"
        )
    return token


def bearer(environ: Any = None) -> str:
    """The caller's own token: EMPIRE_TOKEN, EMPIRE_TOKEN_FILE, else the named automation token."""
    environ = os.environ if environ is None else environ
    if environ.get("EMPIRE_TOKEN"):
        return _checked(environ["EMPIRE_TOKEN"])
    if environ.get("EMPIRE_TOKEN_FILE"):
        return _checked(
            _read_token_file(Path(environ["EMPIRE_TOKEN_FILE"]).expanduser())
        )
    name = environ.get("EMPIRE_MCP_AUTOMATION") or "owner-mcp"
    if not AUTOMATION.match(name):
        raise ConfigError(
            "EMPIRE_MCP_AUTOMATION must be a short lowercase name (letters, digits, '-')"
        )
    key = "EMPIRE_AUTOMATION_TOKEN_" + name.upper().replace("-", "_")
    if environ.get(key):
        return _checked(environ[key])
    path = Path.home() / ".config" / "empire-platform" / "tokens" / f"{name}.jwt"
    if path.is_file():
        return _checked(_read_token_file(path))
    raise ConfigError(f"no token: set EMPIRE_TOKEN, EMPIRE_TOKEN_FILE or {key}")


# --- argument models from the spec ----------------------------------------------------------------


def argument_models(cell: Cell, r: Resource) -> dict[str, type[Strict]]:
    """Strict argument model per operation, derived from the resource's fields."""
    name = "".join(part.title() for part in r.name.split("-"))

    exposed = tuple(f for f in r.fields if f.name not in IDENTITY_NAMES)
    for f in r.fields:
        if f.name in IDENTITY_NAMES:
            warnings.warn(
                f"{cell.name}.{r.name}.{f.name}: identity-like field is not exposed through MCP",
                stacklevel=2,
            )

    def typed(f: Field, *, required: bool) -> tuple[Any, Any]:
        typ, extra = _python_type(f), _constraints(f)
        if required:
            return (typ, PydanticField(**extra))
        return (typ | None, PydanticField(default=None, **extra))

    list_fields: dict[str, Any] = {
        **{
            f.name: typed(f, required=False)
            for f in exposed
            if f.name in r.filters and f.name not in ("limit", "offset", "order")
        },
        # SPEC-007: inclusive date/timestamp bounds, same names as the HTTP list.
        **{
            name: (_python_type(f) | None, PydanticField(default=None))
            for name, (f, _) in r.bounds.items()
            if f in exposed
        },
        "limit": (int, PydanticField(default=50, ge=1, le=MAX_LIMIT)),
        "offset": (int, PydanticField(default=0, ge=0)),
        "order": (Literal["asc", "desc"], PydanticField(default="asc")),
    }
    ident: dict[str, Any] = {"id": (int, PydanticField(gt=0))}
    create_fields: dict[str, Any] = {
        f.name: typed(f, required=f.required and f.default is None) for f in exposed
    }
    # A resource may already own a field called idempotency_key (it is then sent in the
    # body and reused as the header); otherwise the tool adds an optional retry key.
    if not any(f.name == "idempotency_key" for f in exposed):
        create_fields["idempotency_key"] = (
            str | None,
            PydanticField(default=None, pattern=IDEMPOTENCY_KEY),
        )
    update_fields: dict[str, Any] = {
        **ident,
        "expected_version": (int | None, PydanticField(default=None, ge=1)),
        **{f.name: typed(f, required=False) for f in exposed},
    }
    return {
        "list": create_model(f"{name}List", __base__=Strict, **list_fields),
        "get": create_model(f"{name}Ref", __base__=Strict, **ident),
        "create": create_model(f"{name}Create", __base__=Strict, **create_fields),
        "update": create_model(f"{name}Update", __base__=Strict, **update_fields),
        "delete": create_model(f"{name}Delete", __base__=Strict, **ident),
    }


@dataclass
class Extension:
    """What a cell's ``mcp_extend`` hook gets to add tools that follow the same rules.

    ``call(method, path, **httpx_kwargs)`` reaches the cell API as the caller; ``add(name, model,
    description, handler, keep_null=False, confirm=False, confirm_message=None)`` registers a
    strict tool whose handler gets the validated arguments. By default nulls are dropped, like list
    filters; a write tool passes ``keep_null=True`` to get exactly what the caller set (an explicit
    null clears a field, unset arguments stay out). A destructive tool passes ``confirm=True`` to
    ask the person first (SPEC-003); ``confirm_message(arguments)`` words the question and must
    not include secrets.
    """

    cell: Cell
    call: Callable[..., Any]
    add: Callable[..., None]
    read_only: bool


def tool_name(cell: Cell, r: Resource, operation: str) -> str:
    return f"{cell.name}.{r.name}.{operation}"


# --- the server ----------------------------------------------------------------------------------


class StrictMCPServer(MCPServer):
    """MCPServer that validates arguments against a strict model before any tool runs."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.argument_models: dict[str, type[Strict]] = {}
        # SPEC-003: tool name -> the question to ask, built from the validated arguments.
        self.confirm_messages: dict[str, Callable[[dict[str, Any]], str]] = {}

    @property
    def confirm(self) -> set[str]:
        return set(self.confirm_messages)

    async def list_tools(self) -> list[MCPTool]:
        tools = await super().list_tools()
        for tool in tools:
            model = self.argument_models.get(tool.name)
            if model is not None:
                tool.input_schema = {
                    **model.model_json_schema(),
                    "additionalProperties": False,
                }
        return tools

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Any = None
    ) -> Any:
        model = self.argument_models.get(name)
        if model is None:
            raise ToolFailed(f"unknown tool {name}")
        try:
            model.model_validate(arguments or {})
        except ValidationError as exc:
            fields = sorted(
                {str(error["loc"][0]) for error in exc.errors() if error["loc"]}
            )
            raise ToolFailed(f"invalid_arguments: {', '.join(fields)}") from exc
        token = sent.set(dict(arguments or {}))
        said_yes = confirmed.set(False)
        try:
            return await super().call_tool(name, arguments, context)
        except ToolFailed:
            raise
        except Exception as exc:
            if name not in self.confirm_messages or confirmed.get():
                raise
            # SPEC-003: before the person said yes, the API saw nothing. A refusal from the resolver
            # (the SDK may wrap it) keeps its word; an invalid reply or a broken channel is a "no".
            cause: BaseException | None = exc
            while cause is not None and not isinstance(cause, ToolFailed):
                cause = cause.__cause__ or cause.__context__
            raise (cause or ToolFailed("cancelled: not confirmed")) from None
        finally:
            confirmed.reset(said_yes)
            sent.reset(token)


def _with_signature(
    function: Callable[..., Any], model: type[Strict], *, confirmation: Any = None
) -> Callable[..., Any]:
    """Give ``function`` the model's fields as its keyword parameters (what the server introspects)."""
    params = []
    for fname, info in model.model_fields.items():
        default = inspect.Parameter.empty if info.is_required() else info.default
        params.append(
            inspect.Parameter(
                fname,
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=info.annotation,
            )
        )
    if (
        confirmation is not None
    ):  # SPEC-003: filled by the SDK resolver, never by the caller
        params.append(
            inspect.Parameter(
                "confirmation", inspect.Parameter.KEYWORD_ONLY, annotation=confirmation
            )
        )
    function.__signature__ = inspect.Signature(params)  # type: ignore[attr-defined]
    function.__annotations__ = {p.name: p.annotation for p in params}
    return function


def _no_preparse(server: MCPServer, name: str) -> None:
    """The framework json.loads strings for non-str parameters ("{}" in a text field); the strict model already
    validated the exact arguments, so skip the guess (best effort: relies on mcp 2.3 internals)."""
    tool = server._tool_manager.get_tool(name)
    if tool is not None:
        object.__setattr__(tool.fn_metadata, "pre_parse_json", lambda data: data)


def build_server(
    cell: Cell,
    client: httpx.Client,
    token: Callable[[], str],
    *,
    read_only: bool = False,
    server: StrictMCPServer | None = None,
) -> StrictMCPServer:
    """Register ``<cell>.<resource>.<operation>`` tools; ``client`` is the cell API (base_url set)."""
    if server is None:
        server = StrictMCPServer(
            cell.name,
            instructions=(
                f"Solo Empire {cell.title} cell. Every tool calls the cell API as the authenticated caller only."
            ),
        )

    def call(method: str, path: str, **kwargs: Any) -> Any:
        try:
            bearer_token = _checked(token())
        except ConfigError as exc:
            raise ToolFailed(str(exc)) from None
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "X-Empire-Channel": "mcp",
            "X-Correlation-Id": f"mcp-{uuid.uuid4().hex}",
            **kwargs.pop("headers", {}),
        }
        try:
            response = client.request(method, path, headers=headers, **kwargs)
        except httpx.HTTPError:
            raise ToolFailed("unavailable: the cell API could not be reached") from None
        if response.status_code >= 400:
            status = response.status_code
            word = STATUS_WORDS.get(status) or (
                "upstream_error" if status >= 500 else "error"
            )
            raise ToolFailed(f"{status}: {word}")
        return response.json() if response.content else {"deleted": True}

    def register(
        name: str,
        model: type[Strict],
        description: str,
        handler: Callable[[dict[str, Any]], Any],
        *,
        drop_none: bool,
        confirm: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        def function(**kwargs: Any) -> Any:
            if confirm is not None:
                outcome = kwargs.get("confirmation")
                if not (
                    isinstance(outcome, AcceptedElicitation)
                    and isinstance(outcome.data, Confirm)
                    and outcome.data.confirm
                ):
                    raise ToolFailed("cancelled: not confirmed")
                confirmed.set(True)
            checked = model.model_validate(sent.get())
            # list drops unset filters; the others send exactly what the caller set (null clears a field).
            return handler(
                checked.model_dump(mode="json", exclude_none=True)
                if drop_none
                else checked.model_dump(mode="json", exclude_unset=True)
            )

        function.__name__ = name.replace(".", "_").replace("-", "_")
        if confirm is not None and "confirmation" in model.model_fields:
            raise ConfigError(
                f"{name}: an argument named 'confirmation' clashes with SPEC-003"
            )
        server.argument_models[name] = model
        if confirm is not None:
            server.confirm_messages[name] = confirm
        server.tool(name=name, description=description)(
            _with_signature(
                function,
                model,
                confirmation=None
                if confirm is None
                else Annotated[
                    ElicitationResult[Confirm],
                    Resolve(confirmation_resolver(model, confirm)),
                ],
            )
        )
        _no_preparse(server, name)

    def add(
        r: Resource,
        operation: str,
        model: type[Strict],
        description: str,
        handler: Callable[[dict[str, Any]], Any],
    ) -> None:
        question = None
        if operation == "delete":
            what = r.name.replace("-", " ")

            def question(a: dict[str, Any], what: str = what) -> str:
                return f"Delete {cell.name} {what} {a['id']}? This cannot be undone."

        register(
            tool_name(cell, r, operation),
            model,
            description,
            handler,
            drop_none=operation == "list",
            confirm=question,
        )

    for r in cell.resources:
        models = argument_models(cell, r)
        base = f"/v1/{r.plural}"
        what = r.name.replace("-", " ")
        operations = READ_ONLY if read_only else OPERATIONS
        handlers: dict[str, tuple[str, Callable[..., Any]]] = {
            "list": (
                f"List {what} records in the caller's workspace, filtered by {', '.join(r.filters) or 'nothing'}.",
                lambda a, base=base: call("GET", base, params=a),
            ),
            "get": (
                f"Get one {what} by id.",
                lambda a, base=base: call("GET", f"{base}/{a['id']}"),
            ),
            "create": (
                f"Create a {what}. Pass the same idempotency_key when retrying so a retry cannot duplicate.",
                # Default arguments bind base/own per resource at definition time (late-binding closure).
                lambda a, base=base, own=any(f.name == "idempotency_key" for f in r.fields): (  # noqa: B008
                    call(
                        "POST",
                        base,
                        json={
                            k: v for k, v in a.items() if own or k != "idempotency_key"
                        },
                        headers={
                            "Idempotency-Key": a.get("idempotency_key")
                            or f"mcp-{uuid.uuid4().hex}"
                        },
                    )
                ),
            ),
            "update": (
                f"Change fields of a {what}; expected_version refuses a stale write (required when an amount changes).",
                lambda a, base=base: call(
                    "PATCH",
                    f"{base}/{a['id']}",
                    json={k: v for k, v in a.items() if k != "id"},
                ),
            ),
            "delete": (
                f"Delete a {what} by id (refused while other records reference it).",
                lambda a, base=base: call("DELETE", f"{base}/{a['id']}"),
            ),
        }
        for operation in operations:
            description, handler = handlers[operation]
            add(r, operation, models[operation], description, handler)

    def extension_add(
        name: str,
        model: type[Strict],
        description: str,
        handler: Callable[[dict[str, Any]], Any],
        keep_null: bool = False,
        confirm: bool = False,
        confirm_message: Callable[[dict[str, Any]], str] | None = None,
    ) -> None:
        def default_message(_arguments: dict[str, Any]) -> str:
            return f"Run {name}? This cannot be undone."

        register(
            name,
            model,
            description,
            handler,
            drop_none=not keep_null,
            confirm=(confirm_message or default_message) if confirm else None,
        )

    if cell.mcp_extend:
        module, _, function = cell.mcp_extend.partition(":")
        # nosemgrep: python.lang.security.audit.non-literal-import.non-literal-import -- module comes from the repo-owned cell.yaml mcp_extend key, never from a request
        hook = getattr(importlib.import_module(module), function or "register_mcp")
        hook(
            Extension(
                cell=cell,
                call=call,
                add=extension_add,
                read_only=read_only,
            )
        )
    return server


def find_cell() -> Cell:
    from cellkit.spec import load

    # The kit is an installed wheel, so its own location says nothing about the cell. The
    # repository is found from the variable, the working directory, or the virtualenv the
    # `<cell>-mcp` script runs in (<repo>/.venv), which works when it is started by absolute path.
    for root in (
        os.environ.get("CELL_APP_ROOT"),
        Path.cwd(),
        Path(sys.prefix).resolve().parent,
    ):
        if root and (Path(root) / "cell.yaml").is_file():
            return load(Path(root) / "cell.yaml")
    raise SystemExit(
        "cell.yaml not found: run from the cell repository or set CELL_APP_ROOT"
    )


def main() -> None:
    cell = find_cell()
    try:
        url, _ = api_url(cell.name), bearer()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from None
    client = httpx.Client(base_url=url, timeout=30, follow_redirects=False)
    server = build_server(
        cell, client, bearer, read_only=os.environ.get("EMPIRE_MCP_READONLY") == "1"
    )
    server.run("stdio")
