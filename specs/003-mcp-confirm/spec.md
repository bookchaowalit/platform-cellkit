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
- **Form:** one boolean field `confirm`, validated strictly (`"true"` or `1` is not a tick). The message names the cell, the record type and the id,
  for example `Delete kit-sample part 9? This cannot be undone.` Extension tools may give their own
  message. The payload is validated once per round: the question is built from it and the handler
  receives that same payload. An extension's message must name every argument that decides what is
  destroyed, because the SDK re-asks when the question changes between rounds and the replay key
  below is the question. The generated message never includes a token or field values.
- **Outcomes:** accept with `confirm: true` calls the API. Accept with `false`, decline, cancel, a
  reply that does not match the form, or an error while asking all end the call with the tool
  error `cancelled: not confirmed`, and nothing is sent to the API. An error after the yes (the API
  may have acted) is reported as that error, never as cancelled.
- **One answer, one call (2026-07-28):** a confirmation given in an `InputRequiredResult` round is
  spent under a key the server derives from the tool name and the question, never from what the
  client echoes (`requestState`, `inputResponses`, `_meta`). The SDK's `request_state` is
  deterministic, so a replayed round and a new call that asks the same question look the same: the
  key is refused with `cancelled: confirmation already used` for 5 minutes (`USED_ROUND_TTL`), then
  forgotten. At most 4096 unexpired keys are kept; when full, a new confirmation is refused
  (`cancelled: too many recent confirmations`) rather than forgetting one early. The initialize
  handshake asks mid-call, so it has no replay round.
- **Later rounds:** the "client cannot show a form" shortcut of `ask` applies only to a call's first
  round. A round answering an earlier question is decided by that answer, even if it does not
  repeat the client's capabilities.
- **Out of scope:** a client that forges `requestState` outcomes can skip the form, exactly as a
  client can auto-accept it. Elicitation trusts the client; this protects the person from the
  model, not from a hostile client.
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
- AC9: an accept whose `confirm` is `"true"`, `1` or `"yes"` sends nothing, on both protocol eras.
- AC10: replaying an answered 2026-07-28 round sends nothing, also with reformatted `requestState`
  or changed `_meta`; another record is its own round; a full key store refuses.
- AC11: a later round without capabilities that declines sends nothing.
- AC12: the handler receives the payload the question was built from.
