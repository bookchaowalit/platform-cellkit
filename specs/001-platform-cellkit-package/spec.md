# SPEC-001: platform-cellkit as a versioned package

- Status: implemented (v1.0.0)
- Owner decision: 2026-11-12, "เป็น platform cellkit เลย แต่ควรเป็นแค่ระบบที่จัดการระบบอื่นๆ microservice อีกที ไม่ควรรวมทุก microservice ไว้ที่เดียว"
- Main-only: yes

## Problem

25 services carried their own `src/cellkit` copy (~4,200 lines). On 2026-11-12 their main
branches held 15 distinct trees: the finance line (10 services, with `refs.py`, `relay.py`,
money/decimal/currency, expected_version, date bounds, :admin imports) and an older line
(15 services), two of which had local opt-in features (`pattern` in life-content-api;
`extra_roles` and `mcp_extend` in platform-intake-api). A bug fix needed up to 25 commits.

## Decision

One package, import name `cellkit`, built from the finance line plus the two opt-in features.
Services depend on a pinned release wheel. Services stay separate repositories, deploys and
databases.

## Acceptance criteria

- AC-01: the package's tests cover the mini cell and two finance fixtures; total coverage ≥ 93%.
- AC-02: the merged opt-in features are off unless a `cell.yaml` sets them (`test_cellkit_extensions.py`, `test_cellkit_pattern.py`).
- AC-03: a tag `vX.Y.Z` publishes a wheel, sdist and SHA256SUMS; a version mismatch or an existing release fails the job.
- AC-04: a service that swaps `src/cellkit` for the pinned wheel keeps its generated migration SQL and passes its own test suite unchanged (checked per service at migration).

## Fixed open items

- 1.0.7: `platform.py begin()` turns a non-JSON or odd-shaped refusal into Denied (was a 500).
- 1.0.7: `LocalCluster` keeps its trust-auth socket owner-only (0700 dir and socket).

## Open question (owner): who may speak for a kind in `finance.events.v1`

`refs._apply` accepts an event only when the envelope's `producer` matches the kind's cell. Both
fields are chosen by the sender. The Kafka ACL limits writers to the ten finance producer
credentials, so a leaked credential of one cell can forge another cell's creates and deletes and
make dependents look deletable. Options, all needing infrastructure or secrets:

1. Signed envelopes: each producer signs with its own Ed25519 key (private key in Infisical and
   the service's Railway vars). Consumers check against public keys pinned in the kit or in each
   service's config. Rollout: sign, then verify in report mode, then enforce.
2. One topic per producer (`finance.<cell>.events.v1`), each with a write ACL for that cell only.
   The reader maps topic to kind. Needs Aiven topics and ACLs, plus moving the offset rows.

Decided 2026-11-13: option 1, signed envelopes. See specs/002-signed-events (kit 1.1.0).
