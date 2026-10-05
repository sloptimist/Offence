# Payment readiness

Model accuracy is assessed through seller reputation and buyer checks. Sellers sign
exact-model claims; those signatures identify who made the claim, not what ran.
Execution proof is optional. Buyers who explicitly require it must still fail closed.
Mainnet activation requires an explicitly configured wallet, model offer and price.
The OpenAI-compatible gateway and job API remain free-only; paid purchases currently
use the direct signed protocol and CLI. Do not advertise the gateway as paid-capable.

## Settlement design

Use encrypted token batches with a Lightning invoice for each batch. Persist the
signed ciphertext before delivering it. In direct LND mode the payment preimage unlocks that batch;
the supplier waits for settlement before pulling the next batch from its backend. A disconnected
buyer can retain its ciphertext and recover the preimage from its Lightning node.
A payment timeout is an unknown outcome until reconciled, not evidence of failure.
This bounds unacknowledged delivery to one batch. A streaming GPU backend may keep
computing ahead, so it does not bound unpaid GPU computation to one batch. Prompt
prefill, backend cancellation and abandoned work require separate measurement.
Supplier admission, output and deadline limits remain necessary.

## Required release evidence

1. Implement explicit seller-claim assurance in offers, quotes, buyer policies and UI.
   Buyers must distinguish a claimed model from verified execution. Preserve strict
   proof-required refusal. Reputation is buyer-local, with observation scope and
   sample counts; neither receipts nor self-reported ratings prove model execution.
2. Exercise two real regtest LND nodes with routed payments. Verify disconnects and
   restarts before dispatch, during settlement and after settlement. Demonstrate
   both buyer key recovery and provider settlement reconciliation. Mock tests alone
   do not satisfy this requirement.
3. Add durable aggregate spend and routing-fee reservations, least-privilege wallet
   credentials, backup/restore checks and restart-safe reconciliation in the service.
4. Measure supplier exposure from prefill, abandoned batches and concurrency. Verify
   cancellation releases GPU capacity and admission controls resist repeated abuse.
5. Review the settlement protocol before adding production wallet configuration.
   Optional cryptographic assurance has its own acceptance gate in SPEC.md; it is
   not a prerequisite for reputation-based payments.

## Regtest recovery command

The buyer writes a private `.attempt.json` record before sending each payment and
fsyncs both the record and its directory. A timeout leaves the record pending.
With OFFENCE_LND_URL, OFFENCE_LND_MACAROON_FILE and OFFENCE_LND_TLS_CERT_FILE set:

```sh
python -m offence.cli recover-payments --data /path/to/buyer-data
```

The command checks that LND is on regtest, verifies retained signed batch evidence,
and queries payments by hash. Confirmed successes retain the preimage for decrypting
saved batches. Missing, interrupted or unrecognized results remain UNKNOWN. It never
submits or retries payments. The CLI also reconciles before new purchases. Provider settlement reconciliation
runs periodically in the service. It does not resume a stream, regenerate output or resend receipts.

The tracking adapter follows the official
[LND TrackPaymentV2 API](https://lightning.engineering/api-docs/api/lnd/router/track-payment-v2/).
The local real-LND harness exercises payment, full TCP delivery, and recovery after
a deliberately lost successful payment reply. Broader power-loss, backup/restore
and mainnet deployment validation remain separate requirements.

## Pricing and live configuration

StartOS Configure Payments accepts an LND HTTPS origin, TLS certificate and invoice
macaroon. Use a receive-only macaroon with invoices:read, invoices:write and info:read;
never give the provider a buyer spending credential. Blank credentials preserve saved
values. Payment configuration is disabled by default. A mainnet node must identify
itself as Bitcoin mainnet; there is no automatic fallback between networks.

Choose sats/token directly or US cents/kWh. Energy pricing additionally requires
measured joules/output-token (including prompt work) and an operator-supplied USD/BTC
rate. Electricity price alone cannot determine token cost. This computes electricity
cost only, without an implicit hardware charge or profit margin. Conversion rounds
up to integer millisatoshis; accepted signed quotes freeze the resulting token price.
Exchange rates are not fetched or updated automatically.

Paid CLI purchases require --lnd-mainnet, --assurance seller-claim, --max-msat,
--fee-limit-msat, --total-fee-limit-msat and a positive --daily-limit-msat. Share one
buyer data directory for a shared budget. Reservations cover the entire quote plus
routing-fee cap and persist across processes/restarts. Incomplete sessions retain
their full reservation indefinitely, even across the rolling daily boundary. This
is conservative: automated release after partial-session reconciliation is pending.
Use recover-payments --lnd-mainnet to recover mainnet payment keys without resending.
Neither the provider nor the recovery command refunds settled payments automatically.

The live operator still needs to supply the wallet connection, select pricing and
configure a model offer/backend. No real-funds smoke-test spending is authorized.

## Strike hosted receiving

Configure Payments accepts a `username@strike.me` receiving address and a masked
Strike API credential. Blank credentials preserve the saved value. Docker uses
`OFFENCE_STRIKE_API_KEY`. Use these receiving/status permissions only:

- `partner.account.profile.read`
- `partner.invoice.create-for-receiver`
- `partner.invoice.quote.generate`
- `partner.invoice.read`

The receiving profile must be public, able to receive, and support BTC invoices.
Offence checks the receiver account, exact BTC amount and invoice commitment.
Currency conversion is refused. Only the fixed Strike API origin is contacted;
redirects and arbitrary address domains are rejected. Generic LNURL-pay URLs and
other hosted wallets are not supported by this adapter. No spending API is used.

Strike chooses the Lightning preimage. Its separately negotiated `provider-key-v1`
mode therefore uses a different private batch key. The provider stores that key,
the signed ciphertext and invoice reference atomically before delivery. A buyer
must explicitly choose `--allow-provider-key-release`. After paying, the buyer
requests the key with a signed request and payment preimage. The supplier checks
buyer identity, batch binding and credited Strike settlement before key release.
It does not advance the paid stream on an unconfirmed payment.

Unlike direct LND `preimage-v1`, this mode needs the supplier online after payment
for decryption. A supplier can withhold a key after payment; signed evidence does
not eliminate that trust. Restore the supplier database and identity together.
Hosted batch keys and their sessions survive routine seven-day detail cleanup,
subject to the database size cap. Exhausted storage fails closed. Retention is
currently indefinite; no automatic pruning or refund policy is implemented.

For a lost wallet reply, first run `recover-payments --lnd-mainnet`. Then recover
hosted keys without paying again:

```sh
python -m offence.cli recover-hosted-keys https://PROVIDER --provider PROVIDER_PUBLIC_KEY --data /path/to/buyer-data
```

Use the same buyer identity/data directory. Recovery verifies signed records and
returns available paid output. An unavailable provider leaves recovery pending.
Strike BTC-to-BTC invoice quotes last one hour. Offence's shorter generation and
payment deadlines stop further work, but do not cancel that invoice. Late payment
can recover the retained key. Wallet amount limits may reject a batch; Offence
never silently rounds its price or substitutes a different receiving currency.

The protocol passes real LND regtest payments in supplier-key mode, including
lost-reply recovery without a second payment. Strike HTTP behavior is tested with
mocked API responses. This does not constitute live Strike acceptance testing.
A receiving address, private API credential, supplier price and real-funds test
budget are still required before a live payment test.

Sources: [Strike receiving workflow](https://docs.strike.me/walkthrough/receiving-payments/),
[profile](https://docs.strike.me/api/fetch-public-account-profile-info-by-handle/),
[receiver invoice](https://docs.strike.me/api/issue-invoice-for-receiver/),
[quote](https://docs.strike.me/api/issue-quote-for-invoice/), and
[settlement query](https://docs.strike.me/api/find-invoice-by-id/).
