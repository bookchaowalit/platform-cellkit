# SPEC-003: Ask the person before an MCP tool deletes

Status: approved by the owner on 2026-11-28 ("ทำเลย": add MCP Elicitation to the cellkit tools that
delete). Ships in kit 1.2.0.

## Problem

Every cell's MCP server registers `<cell>.<resource>.delete`. A model calls it like any other
tool, and nothing between the model and the API asks the person first. The MCP 2026 Elicitation
feature lets a server pause a tool call and show the person a form, and Claude Code shows it.

## Decision

Before a tool that needs confirmation calls the API, the server asks the person through form-mode
elicitation. The API is called only when the person accepts and ticks `confirm`.

- **Tools that ask:** every generated `delete` tool, and an extension tool registered with
  `ext.add(..., confirm=True)`. `confirm` defaults to `False`, so existing extension tools do not change.
- **Order:** the arguments are validated first (a call with bad arguments asks nothing), then the
  person is asked, then the API is called.
- **Form:** one boolean field `confirm`. The message names the cell, the record type and the id,
  for example `Delete kit-sample part 9? This cannot be undone.` Extension tools may give their own
  message. The message never includes a token or field values.
- **Outcomes:** accept with `confirm: true` calls the API. Accept with `false`, decline, cancel, a
  reply that does not match the form, or an error while asking all end the call with the tool
  error `cancelled: not confirmed`, and nothing is sent to the API.
- **Mode, `EMPIRE_MCP_CONFIRM`:**
  - `ask` (default, also when unset or empty): ask when the client declares form elicitation.
    A client that cannot show a form gets the 1.1.x behaviour (no question), so no client loses
    a tool on the bump.
  - `require`: as `ask`, but a client that cannot show a form gets `cancelled: confirmation unavailable`.
  - `off`: never ask.
  - Any other value counts as `require` (fail closed, as in SPEC-002).
- **Unchanged:** `EMPIRE_MCP_READONLY=1` still registers no delete tool. The HTTP API, SQL,
  routes, permissions and `cell.yaml` are unchanged.

## Acceptance criteria

- AC1: under `ask`, a client with form elicitation is asked once per delete, and the API sees the
  DELETE only after accept + `confirm: true`.
- AC2: decline, cancel, `confirm: false`, an invalid reply and an error while asking each send
  nothing to the API and return `cancelled: not confirmed`.
- AC3: under `ask`, a client without elicitation deletes as in 1.1.13; under `require` it gets
  `cancelled: confirmation unavailable` and the API sees nothing.
- AC4: under `off`, nothing is asked.
- AC5: an unknown `EMPIRE_MCP_CONFIRM` value acts as `require`; an empty one acts as `ask`.
- AC6: list, get, create and update never ask; an extension tool asks only with `confirm=True`.
- AC7: invalid arguments are refused before anything is asked.
- AC8: end to end, an in-process MCP client with an elicitation callback sees the form, and its
  answer decides whether the API is called.
