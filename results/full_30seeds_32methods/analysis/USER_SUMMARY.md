# Completed run assessment

Validated 6 loads ×30 seeds ×32 methods = 5,760 rows; 50 nodes, 20,000 seconds, 4 concurrent workers. All 180 topology/request cases were regenerated and their recorded hashes and request counts matched. Served-resource identities and independent CPU-energy bounds passed. No simulation was rerun or policy changed.

## Proposal and competitors

Values below average 180 run-level metrics equally. Energy is modeled Wh per 20,000-second run. Normalized energy is Wh per served virtual-request-second. This is distinct from pooling all arrivals/service.

| Algorithm | AcceptancePercent | Energy_Wh | EnergyPerServedRequestSecond_Wh | EmbeddingMs | MeanHops |
| --- | --- | --- | --- | --- | --- |
| ProposedAdaptive | 76.750 | 79966.1 | 0.184093 | 5.780 | 1.621 |
| VirneGRC | 31.427 | 44647.7 | 0.243428 | 1.903 | 1.652 |
| VirneRWMaxMatch | 30.429 | 43613.2 | 0.244480 | 2.205 | 1.643 |
| VirneRWBFS | 62.606 | 72222.9 | 0.208965 | 2.586 | 2.006 |
| VirneFFD | 26.013 | 40165.0 | 0.262039 | 1.572 | 1.772 |
| VirnePSO | 62.901 | 69224.9 | 0.195450 | 71.259 | 1.497 |
| GRC | 50.196 | 65640.0 | 0.239224 | 8.171 | 2.169 |
| NodeRank | 49.185 | 64505.1 | 0.239636 | 8.188 | 2.185 |
| GreedyKSP | 45.597 | 63445.6 | 0.255657 | 7.045 | 2.347 |
| EnergyAware | 33.526 | 50689.7 | 0.271519 | 15.249 | 2.596 |
| PSO | 65.201 | 73111.7 | 0.203178 | 169.589 | 1.759 |
| FullJointRepair | 75.324 | 79064.2 | 0.186195 | 12.562 | 1.675 |
| CompactNoRepair | 75.082 | 78314.1 | 0.184565 | 7.273 | 1.588 |
| GreenCostRouting | 75.051 | 77909.6 | 0.183156 | 10.083 | 1.630 |

## All-metric proposal assessment

Competition ranks among all 32 methods. Per-load order is 2/4/6/8/10/12 requests per100 seconds. The mean of run-level P95/P99 measurements is not a pooled percentile. Utilization ranks indicate usage, not intrinsic quality.

| Metric | Value | Unit | OverallRank | PerLoadRanks | TopFiveLoads | MeanLeader |
| --- | --- | --- | --- | --- | --- | --- |
| Acceptance | 76.75 | % | 1 | 1/1/1/1/1/2 | 6 | ProposedAdaptive |
| Admission revenue/cost | 0.70469 | ratio | 3 | 1/3/4/6/7/7 | 3 | VirnePSO |
| Served revenue/cost | 0.704983 | ratio | 3 | 1/2/4/6/7/7 | 3 | VirnePSO |
| Total energy | 79966.1 | Wh | 32 | 7/32/32/32/32/32 | 0 | VirneFFD |
| Energy/accepted request | 89.5027 | Wh/request | 2 | 2/1/3/3/4/7 | 5 | GreenCostRouting |
| Energy/served request-second | 0.184093 | Wh/request-second | 2 | 2/1/1/3/4/6 | 5 | GreenCostRouting |
| Energy/served CPU-second | 0.0013201 | Wh/CPU-unit-second | 1 | 2/1/1/1/1/1 | 6 | ProposedAdaptive |
| Energy/served BW-second | 0.000558968 | Wh/BW-unit-second | 1 | 1/1/1/1/1/1 | 6 | ProposedAdaptive |
| Mean embedding time | 5.77964 | ms | 6 | 6/6/7/9/9/9 | 0 | GreedyCSP |
| P95 embedding time | 19.5448 | ms | 6 | 6/6/10/10/10/10 | 0 | VirneFFD |
| P99 embedding time | 40.1159 | ms | 10 | 6/10/11/11/11/11 | 0 | VirneFFD |
| Total embedding time | 8.39732 | seconds | 7 | 6/6/7/9/9/9 | 0 | GreedyCSP |
| Mean hops | 1.62096 | hops | 3 | 1/2/4/6/6/7 | 3 | VirnePSO |
| CPU utilization (highest usage) | 63.1217 | % | 1 | 1/1/1/1/1/1 | 6 | ProposedAdaptive |
| BW utilization (highest usage) | 43.7402 | % | 17 | 26/18/16/15/15/15 | 0 | NodeRankSearch |

## Load-specific performance

| Lambda | AcceptancePercent | AcceptanceRank | MeanLeaders | TimeRank | EnergyPerServiceRank | TotalEnergyRank | HopsRank |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2.0 | 99.754 | 1 | ProposedAdaptive | 6 | 2 | 7 | 1 |
| 4.0 | 95.956 | 1 | ProposedAdaptive | 6 | 1 | 32 | 2 |
| 6.0 | 82.432 | 1 | ProposedAdaptive | 7 | 1 | 32 | 4 |
| 8.0 | 69.991 | 1 | ProposedAdaptive | 9 | 3 | 32 | 6 |
| 10.0 | 59.965 | 1 | ProposedAdaptive | 9 | 4 | 32 | 6 |
| 12.0 | 52.402 | 2 | GreenCostRouting | 9 | 6 | 32 | 7 |

At load 12, GreenCostRouting leads acceptance by only 0.0039 percentage points; the paired difference is nonsignificant (BH q≈0.954). The proposal remains second by the numerical mean rank.

## Paired evidence

Better/Worse refer to within-load, seed-paired comparisons against the proposal with BH q<0.05 over the original 2,604 tests. Other includes nonsignificant comparisons. No across-load significance test or pairwise tests between other methods are claimed.

| Baseline | Metric | BetterLoads | WorseLoads | OtherLoads |
| --- | --- | --- | --- | --- |
| CompactNoRepair | AcceptanceRatio | 2,4,6,8,10 | none | 12 |
| CompactNoRepair | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| CompactNoRepair | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| CompactNoRepair | EnergyPerServedRequestSecond_Wh | 2,4,6 | 8,10,12 | none |
| CompactNoRepair | MeanEmbeddingTime | 2,4,6,8,10,12 | none | none |
| EnergyAware | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| EnergyAware | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| EnergyAware | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| EnergyAware | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| EnergyAware | MeanEmbeddingTime | 2,4,6,8,10,12 | none | none |
| FullJointRepair | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| FullJointRepair | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| FullJointRepair | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| FullJointRepair | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10 | none | 12 |
| FullJointRepair | MeanEmbeddingTime | 2,4,6,8,10,12 | none | none |
| GRC | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| GRC | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| GRC | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| GRC | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| GRC | MeanEmbeddingTime | 2,4,6 | none | 8,10,12 |
| GreedyKSP | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| GreedyKSP | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| GreedyKSP | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| GreedyKSP | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| GreedyKSP | MeanEmbeddingTime | 2,4 | 8,10,12 | 6 |
| GreenCostRouting | AcceptanceRatio | 2,4,6,8,10 | none | 12 |
| GreenCostRouting | EnergyPerServedBandwidthUnitSecond_Wh | 4,6,8,10,12 | none | 2 |
| GreenCostRouting | EnergyPerServedCPUUnitSecond_Wh | 4,6,8,10,12 | 2 | none |
| GreenCostRouting | EnergyPerServedRequestSecond_Wh | 4,6 | 2,8,10,12 | none |
| GreenCostRouting | MeanEmbeddingTime | 2,4,6,8,10,12 | none | none |
| NodeRank | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| NodeRank | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| NodeRank | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| NodeRank | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| NodeRank | MeanEmbeddingTime | 2,4,6 | none | 8,10,12 |
| PSO | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| PSO | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| PSO | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| PSO | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| PSO | MeanEmbeddingTime | 2,4,6,8,10,12 | none | none |
| VirneFFD | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| VirneFFD | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneFFD | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneFFD | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneFFD | MeanEmbeddingTime | none | 2,4,6,8,10,12 | none |
| VirneGRC | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| VirneGRC | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneGRC | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneGRC | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneGRC | MeanEmbeddingTime | none | 2,4,6,8,10,12 | none |
| VirnePSO | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| VirnePSO | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirnePSO | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirnePSO | EnergyPerServedRequestSecond_Wh | 2,4,6,8 | 12 | 10 |
| VirnePSO | MeanEmbeddingTime | 2,4,6,8,10,12 | none | none |
| VirneRWBFS | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| VirneRWBFS | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneRWBFS | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneRWBFS | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneRWBFS | MeanEmbeddingTime | none | 2,4,6,8,10,12 | none |
| VirneRWMaxMatch | AcceptanceRatio | 2,4,6,8,10,12 | none | none |
| VirneRWMaxMatch | EnergyPerServedBandwidthUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneRWMaxMatch | EnergyPerServedCPUUnitSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneRWMaxMatch | EnergyPerServedRequestSecond_Wh | 2,4,6,8,10,12 | none | none |
| VirneRWMaxMatch | MeanEmbeddingTime | none | 2,4,6,8,10,12 | none |

## Interpretation and limits

- Strongest result: highest average acceptance; mean rank 1 at five loads and a near-tie at load 12. It accepts 170,002 of 249,322 requests pooled (68.186%); the equal-load/run acceptance mean is 76.750%.
- Service/resource efficiency is strong: energy per served CPU-second ranks 1 at loads 4–12 and 2 at load 2; energy per served virtual-bandwidth-second ranks 1 at every load.
- Embedding time ranks 6–9 and total energy ranks 32 at loads 4–12. The goal of top-five placement on every metric is not met. More admitted/served demand means total energy and utilization require interpretation alongside service volume.
- GreenCostRouting is the closest efficiency control: it has lower mean energy per served request-second and significantly lower values at loads 2,8,10,12. VirnePSO has significantly lower values at load 12; the load 10 difference is nonsignificant. Thus normalized energy is not universally best.
- The proposal is significantly faster than all three compact controls at every load. It is significantly slower than the four non-PSO Virne ports and GreedyCSP at every load. Against GreedyKSP the time result depends on load.
- Current proposal versus NoExactPacking favors the proposal for acceptance, normalized service energy and runtime at all six loads, but NoExactPacking uses the previous engine: these differences do not isolate an exact-packing contribution.
- The five Virne competitors are pinned reference-code ports with documented QoS and execution adaptations. GRC/NodeRank are ranking adaptations; GreedyKSP/EnergyAware/PSO are custom baselines. These results do not verify complete published-method reproduction.
- Four concurrent workers were used; embedding time excludes construction and simulator overhead. The energy model excludes algorithm-computation electricity. One fixed synthetic density/workload/power scenario with 30 seeded topologies does not establish real-topology generalization or literature novelty.

## Files

[All-method per-load rankings](../rankings/REPORT.md), [original comparison report](REPORT.md), [comparison chart](primary_comparison.png), [overall top five](overall_top_five.csv), [independent input/energy audit](independent_input_and_energy_audit.json), [all mean metrics](all_metric_means.csv), [pooled service volumes](service_volume_totals.csv).
