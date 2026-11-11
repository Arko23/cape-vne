# Necessary regression data

These files let the tests run without old experiment folders or old simulator
archives. They are deterministic correctness fixtures, not performance evidence.

| File | Purpose |
|---|---|
| `baseline_regression.json` | Two seeded cases of the original five baselines, with non-time resource/service/energy outcomes |
| `policy_regression.json` | Default and sparse-QoS cases of all original 27 methods, with non-time outcomes, work counters and exact policy parameters |
| `sparse_qos_witness.json` | A preserved resource state and request that exercises a real sparse-QoS admission regression |

The expected outcomes were extracted from the original frozen source archives,
then checked for exact equality with the maintained policies before the old
archives were removed. Each JSON fixture records the original source and
archive SHA-256 for provenance. The fixtures omit embedding timings and are
not regenerated from new outcomes when a test fails.

For the 2026-10-08 proposal performance revision, comparator outcomes, counters
and parameters remain frozen. The proposal still checks exact physical
service/energy/route outcomes, while its reduced-work counters and new execution
flags are allowed to differ. The saved fixture itself is unchanged.

The sparse witness was copied byte-for-byte; its SHA-256 is
`dcb58a23c9b683fdb21bc6723b3d47fb234518fb3c77e1a9458544dc085e2f1b`.

The separate pinned Virne decision-code oracle lives in
[third_party/virne](../../third_party/virne/NOTICE.md). It remains necessary
because the tests execute upstream definitions rather than treating a local
port's output as its own reference.
