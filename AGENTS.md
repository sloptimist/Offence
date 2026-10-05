# Offence

Permissionless inference service, initially packaged for StartOS and Linux Docker.
The project name is Offence. Product requirements are in SPEC.md and the
source-backed network comparison is in docs/RESEARCH.md.

## Rules

- No central registry, admission authority, mandatory intermediary, or native asset.
- Each provider runs complete inference. Charge for delivered output tokens,
  including tokens delivered before a later failure. Buyers select providers.
- Model manifests identify exact files independently of a hosting website.
- Model accuracy is a seller claim judged through buyer-local reputation and checks.
- Execution proof is optional, not a payment prerequisite. Signatures/hashes are not execution proof.
- Honor explicit proof-required buyer policies without silently downgrading them.
- Keep lab payment simulations and regtest separate from production.
- Keep task planning and result combination in the harness. Offence routes independent waves.
- Routing never relaxes model/trust policy; retry allowances cannot consume initial-task reservations.
- Supplier protection takes priority: bound admitted work, runtime privileges and backend access.
- The node-hosted gateway is text-only and free-lab-only. The standalone buyer app
  supports budgeted LND and NWC payments; neither passes through unsupported parameters.
- NWC inference limits exclude routing fees; the owner must accept wallet-managed fees and set a wallet allowance.
- NWC connection secrets are owner-only local files; preserve uncertain-payment recovery and never resend on timeout.
- Buyer owner and agent keys are separate. Agent requests cannot alter owner policy.
- Buyer launch binds to loopback and locks its data directory. Do not expose it publicly.
- StartOS initializes /data/runtime before running as UID 10001; preserve identity on upgrades.
- StartOS reports the requested readonly config mount as rw; root-owned permissions protect it.
- Live StartOS has NoNewPrivs=0; do not claim Docker hardening flags apply to LXC.
- No em dashes. Secrets belong in ignored runtime files, never source or logs.
- The operator explicitly approves GitHub commit, push and releases for Offence
  under smallblocks, as a project exception to the workspace Gitea-only rule.
- Docker Actions artifacts are downloadable image archives retained 30 days, not GHCR images or s9pk releases.
- Keep operational records in ignored .private/ and .startos/, never in public source.
- Do not deploy without a concrete review.
- Bump the package revision before every s9pk pack; use release preflight.
- start-cli 1.1.0 can pack without a Git commit (manifest gitHash is null). Record
  scripts/snapshot.py hashes for uncommitted builds; commit/push still require approval.
- StartOS exposes the interface over HTTPS on its assigned SSL port.
  Plain HTTP is available internally, not on the LAN by default.
- Run `.venv/bin/python -m pytest` and `npm run check` for relevant changes.
- Strike provider-key-v1 requires explicit buyer opt-in and supplier availability for key recovery; never claim offline decryption for hosted settlement.
- Hosted keys and sessions survive routine cleanup; preserve the database with the node identity.
- End sessions using the handoff procedure and replace Current state, max 15 lines.

## Current state

- Supplier package revision 0.1.0:10 remains the experimental public StartOS release.
- Buyer supports loopback UI/API, signed discovery, LND and NWC mainnet wallet connection.
- NWC connects without spending; owner enables budgets and explicitly accepts wallet-managed fees.
- UI prices are sats; API and storage amounts remain integer msat.
- Wallet secrets stay local and separate from agent keys; disconnect preserves uncertain-payment recovery.
- 187 tests and TypeScript pass, including encrypted NWC SDK transport and recovery tests.
- Buyer runtime audit, privacy scan, fresh macOS install, Linux ARM64 smoke and browser checks pass.
- Buyer download requires Python 3.12+; live NWC funds and Windows launch remain unvalidated.
- Buyer release buyer-v0.1.0-alpha.2 and offence.ai download are live with matching checksums.
- GitHub Actions builds and smoke-tests AMD64/ARM64 Docker images; run 37259879618 passes with both archives uploaded.
- README and offence.ai explain agent-first buyer access and downloads; paid-marketplace readiness is separate.
- Node-hosted gateway/jobs remain free-only; paid split jobs and tool calls are unsupported.
- Live checks: both wallets disabled; Sandy has no backend/offer; Boxed offer unavailable with discovery error.
- Both nodes have saved Strike keys; fractional-millisatoshi billing and live payment validation remain open.
- Live supplier deployments remain revision 9; this buyer update does not sideload them.
