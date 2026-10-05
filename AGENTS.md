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
- Agent API is text-only and free-lab-only; never silently pass through unsupported parameters.
- StartOS initializes /data/runtime before running as UID 10001; preserve identity on upgrades.
- StartOS reports the requested readonly config mount as rw; root-owned permissions protect it.
- Live StartOS has NoNewPrivs=0; do not claim Docker hardening flags apply to LXC.
- No em dashes. Secrets belong in ignored runtime files, never source or logs.
- The operator authorizes a public GitHub release under smallblocks after the security sweep.
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

- Experimental revision 0.1.0:10 is built for both architectures after the initial security review.
- 160 tests, TypeScript, discovery, free gateway/jobs and LND regtest recovery pass.
- Both packaged application payloads match reviewed source; restricted Docker smoke passes.
- Two SDK development-tooling advisories remain; affected modules are absent from the bundle.
- Public discovery and signed streaming work; execution proofs remain unavailable.
- Paid direct CLI is separate from the free-only agent gateway and jobs.
- Fractional pricing, live hosted settlement and StartOS isolation acceptance remain open.
- Last verified live deployments use revision 9; revision 10 is not sideloaded.
- Source publication targets smallblocks/Offence; preserve the existing LICENSE commit.
- Next product phase: offence.ai buyer download, local agent API, enforced buyer preferences.
- Private deployment and release evidence remain in ignored .private/ and .startos/.
