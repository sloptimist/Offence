# Network and inference review

Research date: 2026-10-04. This review uses project documentation and source code.
It distinguishes advertised capabilities from properties demonstrated in our tests.
Upstream repository links are research citations, not project remotes.

## Recommendation

Build a small independent protocol with signed, expiring model offers, replaceable
bootstrap peers, local provider selection, direct inference sessions, and direct
Lightning settlement. StartOS hosts the network service; a GPU machine on the
operator's network runs a complete model. Do not introduce a new blockchain,
network asset, admission authority, global rating authority, or mandatory mint.

Keep cryptographic execution proof as a production requirement. The user explicitly
approved building a lab while paid production remains blocked. Neither a model
hash nor a provider signature establishes which computation ran.

## How Bitcoin Core connects

### Bootstrap and address exchange

A node needs at least one route into the network. Bitcoin Core can obtain addresses
from its saved peer database, DNS seeds, fixed seeds, and explicitly supplied peers.
After connecting, peers exchange addresses. Seeds introduce candidates; they do not
approve membership or determine transaction validity. Seed responses are not a
trusted consensus source. A hostile introduction can still isolate a newcomer.
[Bitcoin developer guide](https://developer.bitcoin.org/devguide/p2p_network.html),
[Core connection implementation](https://doxygen.bitcoincore.org/net_8cpp.html).

Bitcoin Core's address manager separates newly learned addresses from addresses
that have worked, uses bucketed storage, and persists its cache. This is more than
broadcasting every known address to everyone. The distinction helps keep untested
addresses from displacing the whole useful peer set.
[Address manager implementation overview](https://bitcoincore.academy/addrman.html).

Core distinguishes inbound, outbound full relay, block relay, manual, address-fetch,
and feeler connections. These have different purposes. An inference network can
borrow bounded peer selection and probing, but Bitcoin's block-relay rules are not
an inference marketplace specification.
[Core connection types](https://doxygen.bitcoincore.org/connection__types_8h.html).

### Reachability is separate from discovery

Running Bitcoin Core does not automatically make a machine reachable by every
other node. Outbound connections generally work behind NAT; inbound service may
need firewall rules and router port forwarding. An address learned through gossip
is only a candidate, not proof that it is reachable.
[Bitcoin full-node connectivity instructions](https://bitcoin.org/en/full-node).

Core also supports onion services and can create one using an authenticated Tor
control connection. This is a useful analogy for StartOS: inbound onion service and
outbound Tor proxy are separate configuration concerns. Tor is an optional transport,
not the membership authority.
[Bitcoin Core Tor documentation](https://github.com/bitcoin/bitcoin/blob/master/doc/tor.md).

### What to copy and what not to copy

Adopt independent identities, manual peers, cached discovery, bounded address
exchange, retries, expiry, diverse peers, and local validation. Avoid a central
provider registry. Do not copy Bitcoin's proof of work or add a chain merely to
maintain a marketplace directory. Offer discovery does not need a universally
ordered ledger, and bilateral reputation need not be globally agreed.

The initial HTTP gossip design is intentionally smaller than Core's network stack.
It does not claim Core's eclipse resistance, peer diversity, tried/new buckets,
connection eviction policy, or scale. Those are explicit hardening requirements
before an adversarial public network, not properties inherited by analogy.

## What BitTorrent contributes

BitTorrent's BEP 5 specifies a Kademlia-style UDP distributed hash table. An infohash
is a lookup key used to find peers; it is not itself a network address. Routing
buckets, node queries, and peer announcements make trackerless discovery possible.
The routing table favors responsive nodes and can be persisted across restarts.
[BEP 5](https://www.bittorrent.org/beps/bep_0005.html).

An exact model manifest hash can serve as the analogous lookup key. A DHT becomes
useful when scanning a bounded local offer cache is insufficient. We should not
claim the first gossip implementation is a DHT. Nor does a DHT make NAT disappear.
BitTorrent's DHT security extension also illustrates why freely chosen node IDs
need adversarial analysis, not just a hash function.
[BEP 42](https://www.bittorrent.org/beps/bep_0042.html).

## Existing systems

| System | Relevant mechanism | Fit and mismatch with this project |
| --- | --- | --- |
| Routstr | Permissionless inference marketplace, Nostr announcements, Cashu payment workflow | Closest product overlap. Reuse lessons about discovery and provider integration; its documented mint/payment model differs from direct Lightning without a mandatory intermediary. |
| Nostr data vending machines | Signed processing requests, results, status, payment coordination through relays | Useful optional interoperability. Relay discovery is different from the requested provider-to-provider gossip network. |
| Petals | Internet participants serve different transformer layers | Strong distributed-compute reference. It solves model partitioning, while this project sells whole inference from one provider. |
| exo | Distributed local inference across devices | Useful GPU-side execution option; not by itself the discovery, billing, and proof contract required here. |
| Gensyn | Network infrastructure, reproducible execution and verification tooling | Valuable verification research. Current REE documentation explicitly includes proprietary components, so it cannot be a required dependency under this project's FOSS requirement. |
| Gonka | Inference hosting and purchasing in GNK | Relevant marketplace and validation research; GNK settlement differs from the required Lightning-only economic model. |
| Bittensor | Subnets, miners, validators and incentive mechanisms | Shows alternative reputation/incentive designs. Validator and emission economics differ from bilateral seller prices and direct token purchases. |
| Lightning L402 | Lightning payment proof used to authorize API access | Useful API authentication/payment building block. Access authorization does not prove model execution or guarantee that response data arrived. |

Sources supporting the comparison:

- [Routstr documentation](https://docs.routstr.com/) and
  [provider discovery](https://docs.routstr.com/provider/discovery/).
- [NIP-90 specification](https://github.com/nostr-protocol/nips/blob/master/90.md).
- [Petals implementation and linked papers](https://github.com/bigscience-workshop/petals).
- [exo implementation](https://github.com/exo-explore/exo).
- [Gensyn REE documentation and license notice](https://docs.gensyn.ai/tech/ree).
- [Gonka official project](https://gonka.ai/).
- [Bittensor subnet guide](https://www.bittensor.com/docs/guides/subnets).
- [Lightning Labs L402 discussion](https://lightning.engineering/posts/2023-07-05-l402-langchain/).

These are architectural comparisons, not throughput benchmarks or claims that each
project lacks every feature absent from its overview. No existing implementation
reviewed here demonstrates all of this project's requirements together.

## Cryptographic model execution

### Identification

A model identity should commit to exact weights, tokenizer, configuration, adapters,
quantization, and any template or runtime artifact that changes the computation.
Repository revisions and file digests help locate and check artifacts. Mirror URLs
must not control identity. Hashes checked against a publisher establish agreement
about bytes, not evidence that a remote GPU used those bytes.
[Hugging Face cache and file identity](https://huggingface.co/docs/hub/en/local-cache).

### Candidate approaches

| Approach | What it can establish | Dependency or limitation |
| --- | --- | --- |
| Signed manifest or receipt | A particular key made a statement | Does not establish execution correctness |
| Challenge requests or independent re-execution | Evidence of consistency under the chosen tests | Statistical testing is not a proof for every purchased response; exact re-execution has a cost |
| Hardware attestation | Claims about a measured protected environment, subject to its trust roots | Requires supported hardware and a complete binding from runtime and weights to session output; a GPU firmware report alone is insufficient |
| Verifiable computation / ZK circuit | Correct execution of the statement encoded by a validated circuit | Needs supported operators, exact numeric semantics, model binding, and affordable proving latency |

NVIDIA's attestation tooling verifies hardware/software claims and requires supported
confidential-computing configurations. This is a different trust model from
hardware-independent computation proofs. No assumption is made that an operator's
existing GPU supports it.
[NVIDIA attestation overview](https://docs.nvidia.com/attestation/index.html),
[SDK requirements](https://docs.nvidia.com/attestation/attestation-client-tools-sdk/latest/gpu_and_switch_attestation.html).

EZKL translates ONNX computations into proof circuits and supports proof generation
and verification. That makes it a candidate for a small-model feasibility experiment,
not evidence that arbitrary current LLMs can be proved at interactive token speeds.
Conversion and numeric approximation must also be specified: proving a transformed
circuit is not automatically proving an unmodified publisher model.
[EZKL documentation](https://docs.ezkl.xyz/).

A production proof must bind the model, tokenization, request, accumulated context,
sampling rules, position in the stream, output token IDs, and decoding. For encrypted
payment batches it must also bind the ciphertext to that output and to the payment
hash. Otherwise a valid proof could accompany unrelated ciphertext. The feasibility
experiment must measure that whole construction, or explicitly identify which part
remains unproved.

## Lightning and streaming economics

LND supports invoices with caller-supplied payment preimages, millisatoshi values,
and description hashes. The buyer can decode an invoice and compare its amount,
payment hash, commitment, expiry, and network before paying.
[LND AddInvoice](https://lightning.engineering/api-docs/api/lnd/lightning/add-invoice/),
[LND DecodePayReq](https://lightning.engineering/api-docs/api/lnd/lightning/decode-pay-req/).

The lab experiment encrypts a small output batch using a key derived from the
invoice preimage. The buyer stores ciphertext before paying; successful payment
reveals the preimage needed to decrypt it. This favors protecting the provider from
releasing useful plaintext without payment. It still permits unpaid computation:
a buyer can abandon a prepared batch. It also permits garbage delivery without the
missing execution/ciphertext proof. This is not a complete fair-exchange proof.

Small batches trade latency against payment overhead. Eight tokens is an initial
lab default, not an economically optimized value. At 40 generated tokens per second,
filling eight tokens adds about 200 ms before payment latency and proving time.
This is arithmetic for an example, not a measured benchmark. Fees, routing failures,
minimum HTLC constraints, liquidity and Tor latency must be measured with actual
Lightning nodes before choosing production defaults.

Previously delivered and paid tokens remain payable if a later batch fails. An
unpaid invoice expires; that is not a refund of settled funds. A settled Lightning
payment cannot simply be relabeled failed and reversed. Any return payment is a
separate transaction. The design avoids charging for future generation and does not
promise automatic refunds for bad model output.
[Lightning payment lifecycle](https://docs.lightning.engineering/the-lightning-network/multihop-payments/the-payment-cycle).

## Decisions and unresolved work

Proceed with independent peer discovery, whole-model providers, buyer-selected
quotes, exact artifact manifests, and a StartOS control service linked to a LAN GPU
backend. Keep proof-required buyers and production payment gates closed. Use free
lab inference and regtest to test protocol behavior.

Before a production design can be approved: demonstrate a FOSS proof system for one
specific model; measure per-batch proof and verification cost; bind proof to encrypted
delivery; perform real Lightning interruption/recovery tests; and harden discovery
against eclipse, Sybil, resource-exhaustion, and address-poisoning attacks. These are
engineering release gates, not reasons to substitute reputation for proof.
