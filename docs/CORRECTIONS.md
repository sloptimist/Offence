# Historical correction spec

This document records revision 7 findings, not the current release verdict.
Revision 10 adds pre-acceptance fee-budget checks, bounded discovery responses,
and protection for the local advertisement when the peer cache is full. Full
Sybil resistance and fee-reservation reconciliation remain open. Use SECURITY.md
for current release gates; line references below may have moved.

Written 2026-10-04 from a full source review of revision 0.1.0:7, verified live on
the bootstrap node and the second node. Each item states where the defect is, what the code
does now, what it must do instead, and the test that proves it. Nothing here changes
the protocol contract in SPEC.md or relaxes a gate in PAYMENT-READINESS.md.

Priority order is P0 to P3. P0 items are defects that make a documented path fail
or leave a cheap attack open. Three couplings matter: C2 depends on C1, C5 depends
on the schema migration added by C4 and must ship in the same sideload, and C11
depends on C9 because the staged model advertises a context the protocol cannot
currently accept.

| ID | Priority | Title |
| --- | --- | --- |
| C1 | P0 | Routing-fee budget fails mid-stream instead of before acceptance |
| C2 | P0 | Successful payments never release their unused fee reservation |
| C3 | P0 | Mainnet CLI purchases always refuse on the default daily limit |
| C4 | P0 | Peer cache rejects new providers once full, with no eviction or source quota |
| C5 | P1 | Tried/new separation and reachability state for dial candidates |
| C6 | P1 | LND client churn, redundant chain checks, and poll-based settlement waiting |
| C7 | P2 | Free-only agent API is enforced by a magic constant, not by config |
| C8 | P2 | Per-batch payment economics are unmeasured |
| C9 | P1 | Advertised context capacity far exceeds the accepted input size |
| C10 | P3 | Source is uncommitted with no remote |
| C11 | P3 | No real model has produced a token through the protocol |

The table and the sections are in ID order so the IDs stay stable as references.
Suggested work order: C1, C2, C3, C4, C5, C9, C6, C7, then one sideload at
`0.1.0:8`, then C8 and C11, then C10 whenever you want the commit.

---

## C1. Routing-fee budget fails mid-stream instead of before acceptance

**Where** [client.py:158](../offence/client.py:158), [cli.py:36](../offence/cli.py:36),
[cli.py:43](../offence/cli.py:43)

**Now** The buyer reserves the full per-batch fee cap against the total fee budget
on every paid batch:

```python
if reserved_fees + fee_limit_msat > total_fee_limit_msat:
    raise ValueError("Total routing fee budget exhausted")
reserved_fees += fee_limit_msat
```

Both CLI defaults are 1000 msat, so the first batch consumes the entire budget and
batch 2 always raises. Any paid purchase longer than one batch fails with stock
flags, after the buyer has already paid for and decrypted batch 0. The regtest
smoke passes only because `scripts/lightning_smoke.py:97` sets both limits to 0 on
a direct channel, so a nonzero routing fee has never been exercised at all.

**Required** Refuse before acceptance, never mid-stream. After quote verification
in `Buyer.run` and before signing the acceptance, compute the worst-case fee
exposure from the quote and compare it to the budget:

```python
expected_batches = -(-max_tokens // q["batch_tokens"])   # ceiling division
required_fee_budget = expected_batches * fee_limit_msat
if required_fee_budget > total_fee_limit_msat:
    raise ValueError(
        f"Total routing fee budget {total_fee_limit_msat} msat cannot cover "
        f"{expected_batches} batches at {fee_limit_msat} msat each; "
        f"{required_fee_budget} msat is required")
```

Keep the per-batch check in the loop as a second defence; it must remain
unreachable under correct arithmetic.

**Implementation notes**

- Place the check after the existing quote-field verification block so a hostile
  `batch_tokens` cannot inflate the estimate past its own validation (`batch_tokens`
  is already bounded to 1..128 at [client.py:102](../offence/client.py:102)).
- `expected_batches` is worst case. A backend that stops early uses fewer batches;
  the budget is a cap, not a prediction.
- Print a warning on stderr from the CLI, not a refusal, when
  `total_fee_limit_msat > max_msat // 5`. Fees above a fifth of the purchase value
  are an operator decision, not a protocol violation, but they should be visible.
- Do not change the default `--fee-limit-msat`. A per-batch cap of 1000 msat is
  reasonable for a routed payment; the bug is the total, not the per-batch figure.
- Raise the `--total-fee-limit-msat` default to 0 and require it explicitly
  whenever `--fee-limit-msat` is nonzero, so the two values can never disagree
  silently. A 0/0 pair keeps the existing direct-channel smoke path working.

**Acceptance** `tests/test_payments.py`

- `test_fee_budget_refuses_before_acceptance`: a quote with `batch_tokens=2` and
  `max_tokens=8` against `fee_limit_msat=1000, total_fee_limit_msat=1000` raises
  before any acceptance is signed. Assert no `.quote.json` acceptance and no
  `.attempt.json` record is written, and assert the message names 4 batches.
- `test_fee_budget_admits_a_full_session`: the same quote with
  `total_fee_limit_msat=4000` completes all four batches.
- Extend `scripts/lightning_smoke.py` to run one session with
  `fee_limit_msat=1, total_fee_limit_msat=<batches>` so a nonzero fee path is
  covered by the real two-node regtest.

---

## C2. Successful payments never release their unused fee reservation

**Where** [client.py:160](../offence/client.py:160),
[lightning.py:82](../offence/lightning.py:82)

**Now** `reserved_fees` accumulates the full cap whether the payment cost 1 msat or
the full cap. `LndRegtest.pay` returns only the preimage, so the actual fee is
discarded. Over a 64-batch session the buyer over-reserves by up to 64 times the
real cost, which forces the operator to set a budget far above true exposure and
defeats the purpose of having a budget.

**Required** Reserve the cap before dispatch, then settle the reservation to the
actual fee once the payment result is known. Keep the full cap reserved whenever
the outcome is unknown, consistent with the existing rule in
[spending.py:19](../offence/spending.py:19) that uncertain reservations are never
released.

1. Change `LndRegtest.pay` to return `(preimage, fee_msat)`. Read the fee from the
   SendPaymentSync response's `payment_route.total_fees_msat`. Verify the exact
   field name against LND 0.21.4-beta before relying on it; if it is absent, fall
   back to `track()`, which already parses and bounds `fee_msat` at
   [lightning.py:144](../offence/lightning.py:144).
2. Validate the returned fee the same way `validate_tracking` does: integer and
   `0 <= fee_msat <= fee_limit_msat`. A fee above the authorised cap is a wallet
   contract violation and must raise, not be recorded.
3. In `Buyer.run`, after a successful `pay`, apply
   `reserved_fees += actual_fee_msat` instead of the cap. On any exception from
   `pay`, keep `reserved_fees += fee_limit_msat` and re-raise.
4. Record `fee_msat` in the `.payment.json` record so reconciliation and the
   economics harness in C8 can read real costs.
   `reconcile_payments` already stores `fee_msat` at
   [client.py:64](../offence/client.py:64); make the field name identical in both
   paths.

**Acceptance** `tests/test_payments.py`

- `test_actual_fee_replaces_the_reservation`: a simulated wallet reporting 1 msat
  of fee against a 1000 msat cap completes eight batches inside a 1000 msat total
  budget.
- `test_unknown_payment_outcome_holds_the_full_cap`: a wallet that raises on
  `pay` leaves the full cap reserved and the session refuses to continue.
- `test_fee_above_cap_is_refused`: a wallet reporting a fee above the authorised
  cap raises and writes no `.payment.json`.

---

## C3. Mainnet CLI purchases always refuse on the default daily limit

**Where** [cli.py:44](../offence/cli.py:44), [client.py:110](../offence/client.py:110),
[spending.py:24](../offence/spending.py:24)

**Now** `--daily-limit-msat` defaults to 0. `reserve` refuses when
`used + amount + fee > daily_limit`, so every mainnet purchase of nonzero value
fails on the first reservation. The failure is correct and fail-closed, but it is
raised deep inside the buyer with a message about a daily limit the operator never
knowingly set to zero.

**Required** Fail at argument parsing with an explicit instruction. When
`--lnd-mainnet` is passed and `--daily-limit-msat` is absent or zero, exit with:

```
--daily-limit-msat is required for mainnet purchases. It caps total msat reserved
in a rolling 24 hours, including routing fee caps. Incomplete sessions stay
reserved until reconciled.
```

Keep `reserve` unchanged. It is the durable enforcement point and must continue to
refuse a zero limit. This item only moves the refusal to where the operator can
act on it.

**Implementation notes**

- `argparse` cannot express this conditional. Validate after `parse_args()` in the
  `buy` branch and raise `SystemExit(2)`.
- Apply the same requirement to `recover-payments --lnd-mainnet`? No. Recovery
  sends no funds and must stay runnable with no budget configured.

**Acceptance** `tests/test_payments.py::test_mainnet_requires_an_explicit_daily_limit`
invokes the CLI argument validator directly and asserts exit code 2 and the
message. Do not spawn a subprocess.

---

## C4. Peer cache rejects new providers once full, with no eviction or source quota

**Where** [store.py:157](../offence/store.py:157)

**Now**

```python
if not row and self.db.execute("SELECT count(*) FROM peers").fetchone()[0] >= self.max_peers:
    return False
```

First come, first served, with no eviction. An attacker who generates
`max_peers` free Ed25519 keys and refills on each expiry cycle locks every
legitimate provider out of the local view. Advertisements expire in at most 300
seconds, so the attacker only needs to win a repeated race that costs nothing but
bandwidth. Random selection at [store.py:166](../offence/store.py:166) then draws
dial candidates entirely from the attacker's set. This is the eclipse-by-Sybil
attack that `ROADMAP.md` names, and it is an eviction-policy defect rather than an
identity-cost problem.

**Required** Bucket by the source the advertisement was learned from, cap each
source group, and evict within a group only. An attacker confined to one source
group must not be able to displace records learned from any other group.

**Schema** Add to the `peers` table, with an in-service migration following the
guarded `ALTER TABLE` pattern already used at [spending.py:16](../offence/spending.py:16):

```sql
ALTER TABLE peers ADD COLUMN source TEXT NOT NULL DEFAULT 'legacy';
ALTER TABLE peers ADD COLUMN first_seen INTEGER NOT NULL DEFAULT 0;
ALTER TABLE peers ADD COLUMN tried INTEGER NOT NULL DEFAULT 0;
```

Deployed nodes carry the old schema, so the migration must run on an existing
database without data loss. Existing rows become source `legacy`, which is treated
as an ordinary group.

**Source group derivation** The group is derived from the connection the record
arrived on, never from `ad.endpoint`, which is attacker-chosen. This distinction is
the entire point of the change; a comment must say so.

| Learned from | Group |
| --- | --- |
| Own advertisement ([discovery.py:67](../offence/discovery.py:67)) | `self`, exempt from caps and never evicted |
| An operator-configured seed in `config.seeds` | `operator`, exempt from caps and never evicted |
| Outbound exchange with a peer ([discovery.py:94](../offence/discovery.py:94)) | group of that peer's endpoint host |
| Inbound gossip POST ([app.py:173](../offence/app.py:173)) | group of `request.client.host` |

Host to group: for an IPv4 address, the first two octets (`8.8.0.0/16`); for an
IPv6 address, the `/32`; for a v3 onion origin, the full 56-character hostname;
for anything unresolvable, the literal string `unknown`.

**Signature** `ingest(self, envelope, now=None, source=None)`. A `None` source
means `unknown`. Keep the parameter third and defaulted so the existing calls in
`tests/test_jobs.py` and `scripts/jobs_smoke.py` continue to work unchanged.

**Admission and eviction** Replace the capacity check with:

1. If the signer already has a row, apply the existing monotonic-sequence rule and
   update in place. Preserve `tried` and `first_seen` across a sequence bump; a
   fresh advertisement from a peer that has answered before does not reset its
   standing.
2. Otherwise, if the group is `self` or `operator`, insert unconditionally.
3. Otherwise, if that group holds fewer than `max_peers_per_group` rows and the
   table holds fewer than `max_peers` rows, insert with `tried=0` and
   `first_seen=now`.
4. Otherwise, select the oldest `tried=0` row **in the same group** and replace it.
5. If every row in the group is `tried=1`, reject and return `False`.

Add `max_peers_per_group: int = Field(default=32, ge=1, le=512)` to `Config` in
[models.py](../offence/models.py) and thread it into `Store.__init__` beside
`max_peers`. Default 32 against `max_peers` 512 gives sixteen independent groups
before any group can crowd the table.

**Acceptance** `tests/test_discovery.py`

- `test_one_source_cannot_evict_another_source`: fill the table from group A to its
  cap, then ingest from group B and assert the B record is stored and every A
  record survives.
- `test_group_cap_evicts_only_untried_records_in_that_group`: at the group cap, a
  new record from the same group replaces the oldest untried record from that
  group and nothing else.
- `test_all_tried_group_refuses_new_records`: with every row in a group marked
  tried, a new record from that group returns `False`.
- `test_operator_seeds_are_never_evicted`: an `operator` record survives a flood
  from any other group.
- `test_sequence_bump_preserves_tried_and_first_seen`.
- `test_legacy_database_migrates`: open a `Store` against a database created with
  the pre-migration schema, assert the columns exist, existing rows are intact and
  carry source `legacy`, and reopening is idempotent.
- Update the existing `test_discovery_expiry_replay_and_capacity`. Its
  `assert not store.ingest(ad(two))` encodes the old reject-when-full behaviour and
  will now be wrong: with `max_peers=1` and two untried records from different
  groups, the second must be admitted by eviction rather than refused. Split the
  expiry and replay assertions, which stay valid, from the capacity assertion,
  which moves into the tests above.

---

## C5. Tried/new separation and reachability state for dial candidates

**Where** [discovery.py:98](../offence/discovery.py:98),
[store.py:163](../offence/store.py:163)

**Now** `tick` draws candidates from `store.peers()` with `ORDER BY RANDOM()`, so a
peer that has never answered ranks identically to one that has answered a hundred
times. `Discovery.backoff` holds failure state in memory only and is lost on
restart. C4 adds the `tried` column but nothing sets it.

**Required**

1. Set `tried=1` on a signer after a successful `exchange`. Add
   `Store.mark_tried(signer)` and call it from
   [discovery.py:113](../offence/discovery.py:113) on the success path only.
2. Add `Store.dial_candidates(limit)` returning tried rows first, then untried,
   randomised within each tier, so a flood of untried records cannot starve known
   good peers of dial attempts. Use it in `tick`. Leave `peers()` unchanged for
   offer search in `routing.select` and `/v1/providers`, which must still see every
   known offer.
3. Persist the backoff. Add `failures` and `retry_after` columns to `peers` in the
   same migration as C4 and move `Discovery.backoff` onto the store, so a restart
   does not re-dial a peer that has failed eight times. Keep the existing
   `min(300, 2**failures)` schedule.

**Explicitly out of scope** Active reachability probing of advertised endpoints,
Bitcoin-style bucket hashing with a per-node secret, and network-diversity
selection across groups when dialling. Those remain `ROADMAP.md` items. C4 and C5
close the cheap attack; they do not claim Core's eclipse resistance, and
`SPEC.md` and `docs/VALIDATION.md` must keep saying so.

**Acceptance** `tests/test_discovery.py`

- `test_tried_peers_are_dialled_before_new_peers`: one tried record against 100
  untried records appears in every `dial_candidates(4)` draw.
- `test_backoff_survives_restart`: a peer at eight failures is still suppressed
  after closing and reopening the store.
- `test_successful_exchange_marks_tried`.

---

## C6. LND client churn, redundant chain checks, and poll-based settlement waiting

**Where** [lightning.py:46](../offence/lightning.py:46),
[lightning.py:53](../offence/lightning.py:53),
[lightning.py:74](../offence/lightning.py:74)

**Now** `call` builds a fresh `httpx.AsyncClient` per request. `wait` polls
`settled()` every 250 milliseconds, so each active paid session drives four TLS
handshakes per second against LND. `check_network()` runs a `getinfo` on every
`invoice()` and every `pay()`, adding a round trip per batch, even though
`app.py`'s lifespan already verifies the chain once at startup.

**Required**

1. Hold one `httpx.AsyncClient` per wallet instance, created lazily on first use
   and closed in an `aclose()` method. Call it from the `lifespan` teardown in
   [app.py:80](../offence/app.py:80) and from the CLI buyer paths. Keep `verify`,
   `trust_env=False` and `follow_redirects=False` exactly as they are.
2. Cache `check_network()` for 60 seconds per instance. A restarted LND pointed at
   the wrong chain is then caught within a minute instead of never, which is
   stronger than dropping the check and far cheaper than running it per batch.
   Do not cache a failure; a failed check must re-run on the next call.
3. Replace the polling loop in `wait` with LND's invoice subscription
   (`/v2/invoices/subscribe/{payment_hash}` with a URL-safe base64 hash, the same
   encoding `track` needed at [lightning.py:109](../offence/lightning.py:109)).
   Keep `settled()` and fall back to polling with the existing 250 millisecond
   interval if the subscription errors, so a REST version without that route still
   works. Bound the subscription by `payment_timeout_s` exactly as now.

**Implementation notes**

- `aclose()` must be safe to call twice and safe to call when no client was ever
  created. The provider reconciliation loop in
  [app.py:63](../offence/app.py:63) runs every 30 seconds and will share the client.
- Keep `LndMainnet` inheriting all of this. Do not duplicate the client.

**Acceptance** `tests/test_payments.py`

- `test_chain_check_is_cached_and_failures_are_not`: a mocked transport counts one
  `getinfo` across two invoices inside the TTL, and counts a fresh call after a
  failed check.
- `test_settlement_subscription_falls_back_to_polling`: a transport returning 404
  for the subscription route still settles through `settled()`.
- `test_wallet_closes_cleanly_when_unused`.
- Re-run `scripts/lightning_smoke.py` against the real two-node regtest. The
  existing assertions must pass unchanged; this item is a performance correction
  and must not alter settlement semantics.

---

## C7. Free-only agent API is enforced by a magic constant, not by config

**Where** [routing.py:32](../offence/routing.py:32),
[gateway.py:121](../offence/gateway.py:121)

**Now** `routing.select` filters `offer.output_msat_per_token != 0` and
`gateway.chat` passes `max_msat=0`. The gateway and job APIs are therefore
structurally incapable of paid inference, which is the intended state per
`PAYMENT-READINESS.md`, but the intent lives in two unlabelled expressions. A
future reader could remove either one and believe they had enabled paid routing,
with no gate failing.

**Required** Make the constraint explicit and single-sourced. This is a clarity
correction with no behaviour change.

1. Add `max_msat_per_request: Literal[0] = 0` to `GatewayConfig` in
   [models.py:145](../offence/models.py:145). The `Literal[0]` annotation means a
   configuration file that sets anything else is rejected at load, so the gate
   cannot be opened by configuration alone.
2. Replace the `!= 0` filter with a comparison against
   `config.gateway.max_msat_per_request`, and pass the same value as `max_msat` in
   `gateway.chat` and in `jobs.execute` at
   [jobs.py:129](../offence/jobs.py:129).
3. Comment at the `GatewayConfig` field, not at the call sites: paid routing
   requires the release evidence in `docs/PAYMENT-READINESS.md`, and widening this
   type is the deliberate act that opens it.

**Acceptance** `tests/test_gateway.py::test_paid_gateway_cannot_be_enabled_by_config`
asserts `GatewayConfig(max_msat_per_request=1)` raises. Existing gateway and job
tests must pass unmodified; if any of them change, the behaviour changed and this
item was done wrong.

---

## C8. Per-batch payment economics are unmeasured

**Where** new `scripts/payment_economics.py`

**Now** `docs/RESEARCH.md` frames batch size as a 200 millisecond fill-time
tradeoff. The real cost is the settlement round trip: a 512-token answer at the
default `batch_tokens=8` is 64 sequential Lightning payments, each gated by
settlement before the next batch is pulled from the backend
([protocol.py:151](../offence/protocol.py:151)). At a plausible 10 msat per token a
batch is worth 80 msat while the default per-batch fee cap is 1000 msat. Neither
the latency nor the fee ratio has been measured, so every production default,
including `batch_tokens` itself, is currently a guess.

**Required** A measurement harness, not a code change. Reuse the real two-node
regtest fixture from `scripts/lightning_smoke.py` with its pinned image digests.
For each `batch_tokens` in 1, 8, 32 and 128, run one 256-token session and report:

- Wall-clock time to first delivered token.
- Wall-clock time to the full 256 tokens, and the implied tokens per second.
- Number of payments, total amount paid, total fees paid.
- Fees as a percentage of amount paid.
- Provider-side time spent waiting for settlement as a share of session wall clock.

Write the table into a new dated section of `docs/VALIDATION.md` and state plainly
that it is a regtest direct channel, which is the cheapest and fastest possible
case. A routed mainnet payment over several hops will be slower and dearer, so the
figures are a floor on latency and fees, not an estimate.

**Then** choose production defaults for `batch_tokens`, `--fee-limit-msat` and
`--total-fee-limit-msat` from the measurement and record the reasoning. Update the
`batch_tokens` default in [models.py:68](../offence/models.py:68) only if the data
supports a different value. Note in `ROADMAP.md` whether the result changes the
viability of per-batch settlement at all; if 64 payments per answer proves
unworkable, that is a protocol finding worth more than any item above it in this
spec, and it belongs in `SPEC.md` rather than being absorbed as a default change.

---

## C9. Advertised context capacity far exceeds the accepted input size

**Where** [models.py:33](../offence/models.py:33),
[models.py:100](../offence/models.py:100), [models.py:110](../offence/models.py:110),
[models.py:90](../offence/models.py:90)

**Now** `Manifest.context_tokens` accepts up to 10,000,000 and is advertised in the
offer, and `protocol.quote` reserves that whole figure against the hourly work
limit at [protocol.py:78](../offence/protocol.py:78). But a `Request` caps `prompt`
at 16,384 characters, caps each `ChatMessage.content` at 16,384 characters, and caps
total chat content at 16,384 bytes. A provider can therefore truthfully advertise a
180,000-token context while the protocol refuses any input above roughly 16 KiB,
which is on the order of 4,000 tokens.

This is now live-relevant: the second node has vLLM configured for 180,000 context, and
`AGENTS.md` already records that Offence input limits do not support full 180k
prompts. The asymmetry is also a supplier-side inefficiency, because each admitted
quote reserves 180,000 work tokens against
`max_work_tokens_per_hour` for a request that cannot exceed about 4,000 input
tokens plus its output budget. At the default 1,000,000 tokens per hour that is
five admitted quotes per hour on a large-context model.

**Required** Make the input ceiling explicit, negotiated and separately reserved,
rather than an incidental consequence of a validator constant.

1. Add `max_input_bytes: int = Field(default=16384, ge=1024, le=4_194_304)` to
   `Offer`. It is a supplier-advertised limit, so a buyer can filter on it before
   disclosing context.
2. Replace the hardcoded 16,384 limits in `Request.input_shape` with a check
   against the offer in `protocol.quote`, keeping an absolute schema ceiling at the
   new `max_input_bytes` upper bound so an unvalidated request still cannot be
   unbounded. The schema stays the outer bound; the offer sets the real one.
3. Reserve measured work, not advertised capacity. Reserve
   `actual_input_bytes // 4 + request.max_output_tokens` as a conservative token
   estimate instead of the full `context_tokens`, and record in a comment that
   bytes divided by four is a deliberate overestimate of tokens for English text
   and not a tokenizer result. Keep the reservation conservative; the current
   behaviour is safe but so coarse that it makes large-context offers unusable.
4. Add `min_input_bytes` to the search filters in
   [app.py:144](../offence/app.py:144) alongside `min_context` so a buyer with a
   large prompt can find a provider that will accept it.
5. Decide and record whether Offence intends to carry 180k-token prompts at all.
   A 180,000-token prompt is roughly 700 KiB, which exceeds the 512 KiB
   `MAX_WIRE` bound at [discovery.py:14](../offence/discovery.py:14) and the
   matching body limit in `bounded_body`. Raising `max_input_bytes` above 512 KiB
   therefore requires raising the request body bound as well, and that is a
   supplier-exposure decision, not a validator tweak. If the answer is no, say so
   in `SPEC.md` and cap `max_input_bytes` accordingly, so the offer cannot advertise
   a context the protocol will never accept.

**Acceptance** `tests/test_protocol.py`

- `test_input_above_offer_limit_is_refused_at_quote`.
- `test_input_within_offer_limit_is_admitted`, with an offer above the old 16 KiB
  constant.
- `test_work_reservation_tracks_measured_input_not_advertised_context`: a 1 KiB
  prompt against a 180,000-token context offer reserves far less than 180,000.
- `test_offer_cannot_advertise_input_above_the_wire_bound`.

---

## C10. Source is uncommitted with no remote

**Where** repository state

**Now** `0.1.0:7` is packed and verified live on both nodes, so the deployment drift
I found earlier in this review is closed: `/v1/status` on the bootstrap node now returns
`token_totals`, and `.startos/deployment-0.1.0-7.json` records both hosts. What
remains is that the repository still has zero commits and no remote, so the only
provenance for the running package is `.startos/release-0.1.0-7.json` plus the
ignored source snapshot.

**Required**, and each step needs your approval before it runs:

1. Initial commit and reviewed public GitHub push to `smallblocks/offence`, matching the
   `packageRepo` already declared at `startos/manifest/index.ts:7`.
2. Land the code corrections above, then bump to `0.1.0:8`. StartOS 0.4.x silently
   ignores a rebuilt package with an unchanged version, so the bump comes before
   the pack, not after.
3. Run `scripts/preflight.py`, pack both architectures (the second node is aarch64),
   sideload, and verify identity preservation and the C4 database migration on both
   hosts. Record the result in `.startos/deployment-0.1.0-8.json`.

One sideload should carry every code correction in this spec. Do not sideload C4
separately from C5; they share a single schema migration.

---

## C11. No real model has produced a token through the protocol

**Where** deployment

**Now** Both deployed nodes still report `backend: none`, confirmed live on the bootstrap node.
Every end-to-end demonstration used `Fixture` or a synthetic vLLM HTTP fixture. The
single real-model datapoint was a direct adapter call to a DeepSeek cluster, outside
the protocol. the second node now has pinned Qwen3.8-27B-Uncensored weights downloaded
and vLLM configured for 180,000 context, with validation pending.

Note the sequencing problem this creates: the node with the model is the second node, and
the second node is the node with no inbound advertised address. the bootstrap node is reachable and has no
backend. So neither node can currently sell inference, for two different reasons,
and `known_peers` on the bootstrap node is 0 because discovery runs only outbound from the second node.

**Required**

1. Finish the Qwen3 manifest. Hash the actual artifact files with
   `offence.cli manifest`, verify with `offence.cli verify-model`, and confirm the
   tokenizer, chat template and any adapter are listed as artifacts, since each one
   changes the computation. The manifest must not be derived from the backend's
   reported model name; the existing note in `docs/VALIDATION.md` is explicit about
   this, and it is the easiest rule to break when the server will happily tell you
   a name.
2. Set `backend: vllm` on the second node with its exact served model, and set
   `max_input_bytes` from C9 to what the 180,000-token configuration can actually
   accept through the protocol.
3. Complete one real purchase through the signed protocol, free lab mode first.
   Record exact token IDs, the delivered text, the session identifier and the signed
   end record. This is the first evidence that the protocol carries model output
   rather than fixture output, and it belongs in `docs/VALIDATION.md` under its own
   heading.
4. Give the second node a dialable address: a StartOS onion interface with an outbound Tor
   SOCKS proxy on the buyer side, or a reachable HTTPS origin. Until this is done,
   the node holding the model cannot be bought from at all. Then verify reciprocal
   discovery, with both nodes reporting a nonzero `known_peers` that excludes self.

Only after step 4 is there a two-node network rather than one reachable node with no
model and one unreachable node with a model.

---

## Non-goals

None of the following is in scope here, and no item above should be extended to
reach them:

- Cryptographic execution proof. `proof_policy: "required"` must keep failing
  closed at [protocol.py:39](../offence/protocol.py:39).
- Paid gateway or paid job API. C7 makes the block explicit; it does not lift it.
- Mainnet payments with real funds.
- Sybil resistance as such. C4 and C5 bound a cache-flooding attack. They do not
  make identities expensive, and `evidence.py` must keep returning
  `sybil_resistant: False`.
- A DHT, NAT traversal, hole punching or relay-mediated sessions.
- Nostr interoperability. It would improve offer propagation under relay diversity
  and would not affect Sybil cost, so it stays a `ROADMAP.md` option.

## Verification before release

Run all of these and record the results, not a summary:

```sh
.venv/bin/python -m pytest -q
.venv/bin/python scripts/smoke.py
.venv/bin/python scripts/gateway_smoke.py
.venv/bin/python scripts/jobs_smoke.py
.venv/bin/python scripts/lightning_smoke.py
.venv/bin/python scripts/payment_economics.py
npm run check && npm run build
.venv/bin/python scripts/preflight.py
```

`npm audit` still reports two high-severity findings in the bundled StartOS SDK
lint tooling. That is unchanged by this work and must not be described as passing.
