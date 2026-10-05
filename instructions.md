# Offence operator instructions

## StartOS installation and configuration

Install a signed package only after reviewing its version and checks. Open Configure
Node, enter known peer origins, and open the dashboard to inspect discovery. An empty
configuration can run without joining a network or serving inference.

The service connects to a GPU server on your personal network. It does not install
models on the StartOS host or alter other services. Supported lab backend: llama.cpp
with `/tokenize` and streamed `/completion` exposing real token IDs. Set the server's
base origin, not an OpenAI `/v1` URL. A GPU server API key is stored as a secret.

An onion interface can provide inbound reachability; outbound onion connections
also require a reachable Tor SOCKS proxy. Set `socks5h://HOST:PORT` in Configure Node.
This package does not provision that proxy. For reachable LAN testing, put each exact
HTTP origin in Approved LAN peers. An advertisement cannot approve itself for LAN
access. Public DNS origins also require explicit operator approval in this lab.

Choose an advertised address reachable by your intended buyers. Copy your service's
actual address from StartOS; do not advertise a localhost address to other servers.
A home router may need explicit inbound configuration for clearnet service.

Paste the JSON `offer` object from a prepared config. For free lab experiments, use
a zero-price offer and Allow unverified lab inference. Configure Payments separately
sets the Lightning network, receiving credentials and sats/token or energy pricing.
Paid model identity is a seller claim, not proof of execution. See
[Payment readiness](docs/PAYMENT-READINESS.md) for required measurements, credentials
and current limitations. Do not enable a live offer before validating its backend.

## Exact model manifest

For a GGUF with embedded tokenizer and metadata:

```sh
.venv/bin/python -m offence.cli manifest /path/to/model.gguf \
  --name 'Your model' --architecture 'Your architecture' \
  --quantization 'Your exact quantization' --context 8192 > model-manifest.json
.venv/bin/python -m offence.cli verify-model model-manifest.json /path/to
```

For separate tokenizer, configuration, adapter or template files, add artifact
records with their SHA-256 and exact sizes. The role describes their purpose.
Use relative paths inside the model directory. `sources` is an optional list of
publisher or mirror URLs, excluded from identity. The verification command reports
the resulting model ID and explicitly reports `execution_verified: false`.

An offer contains `manifest`, `output_msat_per_token`, `batch_tokens`,
`max_output_tokens`, `generation_deadline_s`, `payment_timeout_s`, `proof:
"unavailable"`, `available`, and optional `hardware`. Consult `examples/free-lab.json`
for a complete structure. Replace the fixture manifest for a real backend.

## Buyer CLI

Get the provider's public identity and exact model ID from its dashboard. The public
`/v1/providers` response also provides derived model IDs alongside signed offers.
Buyers verify the signed quote, not the listing's unsigned convenience fields.

```sh
.venv/bin/python -m offence.cli buy http://127.0.0.1:8080 \
  --provider PROVIDER_PUBLIC_KEY --model-id MODEL_SHA256 \
  --prompt 'Explain peer discovery.' --max-tokens 64 --max-msat 0 \
  --allow-lab-unverified
```

Without the explicit lab option the buyer refuses because execution proof is
required. Keep `--max-msat 0` for free experiments. The `fixture` backend emits fixed
text solely to test the protocol; it is not a language model.

## Lightning regtest

Only a separate bitcoin regtest wallet is accepted. Mainnet, testnet, and signet are
rejected by the adapter. Do not copy production wallet credentials into this lab.
LND credentials are supplied through environment variables pointing to private files:

- `OFFENCE_LND_URL`: HTTPS REST origin of your regtest LND instance.
- `OFFENCE_LND_MACAROON_FILE`: path to the binary macaroon with the required invoice
  or payment permissions. Use separate limited provider and buyer credentials.
- `OFFENCE_LND_TLS_CERT_FILE`: path to its trusted TLS certificate.
- `OFFENCE_BACKEND_API_KEY`: optional GPU server credential.

The provider needs getinfo, invoice creation, and invoice lookup. The buyer needs
getinfo, invoice decoding and synchronous payment. Configure provider
`lightning: "lnd-regtest"`, explicit lab opt-in, and a positive output-token price.
StartOS Configure Payments supports direct LND and Strike receiving. See
`docs/PAYMENT-READINESS.md` for required credentials, scopes and explicit buyer opt-in.

The buyer's `--lnd-regtest` option reads the environment variables, and
`--fee-limit-msat` caps routing fees PER BATCH. The quote cap covers inference charges;
routing fees are additional. No payment is made by installation, discovery, or viewing
the dashboard. The buyer only pays within an explicitly invoked purchase.

## Recovery and evidence

Buyer files are written with mode 0600. Preserve the directory containing identity,
signed quotes, encrypted batches, payment results and receipts. The provider stores
no prompt in its database. Backend servers may have their own logging policy.

For direct LND, if payment succeeded but the connection failed, the buyer's saved ciphertext and
wallet payment preimage can decrypt the batch without another provider response.
The Python helper `offence.crypto.unseal` performs authenticated decryption. If the wallet
response was lost, retrieve that original payment's result from LND using its payment
hash. Do not create a replacement payment. Automated wallet reconciliation is a
production release requirement.

A signed POST to `/v1/recover` with body `{type: "recover", session: SESSION_ID,
issued: CURRENT_UNIX_SECONDS}` returns that buyer's retained ciphertext and bilateral
records. The service retains ordinary records for seven days. Hosted settlement sessions and private keys are retained for recovery beyond that period, subject to the database size cap. It does not expose payment
preimages in this endpoint. Restart interrupts generation; it does not resume a model's
internal state or charge for unseen work.

`/v1/track-record` returns signed provider-local statistics with sample counts.
`/v1/evidence` exposes portable bilateral records only when `share_receipts: true`
is set in the operator config. This reveals counterpart public keys and trading
relationships. It is disabled by default. `offence.evidence.verify_delivery` checks both
signatures and binding; it reports no execution, settlement, or Sybil guarantee.

## Packaging and deployment

Run Python tests, the three-node smoke test, TypeScript checks, and the bundle build.
The pinned SDK includes two npm-audit findings in bundled lint tooling; see the
validation report for their scope and disposition. Do not claim a clean audit.

Before every s9pk pack: bump `startos/versions/index.ts`, confirm secrets and artifacts
are ignored, record the source state, and run `scripts/preflight.py`. Use the user's
existing signing key in ignored `.startos/build.key.pem`; never print or commit it.
Build through the Linux start-cli in Colima. Uncommitted builds must have a source-file
hash snapshot created with `scripts/snapshot.py`. A commit and push require approval.
No command in this project deploys a package to a server automatically.

The package definition includes both x86_64 and aarch64. Select the architecture
matching the destination server. Installation and real network reachability must be
verified on that server before calling it deployed or operational across StartOS nodes.

## Agent access and supplier protection

Use Configure Node to select vLLM, its fixed origin, served-model identifier and model offer. Supplier limits bound admitted requests, context reservations, concurrent sessions and storage. Use Configure Buyer API to set pinned model aliases and a private key. The dashboard shows the agent base URL. The buyer API accepts text chat in free lab mode; paid purchases, tools and media are rejected. See docs/AGENT-API.md and docs/PROVIDER-SECURITY.md in the source for the exact contract and deployment limits.

## Automatic provider selection and split jobs

In Configure Buyer API, add a routing policy with an alias and exact allowed model
IDs. Choose balanced, cheapest, fastest or preferred-model ordering. For sensitive
work, restrict the policy to explicitly trusted provider identities. An agent can
use the policy alias as its chat model, or submit independent subtasks to /v1/jobs
with a shared output allowance and idempotency key. See docs/JOBS.md for the request
contract. All payments remain disabled in the buyer API.
