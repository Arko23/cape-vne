# Primary sources and implementation fidelity

## Pinned Virne source

The five `Virne*` ports use a selected snapshot of
[GeminiLight/Virne](https://github.com/GeminiLight/virne). Its original local
checkout had no verified Git revision. The exact 16 files are retained in
[third_party/virne/source.zip](third_party/virne/source.zip), with archive and
member hashes in [SOURCE.json](third_party/virne/SOURCE.json). This snapshot is
not identified as the latest upstream version.

| Method | Pinned decision rules | Explicit adaptations |
|---|---|---|
| VirneGRC | GRC ranks on both graphs, L2 tolerance 1e-5, greedy two-stage mapping, sequential K=10 unweighted paths | Common hard delay/hop gates, atomic accounting and finite zero/dangling-resource handling; paper profit threshold absent |
| VirneRWMaxMatch | H-weighted global/neighbor resource walk, L2 tolerance 1e-4, two-stage maximum-rank matching, K=10 paths | Same QoS/accounting and degenerate-resource extensions |
| VirneRWBFS | Virtual BFS/rank order, highest-rank physical root, depth 5 and visit parameter 50, bandwidth-feasible BFS routes | Same QoS/accounting; disconnected virtual requests rejected rather than partially admitted |
| VirneFFD | Decreasing absolute residual CPU, stable ties, sequential K=10 paths | Same QoS/accounting; this is not Yu's path-splitting/migration method |
| VirnePSO | Equality-bit updates, 8 particles ×12 iterations, probabilities 0.1/0.2/0.7, injective CPU-domain candidates, cost/revenue fitness, K=10 paths | Parent-visible synchronous serial evolution, one global snapshot per iteration, private RNG streams and common QoS/accounting |

The pinned PSO process loop discards child-process particle updates and its
constructor has spawn-pickling limitations. The port corrects the scheduler
instead of retaining a broken competitor. Its effective CPU-only candidate
domains are preserved: the pinned controller computes but discards an extra
link-domain mask. Execution changes are recorded in algorithm metadata.
These decisions may differ from newer upstream revisions.

Independent tests execute unchanged rank, mapping, routing and PSO definitions
from this archive through the adapters in `tests/virne_oracle.py`. They also
check the hard QoS extension, rejected-request rollback, committed resource
state and the discarded-process-update defect. These are decision-code checks,
not a full native Virne environment or complete original-paper reproduction.
Port runtime does not include native Virne framework overhead.

Apache-2.0 attribution, the unchanged original license and modifications are
documented in [third_party/virne/NOTICE.md](third_party/virne/NOTICE.md).
The external checkout is not required to run the simulator or its tests.

## Original baselines

| Local identifier | Primary source and verified portion | Remaining fidelity limits |
|---|---|---|
| GRC | Gong et al., *Toward Profit-Seeking Virtual Network Embedding Algorithm via Global Resource Capacity*, INFOCOM 2014. [Author paper](https://www3.ntu.edu.sg/home/ygwen/Paper/GWZL-Infocom-14.pdf), [DOI](https://doi.org/10.1109/INFOCOM.2014.6847918). Normalized CPU personalization, bandwidth transitions and damping 0.85 on both graphs. | Shared bounded unsplittable QoS router and no profit-threshold stage; ranking adaptation |
| NodeRank | Cheng et al., *Virtual Network Embedding Through Topology-Aware Node Ranking*, CCR 2011. [DOI](https://doi.org/10.1145/1971162.1971168), [indexed primary text](https://citeseerx.ist.psu.edu/document?doi=591638ee010aceb0192c6cab37fb311900d83914&repid=rep1&type=pdf). H=CPU×incident bandwidth, H-weighted global jumps and neighbor forwarding. | Direct PDF retrieval was unavailable during verification; shared router, zero/dangling extensions and no original RW-BFS pipeline |
| GreedyKSP | Related work: Yu et al., *Rethinking Virtual Network Embedding: Substrate Support for Path Splitting and Migration*, 2008. [Author paper](https://www.princeton.edu/~chiangm/vne.pdf). | Custom residual-CPU-fraction placement and bounded joint QoS routing; not the paper's splitting/migration algorithm |
| EnergyAware | Related work: Su et al., *Energy-Aware Virtual Network Embedding*, IEEE/ACM ToN 2014. [DOI](https://doi.org/10.1109/TNET.2013.2286156). | Full equation-level verification unavailable; custom marginal-host-power greedy placement |
| PSO | Related work: Cheng et al., *Virtual network embedding through topology awareness and optimization*, Computer Networks 2012. [Publisher record](https://www.sciencedirect.com/science/article/abs/pii/S1389128612000461), [DOI](https://doi.org/10.1016/j.comnet.2012.01.022). | Custom 12×12 categorical PSO, mapping repair, admission-cost fitness, K=1 routing and greedy fallback; not verified RW-PSO or EA-VNE-EPSO |

Independent linear-system tests check the implemented GRC and NodeRank equations,
virtual-graph ranking and resource accounting. They do not verify missing
end-to-end paper stages. Stable identifiers distinguish these implementations
from the five pinned Virne ports.

## Proposal and prior work

The proposal combines joint hop/delay port domains, local packing feasibility,
shared-quota greedy/constrained-node recovery and power-aware equal-hop route
preferences. The domain and packing checks are necessary conditions; heuristic
placement and bounded repair can still reject feasible requests.

Hop-layer delay dynamic programming is established constrained-path machinery.
See [Frangioni, Galli and Scutella, Section 3.1](https://arpi.unipi.it/bitstream/11568/486067/2/SOCP4SFSP.pdf)
for successive hop phases in a related minimum-hop delay-feasible problem.
This implementation uses fixed additive delay rather than their complete
rate-allocation model. Priority/order recovery also overlaps with
[Zheng et al., ICAPS 2023](https://www2.cs.sfu.ca/~hangma/pub/icaps23.pdf).
No new general shortest-path, packing or VNE optimality theorem is claimed.

The 21 local controls are documented in the registry and README. Most retain
previous proposal engines; they are local comparisons, not separately published
algorithms or automatically valid isolated ablations of the latest proposal.

A green claim must be tied to recorded energy assumptions and comparable served
work. Acceptance, total energy, normalized energy and runtime can trade off.
Fresh complete paired experiments, relevant current published methods,
independent scenarios and a defensible mechanism contribution are still needed
for publication claims. No performance winner or journal quartile is guaranteed.
