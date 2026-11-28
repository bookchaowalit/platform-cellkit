# SPEC-003: Ask the person before an MCP tool deletes

Status: approved by the owner on 2026-11-28 ("ทำเลย": add MCP Elicitation to the cellkit tools that
delete). Ships in kit 1.2.0; replay and extension rules tightened in 1.2.1 and 1.2.2.

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
  message, and must: `confirm=True` without `confirm_message` is refused at registration (1.2.1),
  because only the extension knows which arguments say what is destroyed and which are safe to show.
  The kit adds where the delete acts (1.2.4): `Where: workspace <ws>, token <12-hex fingerprint>.` from the
  caller's token (claim `ws`, display only; the fingerprint alone without it; read off the event
  loop), and the confirmed call sends that same token, so a token swapped while the form is open is
  never used; on 2026-07-28 any other token changes the rebuilt question and the SDK asks again.
  The payload is validated once per round: the question is built from it, only when the person is
  actually asked (`off` and the no-form shortcut never call the message builder), and the handler
  receives that same payload. The generated message never includes a token or field values.
  An extension's validated payload must be a pure function of the call's arguments (no clock or
  counter in a default or validator): on 2026-07-28 the answer arrives in a later request, the
  payload and question are rebuilt there, and the SDK re-asks when the question changed. A
  non-deterministic payload therefore fails closed (asked again, nothing sent); a time bound belongs
  in an explicit argument the person sees.
- **Outcomes:** accept with `confirm: true` calls the API. Accept with `false`, decline, cancel, a
  reply that does not match the form, or an error while asking all end the call with the tool
  error `cancelled: not confirmed`, and nothing is sent to the API. An error after the yes (the API
  may have acted) is reported as that error, never as cancelled.
- **One answer, one call (2026-07-28):** the SDK seals every `requestState` it sends (AES-GCM with a
  random nonce, ttl 600 s by default) and unseals it before the handler runs. A confirmation is spent
  under that round's sealed token, captured by a middleware just outside the SDK boundary, so a
  replay (the same token again) is refused with `cancelled: confirmation already used`, while a new
  call for the same record (for example after a `409`) gets a new token and is asked again. A spent
  token is remembered for the SDK's ttl plus 60 s by the wall clock the SDK checks expiry with, so
  setting the clock back cannot forget a token the SDK still accepts (1.2.2). Only an answer to a
  form that was actually shown spends a round: `off` and the no-form shortcut never do (1.2.2). At most
  4096 unexpired tokens are kept; when full, a new confirmation is refused (`cancelled: too many
  recent confirmations`) rather than forgetting one early. The initialize handshake asks mid-call,
  so it has no replay round. (1.2.0 keyed on tool + question for 5 minutes, which refused a genuine
  re-confirmation and forgot replays before the SDK's 600 s expiry.)
- **Later rounds:** the "client cannot show a form" shortcut of `ask` applies only to a call's first
  round. A round answering an earlier question is decided by that answer, even if it does not
  repeat the client's capabilities.
- **Trust:** `requestState` is sealed by the SDK, so a client cannot forge recorded answers. A
  client can still auto-accept the form itself: elicitation trusts the client, and this protects
  the person from the model, not from a hostile client.
- **Mode, `EMPIRE_MCP_CONFIRM`:**
  - `ask` (default, also when unset or empty): ask when the client declares form elicitation.
    A client that cannot show a form gets the 1.1.x behaviour (no question), so no client loses
    a tool on the bump.
  - `require`: as `ask`, but a client that cannot show a form gets `cancelled: confirmation unavailable`.
  - `off`: never ask.
  - Any other value counts as `require` (fail closed, as in SPEC-002).
- **Unchanged:** `EMPIRE_MCP_READONLY=1` still registers no delete tool. The HTTP API, SQL,
  routes, permissions and `cell.yaml` are unchanged.

## Known gaps (Codex review of 2fbeb8d..9fb4cb0, 2026-11-28; accepted, not fixed)

- A round answered with decline, cancel or `confirm: false` is not spent, so the client can send the
  same sealed token again with an accept and the API is called. Only the client can build that
  answer, and the trust rule above already lets a client accept the form itself; a person who
  declined and then retries gets a new round.
- A spent token is forgotten after ttl + 60 s by the wall clock. If the server clock is then set back
  into the token's lifetime, the SDK accepts it again and a client replay is not caught. This needs
  the host clock to go back more than about 11 minutes; the SDK's own `exp` check fails the same way.
- The question names the record by id, not by version: a record deleted and re-imported with the
  same `legacy_id` while the form is open is deleted on the yes. The generated `DELETE` route takes
  no `expected_version`; binding the version needs that API change first.
- An extension tool with `confirm=True` validates its arguments twice in the first round (once by
  `call_tool`, once to build the question). No extension uses `confirm=True` yet; cache the first
  result if one with a costly validator appears.

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
- AC13 (1.2.1): a replayed sealed round is refused until the SDK ttl + 60 s; a new call for the same
  record (new token) is asked and sent; end to end, rounds are keyed by distinct sealed tokens.
- AC15 (1.2.2): `off` with `inputResponses: {}` and no `requestState` deletes two records in a row;
  a spent token survives the wall clock being set back.
- AC16 (1.2.3): `inputResponses: {}` without `requestState` is a first round: under `ask` a client
  without forms deletes as on 1.1.x, under `require` it is refused, and a form client is asked.
- AC17 (1.2.4): the question names the token's workspace and never the token; a token swapped
  while the form is open is not used (the DELETE carries the token the question named); a 2026-07-28
  answer under another token (another workspace or another user in it) is asked again and sends
  nothing.
- AC14 (1.2.1): `confirm=True` without `confirm_message` fails at registration; a message builder
  that raises does not block `off` or the no-form shortcut.
