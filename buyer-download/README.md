# Offence Buyer

A local buyer app for the Offence provider graph. No GPU or supplier node required.
This is an experimental text-chat client, not a general tool-calling coding harness.

## Start

1. Install Python 3.12 or newer from https://www.python.org/downloads/.
2. Extract this entire download into a folder you own.
3. On macOS run `Start-Offence.command`; on Windows run `Start-Offence.cmd`;
   on Linux run `sh start-offence.sh`. A terminal alternative on any platform is
   `python3 launch.py` (Windows: `py -3 launch.py`).
4. The first launch installs pinned dependencies from PyPI into this folder.
   Subsequent launches reuse that environment. The local browser screen opens.
5. Refresh the graph, select model hashes and set your supplier preferences.
   Explicitly choose an assurance mode. Requiring proof blocks requests because
   execution proofs are unavailable. Free lab and mainnet use separate networks.
6. Save the policy. Give your agent the displayed base URL, agent key and model
   `auto`. Never give it the private owner link or owner key.

Use `--no-browser` for headless operation or `--port 8788` for a different local port.
Close with Ctrl+C in the terminal. Keep the terminal running while your agent uses
inference. This is a Python-based download, not a signed native installer.

## Payment wallet

All spending defaults to zero. The app supports free lab inference, LND regtest,
and explicitly enabled LND mainnet purchases. Strike receiving addresses do not
provide spending authority. A buyer needs an LND node with usable channel balance.

Set these environment variables locally before launching:

- `OFFENCE_LND_URL`: your wallet's HTTPS REST origin.
- `OFFENCE_LND_MACAROON_FILE`: path to a least-privilege payment-capable macaroon.
- `OFFENCE_LND_TLS_CERT_FILE`: path to the wallet's TLS certificate.

Then select the matching wallet network in the app and save to verify it. The
supplier never receives these credentials. Wallet errors leave spending blocked.
Buyer recovery reconciles existing payment intents at startup without resending.
Hosted supplier-key settlement requires explicit owner opt-in. Its key recovery
still requires that supplier; use `python -m offence.cli recover-hosted-keys` with
this app's purchases directory and the chosen endpoint/provider for recovery.

Prices and limits use integer millisatoshis: 1,000 msat is one sat. The request
cap covers output; the daily cap includes reserved routing fees. Fee budgets must
cover one batch per requested output token. Reservations deliberately remain
conservative, and uncertain purchases keep their reservation. Reconciliation recovers payment
state but does not automatically release an interrupted session reservation.
No automatic retry or fallback purchase occurs after a failed paid stream.
Ambiguous paid failures do not count against supplier reputation: the cause may
be the buyer wallet or a local spending limit.

The displayed token total counts verified output received by the local app, not
proof that a downstream agent consumed it. Output cost excludes routing fees and
payments whose output has not been recovered. Local signed purchase records are
authoritative evidence of partial and interrupted sessions.

## Security and privacy

The server binds only to 127.0.0.1, rejects foreign Host/Origin headers, and keeps
owner and agent keys separate. Agent requests cannot set endpoints, increase
budgets, run tools, or read files. Text returned by a supplier remains untrusted;
your agent harness must enforce its own tool permissions. This app is not an OS
sandbox against other software already running under your account.

State is stored under `~/.offence-buyer` by default. Back up the whole directory
privately, especially identity and purchase records. Never put it in a web folder
or source repository. Deleting it resets identity, evidence and spending history.
Do not run copies of this directory concurrently on different machines.

The default seed is https://offence.ai. Add other seeds and approve their exact
DNS/private origins locally. Public IP HTTPS and configured Tor origins follow
peer validation. A seed is not a mandatory intermediary. Suppliers receive the
context you send; splitting a task does not make that context private.

API: authenticated `GET /v1/models`, `GET /v1/providers`, and
`POST /v1/chat/completions`. Text system/user/assistant messages, `max_tokens`,
`stream`, `temperature: 0`, and `n: 1` only. Input is bounded to 16 KiB. Tools,
images, arbitrary parameters and paid split-job execution are not supported.
