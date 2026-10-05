# Roadmap

## Agent access and supplier protection

- Deployed 0.1.0:5 includes policy routing, independent subtask waves, durable shared
  quotas, bounded retries and cancellation. The harness retains planning and combination.
- Improve capability/version negotiation before expanding mixed-version lab discovery.
- Investigate StartOS ignoring the requested read-only config mount and enforce
  no-new-privileges for its daemon before wider distribution. Migration and non-root
  startup pass on both architectures; filesystem ownership currently protects configuration.
- Complete real model artifact hashing and a full StartOS buyer/provider test against
  the selected dual-Spark DeepSeek model. Direct live adapter inference passes.
- Add explicitly negotiated tool-call, structured-output and reasoning contracts with
  exact token attribution. Do not silently enable backend parameter passthrough.
- Implement persistent monetary reservations and total routing-fee limits only when the
  payment protocol is ready. The current gateway cannot spend funds.
- Measure backend cancellation and worst-case unpaid GPU work under disconnect/payment
  failure. Add sustained resource-exhaustion and Sybil-load tests before public use.
- Audit OS egress restrictions and backend containment separately from application limits.

## Next integration work

- Complete the security and privacy sweep before the authorized public GitHub release.
- Configure the selected GPU backend and peer through the installed Configure Node action.
- Exercise a real model completion, backup/restore, and restart recovery on StartOS.
- Connect two independently operated StartOS nodes through actual onion services and
  a configured outbound SOCKS proxy. Verify reachability, expiry and reconnects.
- Resolve the pinned SDK's bundled lint dependency audit findings before wider distribution.

## Optional proof research

- Pick a small openly licensed model with explicit deterministic numerical semantics.
- Prototype a FOSS verifiable-computation pipeline, starting with EZKL feasibility.
- Pin model conversion, tokenizer, configuration and runtime semantics. Prove that the
  committed artifacts correspond to the proved computation.
- Bind request context, generated tokens, decoding, encrypted output and payment hash
  in the verified statement. Reject substituted ciphertext and replayed proofs.
- Benchmark generation, proof, verification, proof bytes, RAM/VRAM and concurrency.
- Obtain independent review of the protocol and proof circuit.
- Keep proof-required purchases blocked if any binding or performance test fails.
- Reputation-based purchases do not require execution proofs.

## Payments and recovery

- Implement explicitly negotiated seller-claim assurance for reputation-based payments.
  Signed direct purchases now negotiate seller-claim assurance; proof-required refusal
  and mainnet/regtest separation are implemented. Extend this to paid gateway/jobs.
  Display claimed model identity separately from cryptographically verified execution.

- Run two real regtest LND nodes, route payments, interrupt at every state boundary,
  and verify invoice timeout, wrong amount, unknown outcome, and key recovery.
- Buyer payment intents now persist before dispatch; operator-invoked regtest recovery
  reconciles by hash without resending, also before CLI purchases. Provider reconciliation
  runs periodically. Extend reservation release for reconciled partial sessions.
  See docs/PAYMENT-READINESS.md for release evidence.
- Add a total session routing-fee budget, not only a per-batch fee limit.
- Measure batch size against proving latency, payment latency and routing constraints.
- Evaluate bounded-work anti-abuse measures without a membership admission authority.
- Review whether another streaming settlement construction improves economics without
  introducing custody or silently weakening buyer-selected assurance requirements.

## Discovery and reputation

- Add tried/new peer buckets, endpoint reachability checks, independent source quotas,
  network diversity, anti-eclipse tests, and bounded persistent storage under Sybil load.
- Add safe ordinary DNS resolution with rebinding protection and transport identity checks.
- Add a model-keyed DHT if measured offer volume requires it; do not introduce a global registry.
- Support multiple model offers per provider and negotiated protocol capabilities.
- Share evidence on demand, separate local observations from signed claims, and test
  fake trading, selective disclosure, receipt withholding, identity resets and spam.
- Add buyer-local latency distributions, delivered-token reliability and provider pinning.
- Consider optional Nostr/Routstr interoperability without making relays or mints mandatory.

## Product extensions

- OpenAI-compatible buyer gateway with explicit model/provider selection and spend limits.
- Chat templates, tool calls, cancellation, and billing rules for non-text/reasoning output.
- Additional token-ID-capable inference backends and separately versioned adapters.
- Better StartOS forms for model artifacts and optional regtest dependency configuration.
- Model publisher verification and optional artifact distribution, independent of any website.

## Model readiness and context

- Gate supplier availability on completed backend warmup, not only an open API port.
  The second node cold kernel compilation exceeds the adapter's 60-second read timeout.
- Expand bounded request/context admission before offering 180k prompts through
  Offence. The second node vLLM passes 180000-token capacity, but current Offence input
  limits remain substantially lower. Preserve supplier resource and spend caps.

## Hosted wallet receiving

- Strike address configuration and explicit supplier-key settlement are implemented.
  Complete live read-only account validation, then an authorized payment smoke test.
- Add additional wallets or generic LNURL only with authoritative settlement checks
  and explicit recovery guarantees. See docs/PAYMENT-READINESS.md.
- Define an acknowledged hosted-key retention/pruning policy and backup acceptance tests.

## Approved Venice comparison pricing

- Operator selected 50% of Venice output-token rates on 2026-10-04. DeepSeek V4
  Flash 0731 target: USD 0.175/million output tokens (Venice USD 0.35). Qwen3.8
  27B Uncensored target: USD 1.60/million output tokens (Venice comparable Qwen
  3.8 27B USD 3.20; exact weight equivalence is not established). Input remains
  unbilled under the delivered-output policy. Source: https://docs.venice.ai/models/text
- Exact targets and receiving address are staged privately in
  `.startos/operator-pricing-policy.json`. Decimal sats/token drafts and the address are now saved in both live payment forms, with payments disabled.
- Replace per-token integer-msat rounding with explicitly negotiated cumulative
  batch pricing before activation. Bound total rounding error, avoid zero-value
  invoice/free-key confusion, and test partial/final batches and buyer budgets.
- The bootstrap node has the saved Strike API credential and passes authenticated receiving-profile validation for the selected address. Invoice creation/settlement remain untested live. Keep payments disabled until precise pricing and backend readiness pass.

## Buyer storefront and downloadable app

- Keep the offence.ai buyer download and checksum aligned with reviewed releases.
- Add signed native installers to remove the Python prerequisite from the buyer
  download. Validate the Windows launcher before claiming Windows support.
- Let the buyer set allowed models, maximum prices and spending limits, latency
  preferences and trusted-provider/privacy restrictions. The agent selects only
  suppliers permitted by those rules and connects directly to them.
- Keep discovery replaceable and multi-seed. The storefront is not a mandatory
  broker, directory, custodian or inference relay.
- Preserve supplier quotas and bounded work while adding negotiated tool support
  and paid independent-job routing to the standalone buyer app.
- Show and require explicit approval of a spending policy before the agent can
  purchase inference. Keep supplier advertisements separate from verified results.
- Keep wallet secrets and spending enforcement in the local buyer service. A remote
  supplier receives only the request context that the buyer authorizes, with no
  permission to read local files or execute tools on the buyer computer.
- Privacy preferences restrict eligible suppliers and context disclosure. Splitting
  a job does not itself make it private; the harness must choose what each supplier
  receives and must not silently weaken those preferences to obtain a lower price.
