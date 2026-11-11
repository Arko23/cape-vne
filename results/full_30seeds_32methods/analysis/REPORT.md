# Fresh full evaluation

6 loads ×30 seeds ×32 algorithms = 5,760 observations. Substrate nodes: 50; horizon: 20000 seconds; workers: 4. Unique generated requests across paired traces: 249,322.

The simulator source remained frozen. All expected rows, common request counts, scope/parameter metadata, resource-time ratios and reported paired statistics passed independent reconstruction checks.

## Across-load descriptive means

Each load/seed observation has equal weight. Energy ratios are means of per-run ratios. The separately supplied pooled totals weight requests/service differently.

| Algorithm | AcceptancePercent | Energy_Wh | EnergyPerServedRequestSecond_Wh | EmbeddingMilliseconds |
| --- | --- | --- | --- | --- |
| ProposedAdaptive | 76.7500 | 79966.1491 | 0.1841 | 5.7796 |
| FullJointRepair | 75.3239 | 79064.2499 | 0.1862 | 12.5622 |
| CompactNoRepair | 75.0819 | 78314.1104 | 0.1846 | 7.2726 |
| GreenCostRouting | 75.0513 | 77909.5713 | 0.1832 | 10.0827 |
| AlwaysJointRouting | 72.6824 | 78467.1254 | 0.1935 | 24.2485 |
| FullHopFootprint | 72.6061 | 78504.7210 | 0.1942 | 22.1895 |
| EagerPathGeneration | 72.5553 | 78527.9925 | 0.1942 | 27.2719 |
| LegacyAdaptive | 72.5553 | 78527.9925 | 0.1942 | 22.3665 |
| QoSBoundRouting | 72.5553 | 78527.9925 | 0.1942 | 18.7888 |
| EagerPacking | 72.5553 | 78527.9925 | 0.1942 | 24.1382 |
| ConflictRepair | 72.5461 | 78488.4005 | 0.1941 | 27.2597 |
| FixedEnergyWeight | 72.3996 | 78359.9914 | 0.1940 | 22.5031 |
| NoExactPacking | 72.3535 | 78459.2558 | 0.1941 | 22.9902 |
| NoCompactPlacement | 72.2266 | 77974.4997 | 0.1944 | 8.7741 |
| NoJointRepair | 72.0657 | 77606.5443 | 0.1931 | 15.5130 |
| NoCutPruning | 71.4012 | 77379.1652 | 0.1942 | 36.7909 |
| NodeRankSearch | 71.1169 | 78658.3742 | 0.2009 | 23.6151 |
| GRCRankedSearch | 70.9971 | 78895.9325 | 0.2016 | 21.3071 |
| NodeRankScoreOnly | 70.1090 | 77913.1785 | 0.2015 | 23.1232 |
| GRCScoreOnly | 69.8028 | 77973.1535 | 0.2027 | 21.6455 |
| ProposedGreedy | 66.7667 | 74060.2415 | 0.1983 | 10.1786 |
| PSO | 65.2012 | 73111.7077 | 0.2032 | 169.5886 |
| VirnePSO | 62.9006 | 69224.8908 | 0.1955 | 71.2594 |
| VirneRWBFS | 62.6060 | 72222.8648 | 0.2090 | 2.5859 |
| GRC | 50.1962 | 65640.0105 | 0.2392 | 8.1710 |
| NodeRank | 49.1853 | 64505.1495 | 0.2396 | 8.1877 |
| GreedyKSP | 45.5973 | 63445.6391 | 0.2557 | 7.0455 |
| GreedyCSP | 45.4844 | 63143.6620 | 0.2552 | 1.2673 |
| EnergyAware | 33.5256 | 50689.7042 | 0.2715 | 15.2491 |
| VirneGRC | 31.4271 | 44647.7371 | 0.2434 | 1.9029 |
| VirneRWMaxMatch | 30.4285 | 43613.1508 | 0.2445 | 2.2047 |
| VirneFFD | 26.0126 | 40164.9721 | 0.2620 | 1.5722 |

## Proposal against primary comparison methods

Positive acceptance gain and normalized-energy reduction favor the proposal. A positive total-energy change means it consumes more total energy; a runtime ratio above1 means it is slower.

| Algorithm | AcceptanceGainPP | NormalizedEnergyReductionPercent | TotalEnergyChangePercent | EmbeddingTimeRatio |
| --- | --- | --- | --- | --- |
| VirneFFD | 50.7375 | 29.7461 | 99.0942 | 3.6761 |
| VirneGRC | 45.3229 | 24.3748 | 79.1046 | 3.0372 |
| VirnePSO | 13.8494 | 5.8107 | 15.5165 | 0.0811 |
| VirneRWBFS | 14.1440 | 11.9026 | 10.7214 | 2.2350 |
| VirneRWMaxMatch | 46.3215 | 24.7004 | 83.3533 | 2.6215 |

## Within-load paired significance

30 seeds are paired within each load. q<0.05 uses BH correction over all valid tests in the original statistical file. Across-load means are descriptive and do not have an overall pooled p-value. Other loads include ties, nonsignificant comparisons and undefined tests.

| Baseline | Metric | SignificantBetterLoads | SignificantWorseLoads | OtherLoads |
| --- | --- | --- | --- | --- |
| AlwaysJointRouting | AcceptanceRatio | 6 | 0 | 0 |
| AlwaysJointRouting | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| AlwaysJointRouting | MeanEmbeddingTime | 6 | 0 | 0 |
| CompactNoRepair | AcceptanceRatio | 5 | 0 | 1 |
| CompactNoRepair | EnergyPerServedRequestSecond_Wh | 3 | 3 | 0 |
| CompactNoRepair | MeanEmbeddingTime | 6 | 0 | 0 |
| ConflictRepair | AcceptanceRatio | 6 | 0 | 0 |
| ConflictRepair | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| ConflictRepair | MeanEmbeddingTime | 6 | 0 | 0 |
| EagerPacking | AcceptanceRatio | 6 | 0 | 0 |
| EagerPacking | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| EagerPacking | MeanEmbeddingTime | 6 | 0 | 0 |
| EagerPathGeneration | AcceptanceRatio | 6 | 0 | 0 |
| EagerPathGeneration | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| EagerPathGeneration | MeanEmbeddingTime | 6 | 0 | 0 |
| EnergyAware | AcceptanceRatio | 6 | 0 | 0 |
| EnergyAware | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| EnergyAware | MeanEmbeddingTime | 6 | 0 | 0 |
| FixedEnergyWeight | AcceptanceRatio | 6 | 0 | 0 |
| FixedEnergyWeight | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| FixedEnergyWeight | MeanEmbeddingTime | 6 | 0 | 0 |
| FullHopFootprint | AcceptanceRatio | 6 | 0 | 0 |
| FullHopFootprint | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| FullHopFootprint | MeanEmbeddingTime | 6 | 0 | 0 |
| FullJointRepair | AcceptanceRatio | 6 | 0 | 0 |
| FullJointRepair | EnergyPerServedRequestSecond_Wh | 5 | 0 | 1 |
| FullJointRepair | MeanEmbeddingTime | 6 | 0 | 0 |
| GRC | AcceptanceRatio | 6 | 0 | 0 |
| GRC | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| GRC | MeanEmbeddingTime | 3 | 0 | 3 |
| GRCRankedSearch | AcceptanceRatio | 6 | 0 | 0 |
| GRCRankedSearch | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| GRCRankedSearch | MeanEmbeddingTime | 6 | 0 | 0 |
| GRCScoreOnly | AcceptanceRatio | 6 | 0 | 0 |
| GRCScoreOnly | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| GRCScoreOnly | MeanEmbeddingTime | 6 | 0 | 0 |
| GreedyCSP | AcceptanceRatio | 6 | 0 | 0 |
| GreedyCSP | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| GreedyCSP | MeanEmbeddingTime | 0 | 6 | 0 |
| GreedyKSP | AcceptanceRatio | 6 | 0 | 0 |
| GreedyKSP | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| GreedyKSP | MeanEmbeddingTime | 2 | 3 | 1 |
| GreenCostRouting | AcceptanceRatio | 5 | 0 | 1 |
| GreenCostRouting | EnergyPerServedRequestSecond_Wh | 2 | 4 | 0 |
| GreenCostRouting | MeanEmbeddingTime | 6 | 0 | 0 |
| LegacyAdaptive | AcceptanceRatio | 6 | 0 | 0 |
| LegacyAdaptive | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| LegacyAdaptive | MeanEmbeddingTime | 6 | 0 | 0 |
| NoCompactPlacement | AcceptanceRatio | 6 | 0 | 0 |
| NoCompactPlacement | EnergyPerServedRequestSecond_Wh | 5 | 0 | 1 |
| NoCompactPlacement | MeanEmbeddingTime | 6 | 0 | 0 |
| NoCutPruning | AcceptanceRatio | 6 | 0 | 0 |
| NoCutPruning | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| NoCutPruning | MeanEmbeddingTime | 6 | 0 | 0 |
| NoExactPacking | AcceptanceRatio | 6 | 0 | 0 |
| NoExactPacking | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| NoExactPacking | MeanEmbeddingTime | 6 | 0 | 0 |
| NoJointRepair | AcceptanceRatio | 6 | 0 | 0 |
| NoJointRepair | EnergyPerServedRequestSecond_Wh | 5 | 0 | 1 |
| NoJointRepair | MeanEmbeddingTime | 6 | 0 | 0 |
| NodeRank | AcceptanceRatio | 6 | 0 | 0 |
| NodeRank | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| NodeRank | MeanEmbeddingTime | 3 | 0 | 3 |
| NodeRankScoreOnly | AcceptanceRatio | 6 | 0 | 0 |
| NodeRankScoreOnly | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| NodeRankScoreOnly | MeanEmbeddingTime | 6 | 0 | 0 |
| NodeRankSearch | AcceptanceRatio | 6 | 0 | 0 |
| NodeRankSearch | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| NodeRankSearch | MeanEmbeddingTime | 6 | 0 | 0 |
| PSO | AcceptanceRatio | 6 | 0 | 0 |
| PSO | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| PSO | MeanEmbeddingTime | 6 | 0 | 0 |
| ProposedGreedy | AcceptanceRatio | 6 | 0 | 0 |
| ProposedGreedy | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| ProposedGreedy | MeanEmbeddingTime | 6 | 0 | 0 |
| QoSBoundRouting | AcceptanceRatio | 6 | 0 | 0 |
| QoSBoundRouting | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| QoSBoundRouting | MeanEmbeddingTime | 6 | 0 | 0 |
| VirneFFD | AcceptanceRatio | 6 | 0 | 0 |
| VirneFFD | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| VirneFFD | MeanEmbeddingTime | 0 | 6 | 0 |
| VirneGRC | AcceptanceRatio | 6 | 0 | 0 |
| VirneGRC | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| VirneGRC | MeanEmbeddingTime | 0 | 6 | 0 |
| VirnePSO | AcceptanceRatio | 6 | 0 | 0 |
| VirnePSO | EnergyPerServedRequestSecond_Wh | 4 | 1 | 1 |
| VirnePSO | MeanEmbeddingTime | 6 | 0 | 0 |
| VirneRWBFS | AcceptanceRatio | 6 | 0 | 0 |
| VirneRWBFS | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| VirneRWBFS | MeanEmbeddingTime | 0 | 6 | 0 |
| VirneRWMaxMatch | AcceptanceRatio | 6 | 0 | 0 |
| VirneRWMaxMatch | EnergyPerServedRequestSecond_Wh | 6 | 0 | 0 |
| VirneRWMaxMatch | MeanEmbeddingTime | 0 | 6 | 0 |

## Limits

This evaluates one recorded synthetic topology/workload/power scenario. Runtime was measured with 4 workers; use separate serial experiments for isolated latency claims. Virne methods are ports of the pinned reference code with the common hard delay/hop gates; VirnePSO uses a documented parent-visible serial scheduler correction. They are not verified complete original-paper reproductions. Results do not establish superiority over omitted full-paper implementations or literature novelty. See the root REFERENCES.md.
