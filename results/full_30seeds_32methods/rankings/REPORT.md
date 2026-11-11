# Latest full-run scenario and metric rankings

6 arrival loads ×30 seeds ×32 methods = 5,760 validated rows. Fixed substrate: 50 nodes; horizon: 20000 seconds; workers: 4. Source `3f2a9fd7f38a64c4172b76dbf81f9854758d01de68867014bf8768ddfe9b30f2`.

A scenario here means arrival load, measured in requests per100 seconds. Density, sizes, QoS, demand distributions, power and lifetimes were not varied. All means average the30 seeds equally within load. Ranks compare all32 methods, including proposal ablations and experimental variants.

The primary cohort for this report is: ProposedAdaptive, VirneGRC, VirneRWMaxMatch, VirneRWBFS, VirneFFD, VirnePSO. Reference-code ports and their common-model extensions are described in REFERENCES.md.

Ties share competition rank (e.g.1,1,1,1,5); alphabetical order inside a tie has no performance meaning. `=` denotes a numerical tie, while `>` orders methods by the stated metric preference. Boundary ties are included even if more than five methods appear. Rankings are descriptive; nearby ranks are not necessarily statistically separated. CPU/BW utilization lists highest usage, which is not intrinsically better. Lower total energy may mean less admitted service; mean hops is conditional on the admitted requests. No-admission runs have undefined hops/admission R/C; zero-served-cost runs have undefined served R/C. Their raw zero placeholders are excluded from quality averages/ranks, and DefinedSeeds records the number of contributing runs. Methods with no defined value are unranked for that metric; all raw results remain unchanged. P95/P99 values are means of per-run percentiles, not pooled request-level percentiles.

## Proposal positions

| Metric | λ2 | λ4 | λ6 | λ8 | λ10 | λ12 |
|---|---:|---:|---:|---:|---:|---:|
| Acceptance ↑ | 1 | 1 | 1 | 1 | 1 | 2 |
| Admission revenue/cost ↑ | 1 | 3 | 4 | 6 | 7 | 7 |
| Served revenue/cost ↑ | 1 | 2 | 4 | 6 | 7 | 7 |
| Total energy ↓ | 7 | 32 | 32 | 32 | 32 | 32 |
| Energy/accepted request ↓ | 2 | 1 | 3 | 3 | 4 | 7 |
| Energy/served request-second ↓ | 2 | 1 | 1 | 3 | 4 | 6 |
| Energy/served CPU-second ↓ | 2 | 1 | 1 | 1 | 1 | 1 |
| Energy/served BW-second ↓ | 1 | 1 | 1 | 1 | 1 | 1 |
| Mean embedding time ↓ | 6 | 6 | 7 | 9 | 9 | 9 |
| P95 embedding time ↓ | 6 | 6 | 10 | 10 | 10 | 10 |
| P99 embedding time ↓ | 6 | 10 | 11 | 11 | 11 | 11 |
| Total embedding time ↓ | 6 | 6 | 7 | 9 | 9 | 9 |
| Mean hops ↓ | 1 | 2 | 4 | 6 | 6 | 7 |
| CPU utilization (highest usage) ↑ | 1 | 1 | 1 | 1 | 1 | 1 |
| BW utilization (highest usage) ↑ | 26 | 18 | 16 | 15 | 15 | 15 |

## Arrival load 2 requests/100 seconds

| Metric | Top five methods (rank order; values in stated units) | Proposal rank/32 | Proposal value |
|---|---|---:|---:|
| Acceptance ↑ (%) | ProposedAdaptive (99.7541) > FullJointRepair (99.3941) > AlwaysJointRouting (98.3108) > CompactNoRepair (98.2942) > GreenCostRouting (98.2025) | 1 | 99.7541 |
| Admission revenue/cost ↑ (ratio) | ProposedAdaptive (0.78315) > CompactNoRepair (0.779314) > FullJointRepair (0.765426) > VirnePSO (0.745769) > GreenCostRouting (0.733702) | 1 | 0.78315 |
| Served revenue/cost ↑ (ratio) | ProposedAdaptive (0.780559) > CompactNoRepair (0.779692) > FullJointRepair (0.765714) > VirnePSO (0.74656) > GreenCostRouting (0.732611) | 1 | 0.780559 |
| Total energy ↓ (Wh) | VirneFFD (19707.2) > VirneRWMaxMatch (23235.7) > VirneGRC (23687.1) > EnergyAware (33708.2) > VirnePSO (44239.4) | 7 | 46345.9 |
| Energy/accepted request ↓ (Wh/request) | GreenCostRouting (118.13) > ProposedAdaptive (119.433) > CompactNoRepair (121.258) > FullJointRepair (122.227) > AlwaysJointRouting (132.266) | 2 | 119.433 |
| Energy/served request-second ↓ (Wh/request-second) | GreenCostRouting (0.242649) > ProposedAdaptive (0.245359) > CompactNoRepair (0.249253) > FullJointRepair (0.251241) > AlwaysJointRouting (0.272558) | 2 | 0.245359 |
| Energy/served CPU-second ↓ (Wh/CPU-unit-second) | GreenCostRouting (0.00165751) > ProposedAdaptive (0.00166805) > CompactNoRepair (0.00170316) > FullJointRepair (0.00171) > AlwaysJointRouting (0.00186348) | 2 | 0.00166805 |
| Energy/served BW-second ↓ (Wh/BW-unit-second) | ProposedAdaptive (0.000664817) > GreenCostRouting (0.000664922) > FullJointRepair (0.000682361) > CompactNoRepair (0.000682657) > AlwaysJointRouting (0.000748468) | 1 | 0.000664817 |
| Mean embedding time ↓ (ms) | VirneFFD (1.6932) > VirneGRC (2.01811) > GreedyCSP (2.1566) > VirneRWMaxMatch (2.29253) > VirneRWBFS (2.50264) | 6 | 4.02345 |
| P95 embedding time ↓ (ms) | VirneFFD (3.11236) > VirneGRC (3.51854) > VirneRWMaxMatch (3.78834) > GreedyCSP (5.82434) > VirneRWBFS (6.16442) | 6 | 8.73479 |
| P99 embedding time ↓ (ms) | VirneFFD (4.09507) > VirneGRC (4.53768) > VirneRWMaxMatch (4.78246) > GreedyCSP (8.37298) > VirneRWBFS (9.22152) | 6 | 14.1508 |
| Total embedding time ↓ (seconds) | VirneFFD (0.658835) > VirneGRC (0.784821) > GreedyCSP (0.839188) > VirneRWMaxMatch (0.891756) > VirneRWBFS (0.974731) | 6 | 1.56642 |
| Mean hops ↓ (hops) | ProposedAdaptive (1.37914) > CompactNoRepair (1.38428) > FullJointRepair (1.4154) > VirnePSO (1.48853) > GreenCostRouting (1.49982) | 1 | 1.37914 |
| CPU utilization (highest usage) ↑ (%) | ProposedAdaptive (27.9285) > FullJointRepair (27.7826) > GreenCostRouting (27.3665) > CompactNoRepair (27.3632) > FullHopFootprint (27.303) | 1 | 27.9285 |
| BW utilization (highest usage) ↑ (%) | NodeRankSearch (26.7895) > GRCRankedSearch (26.4966) > NodeRankScoreOnly (26.4908) > GRCScoreOnly (26.2256) > FixedEnergyWeight (25.1967) | 26 | 17.7942 |

## Arrival load 4 requests/100 seconds

| Metric | Top five methods (rank order; values in stated units) | Proposal rank/32 | Proposal value |
|---|---|---:|---:|
| Acceptance ↑ (%) | ProposedAdaptive (95.9557) > FullJointRepair (93.0986) > CompactNoRepair (92.0754) > GreenCostRouting (91.6243) > AlwaysJointRouting (88.8569) | 1 | 95.9557 |
| Admission revenue/cost ↑ (ratio) | CompactNoRepair (0.748695) > VirnePSO (0.74659) > ProposedAdaptive (0.745828) > GreenCostRouting (0.73102) > FullJointRepair (0.719645) | 3 | 0.745828 |
| Served revenue/cost ↑ (ratio) | CompactNoRepair (0.749908) > ProposedAdaptive (0.748436) > VirnePSO (0.746743) > GreenCostRouting (0.731755) > FullJointRepair (0.720447) | 2 | 0.748436 |
| Total energy ↓ (Wh) | VirneFFD (31965.4) > VirneRWMaxMatch (35459.3) > VirneGRC (35995.1) > EnergyAware (44742) > GreedyCSP (59027.9) | 32 | 73575.1 |
| Energy/accepted request ↓ (Wh/request) | ProposedAdaptive (97.7023) > GreenCostRouting (98.3) > CompactNoRepair (99.0709) > FullJointRepair (99.6342) > AlwaysJointRouting (103.785) | 1 | 97.7023 |
| Energy/served request-second ↓ (Wh/request-second) | ProposedAdaptive (0.201618) > GreenCostRouting (0.202598) > CompactNoRepair (0.204239) > FullJointRepair (0.205476) > AlwaysJointRouting (0.214509) | 1 | 0.201618 |
| Energy/served CPU-second ↓ (Wh/CPU-unit-second) | ProposedAdaptive (0.00138642) > GreenCostRouting (0.00141308) > CompactNoRepair (0.00142098) > FullJointRepair (0.00142305) > AlwaysJointRouting (0.00150611) | 1 | 0.00138642 |
| Energy/served BW-second ↓ (Wh/BW-unit-second) | ProposedAdaptive (0.000559882) > FullJointRepair (0.000580558) > GreenCostRouting (0.0005817) > CompactNoRepair (0.000582885) > AlwaysJointRouting (0.000624812) | 1 | 0.000559882 |
| Mean embedding time ↓ (ms) | GreedyCSP (1.49727) > VirneFFD (1.53499) > VirneGRC (1.82065) > VirneRWMaxMatch (2.16515) > VirneRWBFS (2.54098) | 6 | 5.31108 |
| P95 embedding time ↓ (ms) | VirneFFD (2.77365) > VirneGRC (3.06405) > VirneRWMaxMatch (3.56598) > GreedyCSP (4.72585) > VirneRWBFS (5.55734) | 6 | 14.0126 |
| P99 embedding time ↓ (ms) | VirneFFD (3.71572) > VirneGRC (4.06616) > VirneRWMaxMatch (4.63463) > GreedyCSP (6.82143) > VirneRWBFS (7.92387) | 10 | 39.5497 |
| Total embedding time ↓ (seconds) | GreedyCSP (1.17573) > VirneFFD (1.20661) > VirneGRC (1.42932) > VirneRWMaxMatch (1.70154) > VirneRWBFS (1.99491) | 6 | 4.17385 |
| Mean hops ↓ (hops) | CompactNoRepair (1.46563) > ProposedAdaptive (1.48169) > VirnePSO (1.49854) > GreenCostRouting (1.51207) > FullJointRepair (1.54323) | 2 | 1.48169 |
| CPU utilization (highest usage) ↑ (%) | ProposedAdaptive (53.304) > FullJointRepair (51.3699) > CompactNoRepair (50.599) > GreenCostRouting (50.2437) > AlwaysJointRouting (48.2599) | 1 | 53.304 |
| BW utilization (highest usage) ↑ (%) | NodeRankSearch (44.8606) > GRCRankedSearch (44.2899) > NodeRankScoreOnly (43.9391) > GRCScoreOnly (43.4199) > FixedEnergyWeight (41.714) | 18 | 35.3804 |

## Arrival load 6 requests/100 seconds

| Metric | Top five methods (rank order; values in stated units) | Proposal rank/32 | Proposal value |
|---|---|---:|---:|
| Acceptance ↑ (%) | ProposedAdaptive (82.432) > FullJointRepair (79.9509) > CompactNoRepair (79.8676) > GreenCostRouting (79.8181) > FullHopFootprint (75.8392) | 1 | 82.432 |
| Admission revenue/cost ↑ (ratio) | VirnePSO (0.748785) > CompactNoRepair (0.711699) > GreenCostRouting (0.702093) > ProposedAdaptive (0.69951) > VirneRWMaxMatch (0.698882) | 4 | 0.69951 |
| Served revenue/cost ↑ (ratio) | VirnePSO (0.748493) > CompactNoRepair (0.712189) > GreenCostRouting (0.703126) > ProposedAdaptive (0.700121) > VirneRWMaxMatch (0.699232) | 4 | 0.700121 |
| Total energy ↓ (Wh) | VirneFFD (39994.5) > VirneRWMaxMatch (43337.9) > VirneGRC (44752.9) > EnergyAware (50870.5) > GreedyCSP (64100.3) | 32 | 85101.7 |
| Energy/accepted request ↓ (Wh/request) | GreenCostRouting (86.5869) > CompactNoRepair (86.6885) > ProposedAdaptive (86.7555) > FullJointRepair (87.5832) > NoCompactPlacement (89.8035) | 3 | 86.7555 |
| Energy/served request-second ↓ (Wh/request-second) | ProposedAdaptive (0.178224) > CompactNoRepair (0.17876) > GreenCostRouting (0.178786) > FullJointRepair (0.180129) > NoJointRepair (0.184896) | 1 | 0.178224 |
| Energy/served CPU-second ↓ (Wh/CPU-unit-second) | ProposedAdaptive (0.00126489) > CompactNoRepair (0.00129094) > GreenCostRouting (0.00129202) > FullJointRepair (0.00129395) > FullHopFootprint (0.00135672) | 1 | 0.00126489 |
| Energy/served BW-second ↓ (Wh/BW-unit-second) | ProposedAdaptive (0.000529387) > FullJointRepair (0.000550133) > CompactNoRepair (0.000550877) > GreenCostRouting (0.000552276) > ConflictRepair (0.000588327) | 1 | 0.000529387 |
| Mean embedding time ↓ (ms) | GreedyCSP (1.17204) > VirneFFD (1.55214) > VirneGRC (1.85575) > VirneRWMaxMatch (2.16254) > VirneRWBFS (2.64821) | 7 | 6.62117 |
| P95 embedding time ↓ (ms) | VirneFFD (2.80599) > VirneGRC (3.15163) > VirneRWMaxMatch (3.56414) > GreedyCSP (3.99721) > VirneRWBFS (5.44189) | 10 | 23.8891 |
| P99 embedding time ↓ (ms) | VirneFFD (3.63104) > VirneGRC (4.05605) > VirneRWMaxMatch (4.48841) > GreedyCSP (6.13532) > VirneRWBFS (7.48946) | 11 | 47.4888 |
| Total embedding time ↓ (seconds) | GreedyCSP (1.39502) > VirneFFD (1.8508) > VirneGRC (2.21232) > VirneRWMaxMatch (2.57669) > VirneRWBFS (3.15446) | 7 | 7.89376 |
| Mean hops ↓ (hops) | VirnePSO (1.50258) > CompactNoRepair (1.57733) > GreenCostRouting (1.60527) > ProposedAdaptive (1.62503) > VirneRWMaxMatch (1.64415) | 4 | 1.62503 |
| CPU utilization (highest usage) ↑ (%) | ProposedAdaptive (67.565) > FullJointRepair (64.675) > CompactNoRepair (64.1002) > GreenCostRouting (63.9283) > FullHopFootprint (60.4404) | 1 | 67.565 |
| BW utilization (highest usage) ↑ (%) | NodeRankSearch (53.1523) > GRCRankedSearch (52.6567) > NodeRankScoreOnly (52.112) > GRCScoreOnly (51.1776) > AlwaysJointRouting (50.253) | 16 | 47.2167 |

## Arrival load 8 requests/100 seconds

| Metric | Top five methods (rank order; values in stated units) | Proposal rank/32 | Proposal value |
|---|---|---:|---:|
| Acceptance ↑ (%) | ProposedAdaptive (69.9909) > GreenCostRouting (68.7976) > FullJointRepair (68.6823) > CompactNoRepair (68.507) > AlwaysJointRouting (65.7393) | 1 | 69.9909 |
| Admission revenue/cost ↑ (ratio) | VirnePSO (0.752192) > VirneRWMaxMatch (0.698913) > VirneGRC (0.695906) > CompactNoRepair (0.689782) > GreenCostRouting (0.683639) | 6 | 0.677951 |
| Served revenue/cost ↑ (ratio) | VirnePSO (0.751625) > VirneRWMaxMatch (0.698149) > VirneGRC (0.696612) > CompactNoRepair (0.689561) > GreenCostRouting (0.68237) | 6 | 0.679194 |
| Total energy ↓ (Wh) | VirneFFD (45591.6) > VirneRWMaxMatch (48846.3) > VirneGRC (50047.7) > EnergyAware (55131.9) > GreedyCSP (67217.5) | 32 | 89568.7 |
| Energy/accepted request ↓ (Wh/request) | GreenCostRouting (80.0036) > CompactNoRepair (80.4597) > ProposedAdaptive (80.7006) > FullJointRepair (80.7709) > NoCompactPlacement (81.9321) | 3 | 80.7006 |
| Energy/served request-second ↓ (Wh/request-second) | CompactNoRepair (0.165624) > GreenCostRouting (0.165665) > ProposedAdaptive (0.166458) > FullJointRepair (0.167202) > NoCompactPlacement (0.169403) | 3 | 0.166458 |
| Energy/served CPU-second ↓ (Wh/CPU-unit-second) | ProposedAdaptive (0.00121938) > CompactNoRepair (0.00123457) > GreenCostRouting (0.00123695) > FullJointRepair (0.00124033) > NoCompactPlacement (0.00128792) | 1 | 0.00121938 |
| Energy/served BW-second ↓ (Wh/BW-unit-second) | ProposedAdaptive (0.000527968) > FullJointRepair (0.00054623) > CompactNoRepair (0.000546974) > GreenCostRouting (0.000549049) > FixedEnergyWeight (0.000579456) | 1 | 0.000527968 |
| Mean embedding time ↓ (ms) | GreedyCSP (1.03045) > VirneFFD (1.5235) > VirneGRC (1.86607) > VirneRWMaxMatch (2.16486) > VirneRWBFS (2.60645) | 9 | 6.62621 |
| P95 embedding time ↓ (ms) | VirneFFD (2.73486) > VirneGRC (3.19374) > VirneRWMaxMatch (3.59282) > GreedyCSP (3.70194) > VirneRWBFS (5.07723) | 10 | 24.5792 |
| P99 embedding time ↓ (ms) | VirneFFD (3.62199) > VirneGRC (4.20769) > VirneRWMaxMatch (4.60044) > GreedyCSP (5.79168) > VirneRWBFS (7.11483) | 11 | 48.3862 |
| Total embedding time ↓ (seconds) | GreedyCSP (1.63483) > VirneFFD (2.41964) > VirneGRC (2.96277) > VirneRWMaxMatch (3.43758) > VirneRWBFS (4.13858) | 9 | 10.523 |
| Mean hops ↓ (hops) | VirnePSO (1.50037) > VirneRWMaxMatch (1.64993) > CompactNoRepair (1.65194) > VirneGRC (1.65882) > GreenCostRouting (1.67248) | 6 | 1.70196 |
| CPU utilization (highest usage) ↑ (%) | ProposedAdaptive (73.7615) > FullJointRepair (71.2203) > CompactNoRepair (71.1008) > GreenCostRouting (70.8551) > AlwaysJointRouting (67.2328) | 1 | 73.7615 |
| BW utilization (highest usage) ↑ (%) | NodeRankSearch (57.1405) > GRCRankedSearch (56.5627) > NodeRankScoreOnly (55.9932) > GRCScoreOnly (55.161) > FixedEnergyWeight (54.553) | 15 | 51.9546 |

## Arrival load 10 requests/100 seconds

| Metric | Top five methods (rank order; values in stated units) | Proposal rank/32 | Proposal value |
|---|---|---:|---:|
| Acceptance ↑ (%) | ProposedAdaptive (59.9651) > GreenCostRouting (59.4588) > CompactNoRepair (59.3464) > FullJointRepair (58.8835) > NoCompactPlacement (57.6685) | 1 | 59.9651 |
| Admission revenue/cost ↑ (ratio) | VirnePSO (0.754889) > VirneRWMaxMatch (0.700839) > VirneGRC (0.697312) > CompactNoRepair (0.675905) > GreenCostRouting (0.669116) | 7 | 0.664791 |
| Served revenue/cost ↑ (ratio) | VirnePSO (0.755081) > VirneRWMaxMatch (0.700616) > VirneGRC (0.697063) > CompactNoRepair (0.675577) > GreenCostRouting (0.668648) | 7 | 0.66575 |
| Total energy ↓ (Wh) | VirneFFD (49935.9) > VirneRWMaxMatch (53767.3) > VirneGRC (54789.9) > EnergyAware (58713.1) > GreedyCSP (69482.1) | 32 | 91894.2 |
| Energy/accepted request ↓ (Wh/request) | GreenCostRouting (76.6152) > CompactNoRepair (76.7857) > VirnePSO (76.9416) > ProposedAdaptive (77.4355) > NoCompactPlacement (77.5175) | 4 | 77.4355 |
| Energy/served request-second ↓ (Wh/request-second) | GreenCostRouting (0.157273) > CompactNoRepair (0.157427) > VirnePSO (0.158294) > ProposedAdaptive (0.158894) > FullJointRepair (0.159436) | 4 | 0.158894 |
| Energy/served CPU-second ↓ (Wh/CPU-unit-second) | ProposedAdaptive (0.00119706) > CompactNoRepair (0.00120585) > GreenCostRouting (0.00120768) > FullJointRepair (0.0012133) > NoCompactPlacement (0.00124737) | 1 | 0.00119706 |
| Energy/served BW-second ↓ (Wh/BW-unit-second) | ProposedAdaptive (0.000533427) > FullJointRepair (0.000549115) > CompactNoRepair (0.000549694) > GreenCostRouting (0.000551506) > AlwaysJointRouting (0.000580413) | 1 | 0.000533427 |
| Mean embedding time ↓ (ms) | GreedyCSP (0.909609) > VirneFFD (1.60434) > VirneGRC (2.026) > VirneRWMaxMatch (2.23347) > VirneRWBFS (2.70648) | 9 | 6.37753 |
| P95 embedding time ↓ (ms) | VirneFFD (2.90379) > GreedyCSP (3.36058) > VirneGRC (3.49624) > VirneRWMaxMatch (3.6317) > VirneRWBFS (5.03996) | 10 | 24.1478 |
| P99 embedding time ↓ (ms) | VirneFFD (3.85152) > VirneGRC (4.52812) > VirneRWMaxMatch (4.5764) > GreedyCSP (5.37111) > VirneRWBFS (6.92384) | 11 | 46.7007 |
| Total embedding time ↓ (seconds) | GreedyCSP (1.801) > VirneFFD (3.17726) > VirneGRC (4.01224) > VirneRWMaxMatch (4.42379) > VirneRWBFS (5.35917) | 9 | 12.6321 |
| Mean hops ↓ (hops) | VirnePSO (1.49876) > VirneRWMaxMatch (1.64951) > VirneGRC (1.65986) > CompactNoRepair (1.70371) > GreenCostRouting (1.72765) | 6 | 1.75268 |
| CPU utilization (highest usage) ↑ (%) | ProposedAdaptive (77.0865) > CompactNoRepair (75.1136) > FullJointRepair (75.0639) > GreenCostRouting (74.9605) > AlwaysJointRouting (71.4809) | 1 | 77.0865 |
| BW utilization (highest usage) ↑ (%) | NodeRankSearch (58.9421) > GRCRankedSearch (58.8062) > NodeRankScoreOnly (58.1181) > GRCScoreOnly (57.4055) > FixedEnergyWeight (56.6067) | 15 | 54.2911 |

## Arrival load 12 requests/100 seconds

| Metric | Top five methods (rank order; values in stated units) | Proposal rank/32 | Proposal value |
|---|---|---:|---:|
| Acceptance ↑ (%) | GreenCostRouting (52.4063) > ProposedAdaptive (52.4024) > CompactNoRepair (52.4008) > FullJointRepair (51.9341) > NoCompactPlacement (51.0625) | 2 | 52.4024 |
| Admission revenue/cost ↑ (ratio) | VirnePSO (0.758832) > VirneRWMaxMatch (0.700705) > VirneGRC (0.696515) > VirneFFD (0.667459) > CompactNoRepair (0.665553) | 7 | 0.656908 |
| Served revenue/cost ↑ (ratio) | VirnePSO (0.758617) > VirneRWMaxMatch (0.700859) > VirneGRC (0.696668) > VirneFFD (0.667183) > CompactNoRepair (0.665869) | 7 | 0.65584 |
| Total energy ↓ (Wh) | VirneFFD (53795.2) > VirneRWMaxMatch (57032.3) > VirneGRC (58613.8) > EnergyAware (60972.6) > GreedyCSP (71488.9) | 32 | 93311.2 |
| Energy/accepted request ↓ (Wh/request) | VirnePSO (72.7245) > CompactNoRepair (73.8696) > GreenCostRouting (73.8888) > NoCompactPlacement (74.5546) > NoJointRepair (74.7378) | 7 | 74.9897 |
| Energy/served request-second ↓ (Wh/request-second) | VirnePSO (0.149095) > GreenCostRouting (0.151966) > CompactNoRepair (0.152088) > FullJointRepair (0.153685) > NoCompactPlacement (0.153689) | 6 | 0.154003 |
| Energy/served CPU-second ↓ (Wh/CPU-unit-second) | ProposedAdaptive (0.00118481) > CompactNoRepair (0.00118882) > GreenCostRouting (0.00119005) > FullJointRepair (0.00119683) > NoJointRepair (0.00122369) | 1 | 0.00118481 |
| Energy/served BW-second ↓ (Wh/BW-unit-second) | ProposedAdaptive (0.000538329) > FullJointRepair (0.000553554) > CompactNoRepair (0.000553829) > GreenCostRouting (0.000554992) > EagerPacking=EagerPathGeneration=LegacyAdaptive=QoSBoundRouting (0.00058035) | 1 | 0.000538329 |
| Mean embedding time ↓ (ms) | GreedyCSP (0.838094) > VirneFFD (1.52519) > VirneGRC (1.83108) > VirneRWMaxMatch (2.2096) > VirneRWBFS (2.51091) | 9 | 5.71839 |
| P95 embedding time ↓ (ms) | VirneFFD (2.80235) > VirneGRC (3.16777) > GreedyCSP (3.18812) > VirneRWMaxMatch (3.66465) > VirneRWBFS (4.60508) | 10 | 21.9052 |
| P99 embedding time ↓ (ms) | VirneFFD (3.77006) > VirneGRC (4.18478) > VirneRWMaxMatch (4.65814) > GreedyCSP (5.25301) > VirneRWBFS (6.41311) | 11 | 44.419 |
| Total embedding time ↓ (seconds) | GreedyCSP (1.99187) > VirneFFD (3.6258) > VirneGRC (4.35305) > VirneRWMaxMatch (5.25497) > VirneRWBFS (5.96887) | 9 | 13.5948 |
| Mean hops ↓ (hops) | VirnePSO (1.49271) > VirneRWMaxMatch (1.65369) > VirneGRC (1.66733) > CompactNoRepair (1.74456) > GreenCostRouting (1.7645) | 7 | 1.78527 |
| CPU utilization (highest usage) ↑ (%) | ProposedAdaptive (79.0848) > CompactNoRepair (77.6697) > GreenCostRouting (77.6162) > FullJointRepair (77.4944) > FixedEnergyWeight (74.2819) | 1 | 79.0848 |
| BW utilization (highest usage) ↑ (%) | NodeRankSearch (60.4271) > GRCRankedSearch (60.0793) > NodeRankScoreOnly (59.6644) > GRCScoreOnly (58.8909) > FixedEnergyWeight (57.9467) | 15 | 55.8042 |

## Paired checks of relevant controls

The following comparisons use the run's seed-paired Wilcoxon tests and BH correction across2604 valid tests. Only comparisons against ProposedAdaptive exist; other methods' ordinal ranks are not pairwise significance claims.

| Control | Metric | Loads favoring proposal (q<0.05) | Loads favoring control (q<0.05) | Remaining loads |
|---|---|---|---|---|
| LegacyAdaptive | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| LegacyAdaptive | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| LegacyAdaptive | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| LegacyAdaptive | Energy/served request-second | 2, 4, 6, 8, 10, 12 | none | none |
| LegacyAdaptive | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| CompactNoRepair | Acceptance | 2, 4, 6, 8, 10 | none | 12 |
| CompactNoRepair | Admission revenue/cost | 2 | 6, 8, 10, 12 | 4 |
| CompactNoRepair | Served revenue/cost | none | 6, 8, 10, 12 | 2, 4 |
| CompactNoRepair | Energy/served request-second | 2, 4, 6 | 8, 10, 12 | none |
| CompactNoRepair | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| FullJointRepair | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| FullJointRepair | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| FullJointRepair | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| FullJointRepair | Energy/served request-second | 2, 4, 6, 8, 10 | none | 12 |
| FullJointRepair | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| NoCompactPlacement | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| NoCompactPlacement | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| NoCompactPlacement | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| NoCompactPlacement | Energy/served request-second | 2, 4, 6, 8, 10 | none | 12 |
| NoCompactPlacement | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| GreenCostRouting | Acceptance | 2, 4, 6, 8, 10 | none | 12 |
| GreenCostRouting | Admission revenue/cost | 2, 4 | 6, 8, 10, 12 | none |
| GreenCostRouting | Served revenue/cost | 2, 4 | 12 | 6, 8, 10 |
| GreenCostRouting | Energy/served request-second | 4, 6 | 2, 8, 10, 12 | none |
| GreenCostRouting | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| QoSBoundRouting | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| QoSBoundRouting | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| QoSBoundRouting | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| QoSBoundRouting | Energy/served request-second | 2, 4, 6, 8, 10, 12 | none | none |
| QoSBoundRouting | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| NoJointRepair | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| NoJointRepair | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| NoJointRepair | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| NoJointRepair | Energy/served request-second | 2, 4, 6, 8, 10 | none | 12 |
| NoJointRepair | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| NoExactPacking | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| NoExactPacking | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| NoExactPacking | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| NoExactPacking | Energy/served request-second | 2, 4, 6, 8, 10, 12 | none | none |
| NoExactPacking | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| ConflictRepair | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| ConflictRepair | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| ConflictRepair | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| ConflictRepair | Energy/served request-second | 2, 4, 6, 8, 10, 12 | none | none |
| ConflictRepair | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |
| AlwaysJointRouting | Acceptance | 2, 4, 6, 8, 10, 12 | none | none |
| AlwaysJointRouting | Admission revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| AlwaysJointRouting | Served revenue/cost | 2, 4, 6, 8, 10, 12 | none | none |
| AlwaysJointRouting | Energy/served request-second | 2, 4, 6, 8, 10, 12 | none | none |
| AlwaysJointRouting | Mean embedding time | 2, 4, 6, 8, 10, 12 | none | none |

Runtime reflects 4 worker(s). The primary competitors are pinned Virne ports with documented QoS and execution adaptations. This run does not establish superiority over unrun complete published methods, real-topology generalization or novelty.

Machine-readable outputs: [all ranks](all_rankings.csv), [top five including ties](top_five.csv), [proposal positions](proposal_positions.csv) and [six-method primary-only ranks](primary_only_rankings.csv).
