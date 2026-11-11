# Virne reference code attribution

`vne/reference_baselines.py` derives decision rules from
[GeminiLight/Virne](https://github.com/GeminiLight/virne).
Original source headers: Copyright 2023 GeminiLight (wtfly2018@gmail.com).

The unchanged original Apache License 2.0 is retained in [LICENSE](LICENSE).
The exact selected upstream files are retained in [source.zip](source.zip);
archive and member hashes are listed in [SOURCE.json](SOURCE.json).
The original local snapshot has no verified Git revision. It is not represented
as the current upstream release or as a complete Virne checkout.

Modifications here include CPU/BW network translation, common hard delay/hop
gates, atomic commit/release, finite degenerate-rank handling, private RNG
streams, parent-visible synchronous serial PSO evolution, and explicit
metadata/work counters. Independent tests execute unchanged pinned definitions
using the CPU/BW adapters in `tests/virne_oracle.py`.

These adapters and changes do not establish complete original-paper
reproduction. See [the implementation fidelity notes](../../REFERENCES.md)
for each method's scope. The pinned source and its license remain necessary
test dependencies.
