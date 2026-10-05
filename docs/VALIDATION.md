# Validation

The initial experimental-release review is complete. Findings and acceptance gates
are recorded in SECURITY.md. Private deployment transcripts, machine addresses,
node identities and operational history are excluded from source publication.

The existing suite contains 160 tests covering protocol, discovery, token counters,
wallet recovery, supplier admission, gateway authentication, routing and split jobs.
Real Bitcoin/LND regtest exercises direct and supplier-key payment recovery without
resending payments. Strike API tests are mocked; account-profile validation alone
does not establish invoice creation or settlement correctness.

Re-run the complete test suite, TypeScript check, smoke tests and dependency scans
after security changes. Record the reviewed source snapshot and package checksums
before a release. Passing these checks is not a guarantee against unknown attacks.

Revision 10 checks pass for pytest, TypeScript, the three-node discovery smoke,
free agent gateway, split-job routing, and real LND regtest recovery. Python
locked dependencies and npm runtime dependencies have no known findings in the
audit run. Two high-severity findings remain in SDK development tooling; affected
modules are absent from the inspected JavaScript bundle. Both architecture application payloads match reviewed source byte for byte,
and package metadata passes the privacy check. A retained image passes the
restricted Docker smoke test. No mainnet payment test is
claimed.

## Buyer download

The buyer build passes 176 tests and TypeScript checks. Real Bitcoin/LND regtest
exercises graph discovery, buyer chat and SSE purchases, persistent token totals
and daily spending refusal. Simulated mainnet-mode tests cover price pinning and
daily limits without using real funds. Tests also reject agent policy changes,
foreign browser origins, unapproved models, unsupported tools, and unsafe wallet
configuration. Interrupted SSE does not emit a success marker.

The extracted download installs its pinned runtime in a fresh macOS virtual
environment and serves the local UI over TCP. A second launcher cannot reuse its
data directory. The extracted application also serves authenticated setup in a
non-root, read-only Linux container. Browser verification covers rendering and
policy save. Windows launch is untested. No live GPU inference or mainnet spending
is claimed for this buyer release.
