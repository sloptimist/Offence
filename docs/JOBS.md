# Automatic routing and split jobs

The harness plans a larger job, sends an independent wave of subtasks to Offence,
checks the results and combines them. If a later step needs earlier results, the
harness constructs a new wave with only the context that later step needs.
Offence does not infer dependencies, rewrite prompts or execute model output.

## Operator policies

Configure Buyer API accepts routing policies alongside optional pinned routes.
Each policy has a unique alias, exact allowed model IDs, and optional provider
restrictions. Policies also work as the `model` value in ordinary chat requests.

```json
{
  "alias": "balanced",
  "model_ids": ["<exact-model-manifest-hash>"],
  "strategy": "balanced",
  "privacy": "any",
  "max_output_tokens": 512,
  "min_context_tokens": 4096
}
```

Replace placeholders with actual identities. `providers` can restrict eligible
provider public keys. For private tasks, set `privacy` to `trusted-only` and list
`trusted_providers`. A request may tighten privacy with `trusted_only: true` but
cannot relax an operator restriction. A pinned route alone is not an explicit
trust declaration, so trusted-only subtasks require a policy.

Only unexpired, validly signed offers with a permitted exact model, text-chat
capability, adequate context/output capacity and an allowed network address are
eligible. Local/DNS endpoints still require Approved LAN peers; onion endpoints
require a configured Tor proxy. Eligible advertisements are claims, not execution
proofs. Required-proof requests fail closed. Free-lab mode excludes all nonzero
prices before sending context; a later paid quote is also rejected before acceptance.

| Strategy | Ordering after eligibility checks |
| --- | --- |
| cheapest | Price, current local load, recent failures, model preference, latency |
| fastest | Current local load, locally observed time to first delivery, model preference |
| preferred-model | Operator's ordered model IDs, load, recent failures, latency |
| balanced | Current local load, recent failures, model preference, latency |

Provider identity breaks ties deterministically. Unknown latency ranks after known
latency; there is no background benchmarking or automatic exploration traffic.
Statistics are buyer-local observations, expire after seven days, and are never
accepted from provider ratings. Failed delivery causes a short cooldown. Client
cancellation does not count as supplier failure. Preferred-model is an operator
preference, not a network quality certification. All eligible prices currently
have to be zero, so paid-market price optimization is not claimed.

No match means no dispatch. Offence never expands the allowed model/provider set
or weakens privacy to complete a job. Policy selection tries to spread concurrent
requests across eligible providers but does not guarantee different providers when
restrictions leave only one eligible supplier.

## Submit independent subtasks

Use the same private bearer key as the chat API. `POST /v1/jobs` returns HTTP 202
with a job ID and initial status. Subtasks carry separate message arrays; there is
no automatically copied global context or inter-provider result sharing.

```json
{
  "idempotency_key": "report-wave-000001",
  "proof_policy": "lab-unverified",
  "max_total_msat": 0,
  "max_total_output_tokens": 768,
  "max_parallel": 2,
  "max_retries": 1,
  "deadline_s": 120,
  "tasks": [
    {
      "id": "section-a",
      "model": "balanced",
      "messages": [{"role": "user", "content": "Summarize section A: ..."}],
      "max_tokens": 256
    },
    {
      "id": "section-b",
      "model": "balanced",
      "messages": [{"role": "user", "content": "Summarize section B: ..."}],
      "max_tokens": 256
    }
  ]
}
```

The default proof policy is `required`; the example explicitly selects unverified
lab work and still requires the operator to enable free-lab mode. Tools, media,
dependency definitions, arbitrary endpoint overrides and nonzero payment budgets
are rejected. Keep prompts within the text-chat API's limits.

- `GET /v1/jobs/{id}` returns progress, partial/final text, actual provider and model
  identities, per-attempt protocol session IDs, received tokens and reserved work.
  Session IDs link to the buyer's retained signed quote, batch and receipt files.
- `POST /v1/jobs/{id}/cancel` cancels queued/running work and closes active streams.
- Repeating an identical idempotency key and request returns the saved job without
  repeating inference. Reusing a key for a different request returns HTTP 409.
- Terminal states are `complete`, `partial`, `cancelled`, `timed-out`, `failed` or
  `interrupted`. `partial` means at least one subtask failed; inspect each task.
  Results are untrusted data for the harness to validate before use.

A job continues if the submitting HTTP connection closes after acceptance. Use
the cancellation endpoint to stop it. On service restart, unfinished jobs become
interrupted and are never automatically resubmitted. A new attempt requires a new
idempotency key and a fresh quota reservation.

## Shared budgets and supplier protection

The full job allowance is reserved durably against the rolling daily quota before
work starts, in the same database transaction as job creation. Initial attempts
are protected from retries: the example reserves 512 tokens for the first wave and
256 for at most one retry. Every dispatched attempt consumes its full requested
allowance even if it fails. Delivered token counts are reported separately. No
monetary spending is enabled and no wallet is available to this gateway.

Retries use a different eligible provider, stop when the retry allowance is
exhausted, and never replay a partially delivered subtask. Partial text and signed
records are retained. Ordinary chat and jobs share the gateway's concurrency and
daily quota. Supplier-side admission limits remain independent and authoritative.
Closing a connection requests runtime cancellation; this does not prove immediate
GPU release or eliminate unpaid computation in free lab mode.

Defaults are two active jobs, sixteen tasks per job, up to one permitted retry
(requests default to zero), a 16,384-token job ceiling and 120-second deadlines.
The daily default allowance is 10,000 tokens, so it can further restrict a job.
Job result text is capped at 64 KiB per subtask and approximately 1 MiB per job;
exceeding the cap stops that subtask while preserving its signed delivery records.
At most 128 jobs are retained for seven days; job admission fails when retention
or storage limits are reached. Quota reservations are not refunded on failure.

All holders of a gateway's bearer key share its job records, policies and limits.
This is a private owner-controlled gateway, not a multi-tenant account service.
Trusted-only routing restricts recipients but does not encrypt data against the
selected provider. Use TLS/Tor as appropriate; an approved LAN HTTP origin still
exposes plaintext to that network. Splitting a job is not a confidentiality proof.

## Lab compatibility

Automatic routing requires the signed `text_chat` offer capability introduced in
0.1.0:4. Older offers without that flag are not selected automatically. Older lab
nodes may reject advertisements carrying the new field; upgrade participating
providers and buyers together, or use explicitly configured compatible routes.
This is a lab protocol addition, not a promise of backward-compatible discovery.
