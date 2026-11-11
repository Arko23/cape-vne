"""Validated VNE policies and explicitly scoped comparison algorithms.

GRC and NodeRank reproduce ranking equations, with adapted routing.
GreedyKSP, EnergyAware and PSO are custom controls, not full paper reproductions.
"""
from __future__ import annotations
import heapq
import math
import random
from collections import defaultdict
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple
import numpy as np
from .models import EPS, SubstrateNetwork, VirtualEdge, VirtualNetworkRequest, canonical_edge
from .pruning import first_hop_packing_possible

DEFAULT_ALGORITHMS = (
    "ProposedAdaptive",
    "GRC",
    "NodeRank",
    "GreedyKSP",
    "EnergyAware",
)
OPTIONAL_PSO = "PSO"

# Preserve stable CSV identifiers while making the scientific scope explicit.
ALGORITHM_SCOPE = {
    "ProposedAdaptive": "Necessary injective host-domain matching, greedy construction then membership-only constrained-node recovery with shared quotas, cached joint hop/delay domains, unchanged compact/power placement scores and power-aware two-hop routing; heuristic online VNE",
    "LegacyAdaptive": "Frozen-policy previous proposal: power/headroom heuristic with green routing, selective packing and joint repair",
    "GRC": "Gong 2014 GRC ranks; shared QoS routing adaptation",
    "NodeRank": "Cheng 2011 NodeRank ranks; shared QoS routing adaptation",
    "GreedyKSP": "Custom CPU-fraction greedy mapping with bounded joint K-path routing",
    "EnergyAware": "Custom marginal-node-power packing; not a published EA-VNE reproduction",
    "PSO": "Custom discrete PSO minimizing admission resource cost; not RW-PSO or EA-VNE-EPSO",
    "ProposedGreedy": "Current green policy with one placement candidate",
    "GRCRankedSearch": "GRC ranks with current green search/router, feasibility checks and budgets",
    "NodeRankSearch": "NodeRank ranks with current green search/router, feasibility checks and budgets",
    "GreedyCSP": "Custom greedy mapping with one constrained path per virtual link",
    "GRCScoreOnly": "GRC substrate score only; proposed virtual-node order, filters and router",
    "NodeRankScoreOnly": "NodeRank substrate score only; proposed virtual-node order, filters and router",
    "NoExactPacking": "Proposed policy with threshold cuts only; exact first-hop packing disabled",
    "NoCutPruning": "Proposed policy without incident threshold or exact packing cuts",
    "FixedEnergyWeight": "Proposed policy without load adaptation of the energy weight",
    "AlwaysJointRouting": "Proposed policy routing all closed links jointly on every placement",
    "NoJointRepair": "Proposed policy with incremental K=1 routing and no joint repair",
    "FullHopFootprint": "Experimental full per-hop footprint coefficient 1.0; may trade acceptance for resource cost",
    "EagerPacking": "Proposed policy checking exact packing for all scored candidates before shortlisting",
    "EagerPathGeneration": "Proposed policy generating all K route alternatives before trying the first path",
    "ConflictRepair": "Experimental current-request conflict repair with shared route-state budget and full fallback; not VNE-CBS",
    "QoSBoundRouting": "Experimental admissible reverse hop/delay pruning on relaxed request-start bandwidth; established bounding technique, not a new published method",
    "CompactNoRepair": "Revised compact policy without joint route repair; placement recovery remains bounded",
    "FullJointRepair": "Revised compact policy with uncapped link-set size for the original bounded joint repair",
    "NoCompactPlacement": "Revised compact policy without the bandwidth-weighted placement distance penalty",
    "GreenCostRouting": "Revised compact placement/profile engine with the previous weighted green route objective",
}
REFERENCE_ALGORITHMS = ('VirneGRC', 'VirneRWMaxMatch', 'VirneRWBFS', 'VirneFFD', 'VirnePSO')
ALGORITHM_SCOPE.update({
    'VirneGRC': 'Pinned Virne GRC two-stage/K10 reference port; common hard QoS extension; no paper profit-threshold claim',
    'VirneRWMaxMatch': 'Pinned Virne RW rank two-stage/K10 reference port; common hard QoS extension',
    'VirneRWBFS': 'Pinned Virne RW-BFS placement and bandwidth BFS routing reference port; common hard QoS extension',
    'VirneFFD': 'Pinned Virne absolute-resource FFD with sequential K10 paths; common hard QoS extension',
    'VirnePSO': 'Pinned Virne equality-bit PSO (8x12, .1/.2/.7, cost/revenue); corrected parent-visible serial evolution; common hard QoS extension',
})
LEGACY_CONTROLS = (
    'ProposedGreedy', 'GRCRankedSearch', 'NodeRankSearch', 'GRCScoreOnly',
    'NodeRankScoreOnly', 'NoExactPacking', 'NoCutPruning', 'FixedEnergyWeight',
    'AlwaysJointRouting', 'NoJointRepair', 'FullHopFootprint', 'EagerPacking',
    'EagerPathGeneration', 'ConflictRepair', 'QoSBoundRouting')
for _legacy_name in LEGACY_CONTROLS:
    ALGORITHM_SCOPE[_legacy_name] = 'Previous-proposal control: ' + ALGORITHM_SCOPE[_legacy_name]
for _compact_name in ('CompactNoRepair', 'FullJointRepair', 'NoCompactPlacement', 'GreenCostRouting'):
    ALGORITHM_SCOPE[_compact_name] = 'Previous compact-proposal control: ' + ALGORITHM_SCOPE[_compact_name]


class BaseVNEAlgorithm:
    """Common bounded routing, reservations, and validated atomic commits."""

    name = "Base"

    def __init__(
        self,
        substrate: SubstrateNetwork,
        rng: Optional[random.Random] = None,
        k_paths: int = 3,
        candidate_limit: int = 10,
        route_budget: int = 3000,
        path_expansion_budget: int = 20000,
    ):
        self.sn = substrate
        self.rng = rng or random.Random(0)
        self.k_paths = max(1, int(k_paths))
        self.candidate_limit = max(1, int(candidate_limit))
        self.route_budget = max(1, int(route_budget))
        self.path_expansion_budget = max(1, int(path_expansion_budget))
        self.history: List[float] = []
        self.route_expansions = 0
        self.route_search_nodes = 0
        self.route_budget_exhaustions = 0
        self.path_budget_exhaustions = 0
        self.last_route_failure_reason: Optional[str] = None
        self.last_commit_validation_error: Optional[str] = None

    def bfs_distance(
        self, source: int, target: int, max_depth: int = 8
    ) -> Optional[int]:
        if source == target:
            return 0
        queue = [(source, 0)]
        seen = {source}
        while queue:
            node, depth = queue.pop(0)
            if depth >= max_depth:
                continue
            for nxt in sorted(self.sn.neighbors[node]):
                if nxt == target:
                    return depth + 1
                if nxt not in seen:
                    seen.add(nxt)
                    queue.append((nxt, depth + 1))
        return None

    def _label_dominated(
        self, labels: List[Tuple[float, float, int, Tuple[int, ...]]],
        cost: float,
        delay: float,
        hops: int,
    ) -> bool:
        # A label is dominated if another label is no worse in all constrained
        # dimensions and has no greater route cost.
        return any(
            old_cost <= cost + EPS
            and old_delay <= delay + EPS
            and old_hops <= hops
            for old_cost, old_delay, old_hops, _ in labels
        )

    def _constrained_shortest_path(
        self,
        source: int,
        target: int,
        request_bw: float,
        max_delay: float,
        max_hops: int,
        state: Dict[str, Dict],
        removed_edges: Optional[Set[Tuple[int, int]]] = None,
        removed_nodes: Optional[Set[int]] = None,
        max_expansions: int = 20000,
    ) -> Optional[List[int]]:
        """Bounded label-setting search for one feasible simple path."""
        if (not math.isfinite(request_bw) or request_bw < 0
                or not math.isfinite(max_delay) or max_delay < -EPS
                or max_hops < 0 or source not in self.sn.neighbors
                or target not in self.sn.neighbors):
            return None
        if source == target:
            return [source]
        removed_edges = removed_edges or set()
        removed_nodes = removed_nodes or set()
        if source in removed_nodes or target in removed_nodes:
            return None
        max_expansions = min(max_expansions, self.path_expansion_budget)

        queue = [(0.0, 0.0, 0, source, (source,))]
        labels: Dict[int, List[Tuple[float, float, int, Tuple[int, ...]]]] = (
            defaultdict(list)
        )
        labels[source].append((0.0, 0.0, 0, (source,)))
        expansions = 0

        while queue and expansions < max_expansions:
            cost, delay, hops, node, path_tuple = heapq.heappop(queue)
            expansions += 1
            self.route_expansions += 1
            if node == target:
                return list(path_tuple)
            if hops >= max_hops:
                continue
            for nxt in sorted(self.sn.neighbors[node]):
                if nxt in removed_nodes or nxt in path_tuple:
                    continue
                directed = (node, nxt)
                undirected = canonical_edge(node, nxt)
                if directed in removed_edges or undirected in removed_edges:
                    continue
                if state["bw"][undirected] + EPS < request_bw:
                    continue
                new_delay = delay + self.sn.link_delay(node, nxt)
                new_hops = hops + 1
                if new_delay > max_delay + EPS:
                    continue
                utilization = 1.0 - (
                    state["bw"][undirected]
                    / max(self.sn.bandwidth_capacity[undirected], EPS)
                )
                new_cost = cost + self.sn.link_delay(node, nxt) * (
                    1.0 + max(0.0, utilization)
                )
                new_path = path_tuple + (nxt,)
                if self._label_dominated(
                    labels[nxt], new_cost, new_delay, new_hops
                ):
                    continue
                labels[nxt] = [
                    old for old in labels[nxt]
                    if not (
                        new_cost <= old[0] + EPS
                        and new_delay <= old[1] + EPS
                        and new_hops <= old[2]
                    )
                ]
                labels[nxt].append((new_cost, new_delay, new_hops, new_path))
                heapq.heappush(
                    queue, (new_cost, new_delay, new_hops, nxt, new_path)
                )
        if queue and expansions >= max_expansions:
            self.path_budget_exhaustions += 1
        return None

    def find_shortest_paths(
        self,
        source: int,
        target: int,
        request_bw: float,
        max_delay: float,
        max_hops: int,
        state: Dict[str, Dict],
        k: Optional[int] = None,
    ) -> List[List[int]]:
        """Up to K distinct feasible simple paths; each spur search is bounded."""
        return list(self.iter_shortest_paths(source, target, request_bw, max_delay,
                                             max_hops, state, k))

    def iter_shortest_paths(
        self, source: int, target: int, request_bw: float, max_delay: float,
        max_hops: int, state: Dict[str, Dict], k: Optional[int] = None,
    ) -> Iterator[List[int]]:
        """Generate alternatives in the same order, only when requested.

        The caller must leave state unchanged while advancing the iterator.
        Routing backtracking reserves bandwidth on separate branch states.
        """
        k = self.k_paths if k is None else max(1, int(k))
        first = self._constrained_shortest_path(
            source, target, request_bw, max_delay, max_hops, state
        )
        if not first:
            return
        paths = [first]
        yield first
        accepted = {tuple(first)}
        candidates = []
        queued = set()
        for _ in range(1, k):
            previous = paths[-1]
            for spur_index in range(len(previous) - 1):
                root = previous[:spur_index + 1]
                removed_edges = {
                    canonical_edge(old[spur_index], old[spur_index + 1])
                    for old in paths
                    if len(old) > spur_index + 1
                    and old[:spur_index + 1] == root
                }
                root_delay = self.path_delay(root)
                root_hops = len(root) - 1
                if root_delay > max_delay + EPS or root_hops >= max_hops:
                    continue
                spur = self._constrained_shortest_path(
                    root[-1], target, request_bw, max_delay - root_delay,
                    max_hops - root_hops, state,
                    removed_edges=removed_edges, removed_nodes=set(root[:-1]),
                )
                if not spur:
                    continue
                candidate = tuple(root[:-1] + spur)
                if candidate in accepted or candidate in queued:
                    continue
                if (self.path_delay(candidate) > max_delay + EPS
                        or self.path_hops(candidate) > max_hops):
                    continue
                heapq.heappush(candidates, (self.path_cost(candidate, state), candidate))
                queued.add(candidate)
            chosen = None
            while candidates:
                _, candidate = heapq.heappop(candidates)
                queued.discard(candidate)
                if candidate not in accepted:
                    chosen = candidate
                    break
            if chosen is None:
                break
            accepted.add(chosen)
            paths.append(list(chosen))
            yield paths[-1]

    def _path_options(self, source, target, bandwidth, delay, hops, state, k):
        # Baselines retain their eager search policy and its measured work.
        return self.find_shortest_paths(source, target, bandwidth, delay, hops, state, k)

    def path_cost(self, path: Sequence[int], state: Dict[str, Dict]) -> float:
        total = 0.0
        for u, v in zip(path, path[1:]):
            edge = canonical_edge(u, v)
            util = 1.0 - state["bw"][edge] / max(
                self.sn.bandwidth_capacity[edge], EPS
            )
            total += self.sn.link_delay(u, v) * (1.0 + max(0.0, util))
        return total

    def path_delay(self, path: Sequence[int]) -> float:
        return self.sn.path_delay(path)

    def path_hops(self, path: Sequence[int]) -> int:
        return self.sn.path_hops(path)

    def reserve_cpu(
        self, state: Dict[str, Dict], node: int, demand: float
    ) -> bool:
        if (not math.isfinite(demand) or demand < 0
                or node not in state["cpu"]
                or state["cpu"][node] + EPS < demand):
            return False
        state["cpu"][node] -= demand
        return True

    def reserve_path(
        self, state: Dict[str, Dict], path: Sequence[int], bandwidth: float
    ) -> bool:
        if not path or len(set(path)) != len(path):
            return False
        if not math.isfinite(bandwidth) or bandwidth < 0:
            return False
        edges = [canonical_edge(u, v) for u, v in zip(path, path[1:])]
        if any(edge not in state["bw"] or state["bw"][edge] + EPS < bandwidth
               for edge in edges):
            return False
        for edge in edges:
            state["bw"][edge] -= bandwidth
        return True

    def route_link_set(
        self,
        vnr: VirtualNetworkRequest,
        mapping: Dict[int, int],
        state: Dict[str, Dict],
        k: Optional[int] = None,
        edge_subset: Optional[Sequence[VirtualEdge]] = None,
    ) -> Optional[Dict[Tuple[int, int], List[int]]]:
        """Route links with bounded path-combination backtracking, atomically.

        Each call explores at most route_budget recursive states and up to K
        alternatives at each edge. A failure is not a proof of infeasibility.
        The supplied private state must not already reserve the subset's BW.
        CPU and reservations belonging to other requests remain untouched.
        """
        self.last_route_failure_reason = None
        ordered_edges = sorted(
            vnr.edges if edge_subset is None else edge_subset,
            key=lambda e: (-e.bandwidth, e.u, e.v),
        )
        if not ordered_edges:
            return {}
        if not self.sn.state_is_valid(state):
            self.last_route_failure_reason = "invalid_private_state"
            return None
        if any(e.u not in mapping or e.v not in mapping for e in ordered_edges):
            self.last_route_failure_reason = "unmapped_virtual_endpoint"
            return None
        keys = [(e.u, e.v) for e in ordered_edges]
        if len(set(keys)) != len(keys):
            self.last_route_failure_reason = "duplicate_virtual_edge"
            return None
        k_value = self.k_paths if k is None else max(1, int(k))
        visited = 0
        exhausted = False
        path_exhaustions_before = self.path_budget_exhaustions

        def search(index, trial_state, chosen_paths):
            nonlocal visited, exhausted
            if visited >= self.route_budget:
                exhausted = True
                return None
            visited += 1
            self.route_search_nodes += 1
            if index == len(ordered_edges):
                return trial_state, chosen_paths
            edge = ordered_edges[index]
            options = self._path_options(
                mapping[edge.u], mapping[edge.v], edge.bandwidth,
                vnr.max_delay, vnr.max_hops, trial_state, k_value,
            )
            for path in options:
                branch_state = self.sn.clone_state(trial_state)
                if not self.reserve_path(branch_state, path, edge.bandwidth):
                    continue
                branch_paths = dict(chosen_paths)
                branch_paths[(edge.u, edge.v)] = path
                result = search(index + 1, branch_state, branch_paths)
                if result is not None:
                    return result
                if exhausted:
                    break
            return None

        result = search(0, self.sn.clone_state(state), {})
        if result is None:
            if exhausted:
                self.route_budget_exhaustions += 1
                self.last_route_failure_reason = "route_budget_exhausted"
            elif self.path_budget_exhaustions > path_exhaustions_before:
                self.last_route_failure_reason = "path_expansion_budget_exhausted"
            else:
                self.last_route_failure_reason = "no_route_within_k_paths"
            return None
        routed_state, paths = result
        state["cpu"] = routed_state["cpu"]
        state["bw"] = routed_state["bw"]
        return paths

    def commit_embedding(
        self,
        vnr: VirtualNetworkRequest,
        state: Dict[str, Dict],
        mapping: Dict[int, int],
        paths: Dict[Tuple[int, int], List[int]],
    ) -> Optional[Dict]:
        self.last_commit_validation_error = None
        try:
            cpu_used, bw_used = self._embedding_usage(vnr, mapping, paths)
            if not self.sn.state_is_valid(state):
                raise ValueError("Invalid candidate residual state")
            for node, residual in self.sn.cpu_residual.items():
                expected = residual - cpu_used.get(node, 0.0)
                if abs(state["cpu"][node] - expected) > 1e-7:
                    raise ValueError("Candidate CPU state does not match the embedding")
            for edge, residual in self.sn.bandwidth_residual.items():
                expected = residual - bw_used.get(edge, 0.0)
                if abs(state["bw"][edge] - expected) > 1e-7:
                    raise ValueError("Candidate bandwidth state does not match the embedding")
        except (ValueError, KeyError, TypeError) as error:
            self.last_commit_validation_error = str(error)
            return None
        node_cost = vnr.total_cpu
        link_cost = sum(bw_used.values())
        newly_powered = self.sn.powered_nodes(state) - self.sn.powered_nodes()
        boot_joules = len(newly_powered) * self.sn.boot_energy_joules
        self.sn.apply_state(state)
        return {
            "request_id": vnr.request_id,
            "mapping": dict(mapping),
            "paths": {key: list(path) for key, path in paths.items()},
            "cost": float(node_cost + link_cost),
            "revenue": float(node_cost + vnr.total_bandwidth),
            "boot_energy_joules": float(boot_joules),
            "newly_powered_nodes": len(newly_powered),
            "accepted_at": vnr.arrival,
            "departure": vnr.departure,
            "_released": False,
        }

    def release_embedding(self, vnr: VirtualNetworkRequest, embedding: Dict) -> None:
        """Validate and restore atomically; do not mask over-release by clamping."""
        if embedding.get("request_id") != vnr.request_id:
            raise ValueError("Release request ID does not match the embedding")
        if embedding.get("_released", False):
            raise ValueError("Embedding has already been released")
        cpu_used, bw_used = self._embedding_usage(
            vnr, embedding["mapping"], embedding["paths"]
        )
        restored = self.sn.empty_state()
        if not self.sn.state_is_valid(restored):
            raise RuntimeError("Cannot release from an invalid substrate state")
        for node, demand in cpu_used.items():
            restored["cpu"][node] += demand
        for edge, demand in bw_used.items():
            restored["bw"][edge] += demand
        if not self.sn.state_is_valid(restored):
            raise RuntimeError("Release would exceed physical resource capacities")
        self.sn.apply_state(restored)
        embedding["_released"] = True

    def node_order(self, vnr: VirtualNetworkRequest) -> List[int]:
        degree = defaultdict(int)
        for edge in vnr.edges:
            degree[edge.u] += 1
            degree[edge.v] += 1
        return sorted(
            vnr.nodes,
            key=lambda n: (vnr.node_cpu[n], degree[n]),
            reverse=True,
        )

    def map_nodes_by_score(
        self,
        vnr: VirtualNetworkRequest,
        score: Dict[int, float],
        order: Optional[Sequence[int]] = None,
    ) -> Optional[Dict[int, int]]:
        selected_order = self.node_order(vnr) if order is None else list(order)
        if len(selected_order) != len(vnr.nodes) or set(selected_order) != set(vnr.nodes):
            raise ValueError("Virtual-node order must include each request node once")
        mapping = {}
        used = set()
        candidates = sorted(
            self.sn.cpu_residual,
            key=lambda p: (-score.get(p, -math.inf), -self.sn.cpu_residual[p], p),
        )
        for vnode in selected_order:
            selected = next(
                (p for p in candidates if p not in used
                 and self.sn.cpu_residual[p] + EPS >= vnr.node_cpu[vnode]),
                None,
            )
            if selected is None:
                return None
            mapping[vnode] = selected
            used.add(selected)
        return mapping

    def embed(self, vnr: VirtualNetworkRequest) -> Optional[Dict]:
        raise NotImplementedError

    def _embedding_usage(
        self,
        vnr: VirtualNetworkRequest,
        mapping: Dict[int, int],
        paths: Dict[Tuple[int, int], List[int]],
    ) -> Tuple[Dict[int, float], Dict[Tuple[int, int], float]]:
        """Validate embedding geometry and independently total its resources."""
        if set(mapping) != set(vnr.node_cpu):
            raise ValueError("Mapping must cover every virtual node exactly once")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Node mapping must be injective within a request")
        if any(p not in self.sn.cpu_capacity for p in mapping.values()):
            raise ValueError("Mapping references an unknown substrate node")
        if (not math.isfinite(vnr.max_delay) or vnr.max_delay < 0
                or not math.isfinite(vnr.max_hops) or vnr.max_hops < 0
                or int(vnr.max_hops) != vnr.max_hops):
            raise ValueError("Delay and hop constraints must be finite and nonnegative")
        edge_keys = [(edge.u, edge.v) for edge in vnr.edges]
        undirected_keys = [canonical_edge(edge.u, edge.v) for edge in vnr.edges]
        if len(set(undirected_keys)) != len(undirected_keys):
            raise ValueError("Virtual network must not contain duplicate undirected edges")
        if set(paths) != set(edge_keys):
            raise ValueError("Paths must cover exactly the virtual edges")
        cpu_used = defaultdict(float)
        bw_used = defaultdict(float)
        for vnode, demand in vnr.node_cpu.items():
            if not math.isfinite(demand) or demand < 0:
                raise ValueError("CPU demands must be finite and nonnegative")
            cpu_used[mapping[vnode]] += demand
        for edge in vnr.edges:
            if edge.u not in mapping or edge.v not in mapping or edge.u == edge.v:
                raise ValueError("Virtual links must connect two mapped distinct nodes")
            if not math.isfinite(edge.bandwidth) or edge.bandwidth < 0:
                raise ValueError("Bandwidth demands must be finite and nonnegative")
            path = paths[(edge.u, edge.v)]
            if not path or path[0] != mapping[edge.u] or path[-1] != mapping[edge.v]:
                raise ValueError("Path endpoints do not match the virtual-node mapping")
            if len(set(path)) != len(path):
                raise ValueError("Substrate paths must be simple")
            if any(node not in self.sn.cpu_capacity for node in path):
                raise ValueError("Path references an unknown substrate node")
            physical_edges = [canonical_edge(u, v) for u, v in zip(path, path[1:])]
            if any(link not in self.sn.bandwidth_capacity for link in physical_edges):
                raise ValueError("Path traverses a nonexistent substrate link")
            if self.path_hops(path) > vnr.max_hops:
                raise ValueError("Path exceeds the hop constraint")
            if self.path_delay(path) > vnr.max_delay + EPS:
                raise ValueError("Path exceeds the delay constraint")
            for link in physical_edges:
                bw_used[link] += edge.bandwidth
        return dict(cpu_used), dict(bw_used)


class BoundedPlacementVNE(BaseVNEAlgorithm):
    """Private bounded placement search and one validated final commit."""

    def __init__(
        self,
        substrate: SubstrateNetwork,
        rng: Optional[random.Random] = None,
        k_paths: int = 3,
        candidate_limit: int = 8,
        search_budget: int = 3000,
    ):
        super().__init__(substrate, rng, k_paths, candidate_limit)
        self.search_budget = max(1, int(search_budget))
        self.search_nodes = 0
        self.last_search_nodes = 0
        self.search_budget_exhaustions = 0
        self.last_search_budget_exhausted = False
        self.last_failure_reason = None
        self.last_candidate_truncated = False
        self.last_routing_budget_exhausted = False
        self._request_profiles = {}


    def _mark_search_exhausted(self) -> None:
        if not self.last_search_budget_exhausted:
            self.last_search_budget_exhausted = True
            self.search_budget_exhaustions += 1


    def embed(self, vnr: VirtualNetworkRequest) -> Optional[Dict]:
        # Reset every per-request field before any early rejection.
        self.last_search_nodes = 0
        self.last_search_budget_exhausted = False
        self.last_candidate_truncated = False
        self.last_routing_budget_exhausted = False
        self.last_failure_reason = None
        self._request_profiles = {}
        if sum(self.sn.cpu_residual.values()) + EPS < vnr.total_cpu:
            self.last_failure_reason = "aggregate_cpu_capacity"
            return None
        if len(vnr.nodes) > self.sn.num_nodes:
            self.last_failure_reason = "distinct_node_capacity"
            return None
        result = self._backtrack(
            vnr, self.node_order(vnr), 0, {}, self.sn.empty_state(), {}
        )
        if result is None:
            if self.last_search_budget_exhausted:
                self.last_failure_reason = "node_search_budget_exhausted"
            elif self.last_routing_budget_exhausted:
                self.last_failure_reason = "routing_search_budget_exhausted"
            elif self.last_candidate_truncated:
                self.last_failure_reason = "candidate_limit_or_routing_failure"
            else:
                # Finite K and per-call route bounds preclude claiming that
                # failure certifies global substrate infeasibility.
                self.last_failure_reason = "bounded_search_no_embedding"
            return None
        mapping, state, paths = result
        embedding = self.commit_embedding(vnr, state, mapping, paths)
        if embedding is None:
            self.last_failure_reason = "commit_validation"
        return embedding


class LegacyAdaptiveVNE(BoundedPlacementVNE):
    """Green balanced VNE: incremental power + headroom + bounded fast repair.

    Prefer already-powered capacity without packing blindly onto bottlenecks.
    Route new links once (K=1); invoke joint K-path repair only on failure.
    Cache per-request link feasibility and prune impossible incident cuts.
    Node, joint-route and path-expansion budgets bound computational work.
    These are explicit multi-objective heuristic choices, not guarantees of
    lowest energy, highest acceptance, fastest runtime, or research novelty.
    All competitors and the shared accounting/constraints remain unchanged.
    """
    name = "LegacyAdaptive"

    def __init__(self, substrate, rng=None, k_paths=3, candidate_limit=8,
                 search_budget=24, energy_weight=0.45, path_expansion_budget=240, route_budget=24,
                 exact_packing=True, cut_pruning=True, adaptive_energy=True,
                 incremental_routing=True, joint_repair=True, packing_degree_limit=10,
                 selective_packing=True, lazy_paths=True, hop_footprint=0.25, conflict_repair=False,
                 qos_route_bounds=False):
        super().__init__(substrate,rng,k_paths,candidate_limit,search_budget)
        if not math.isfinite(energy_weight) or not 0 <= energy_weight <= 1:
            raise ValueError("energy_weight must be in [0,1]")
        self.energy_weight = float(energy_weight)
        self.path_expansion_budget = max(1,int(path_expansion_budget))
        self.route_budget = max(1,int(route_budget))
        self.exact_packing = bool(exact_packing)
        self.cut_pruning = bool(cut_pruning)
        self.adaptive_energy = bool(adaptive_energy)
        self.incremental_routing = bool(incremental_routing)
        self.joint_repair = bool(joint_repair)
        self.packing_degree_limit = max(1, int(packing_degree_limit))
        self.selective_packing = bool(selective_packing)
        self.lazy_paths = bool(lazy_paths)
        self.conflict_repair = bool(conflict_repair)
        self.conflict_repair_attempts = self.conflict_repair_successes = 0
        self.conflict_repair_fallbacks = self.conflict_repair_links = 0
        self.conflict_probe_expansions = self.conflict_local_states = self.conflict_fallback_states = 0
        self.qos_route_bounds = bool(qos_route_bounds)
        self.qos_bound_prunes = self.qos_bound_builds = 0
        self._routing_request_bw = None
        if not math.isfinite(hop_footprint) or hop_footprint < 0:
            raise ValueError("hop_footprint must be finite and nonnegative")
        self.hop_footprint = float(hop_footprint)
        self.cut_checks = self.cut_rejections = 0
        self.packing_checks = self.packing_rejections = self.packing_bypasses = 0
        self.fast_route_batches = self.fast_route_batch_links = 0
        self.always_joint_batches = 0
        self.fast_route_successes = 0
        self.joint_route_repairs = 0
        self.repair_successes = 0
        self.boot_amortization_seconds = 500.0  # fixed policy, not future lifetimes

    def embed(self, vnr):
        if not self.qos_route_bounds:
            return super().embed(vnr)
        # Previous tentative paths may be released by joint repair. Computing
        # cached bounds on that smaller residual graph would be unsound.
        self._routing_request_bw = dict(self.sn.bandwidth_residual)
        try:
            return super().embed(vnr)
        finally:
            self._routing_request_bw = None

    def _score_context(self,vnr,vnode,mapping,state,cache=None):
        cpu_pressure=1-sum(state['cpu'].values())/max(sum(self.sn.cpu_capacity.values()),EPS)
        bw_pressure=1-sum(state['bw'].values())/max(sum(self.sn.bandwidth_capacity.values()),EPS)
        cpu_weight,bw_weight=1+2*cpu_pressure,1+2*bw_pressure
        incident=[]
        for edge in vnr.edges:
            other=edge.v if edge.u==vnode else edge.u if edge.v==vnode else None
            if other is not None:
                incident.append((edge,self._link_profile(vnr,edge,mapping.get(other),state)))
        key=('node_cut',vnode)
        allowed=self._request_profiles.get(key)
        if allowed is None:
            demands=[e.bandwidth for e,_ in incident if e.bandwidth>EPS]
            total=sum(demands)
            thresholds={w:sum(d>=w for d in demands) for w in demands}
            allowed=set()
            for node,neighbors in self.sn.neighbors.items():
                if not self.cut_pruning:
                    allowed.add(node)
                    continue
                self.cut_checks += 1
                residuals=[state['bw'][canonical_edge(node,n)] for n in neighbors]
                # Necessary cut-capacity/count bounds, not greedy bin packing:
                # never reject solely because a heuristic packing attempt fails.
                if sum(residuals)+EPS*len(residuals)<total:
                    self.cut_rejections += 1
                    continue
                if any(sum(int((r+EPS)//w) for r in residuals)<count for w,count in thresholds.items()):
                    self.cut_rejections += 1
                    continue
                allowed.add(node)
            self._request_profiles[key]=allowed
        return {'powered':self.sn.powered_nodes(state),'incident':incident,'allowed':allowed,
                'cpu_weight':cpu_weight/(cpu_weight+bw_weight),
                'bw_weight':bw_weight/(cpu_weight+bw_weight),
                'pressure':max(cpu_pressure,bw_pressure)}

    def _node_score(self,vnr,vnode,pnode,mapping,state=None,context=None):
        state=self.sn.empty_state() if state is None else state
        if pnode in mapping.values() or state['cpu'][pnode]+EPS<vnr.node_cpu[vnode]:
            return -math.inf
        # Cache keys assume the unreserved request-start BW state. Public
        # one-off score calls get a fresh cache; embedding passes context.
        if context is None:
            previous=self._request_profiles
            self._request_profiles={}
            try:
                context=self._score_context(vnr,vnode,mapping,state)
                return self._node_score(vnr,vnode,pnode,mapping,state,context)
            finally:
                self._request_profiles=previous
        if pnode not in context['allowed']:
            return -math.inf
        demand=vnr.node_cpu[vnode]
        capacity=self.sn.cpu_capacity[pnode]
        wake=0. if pnode in context['powered'] else self.sn.p_idle+self.sn.boot_energy_joules/self.boot_amortization_seconds
        marginal=(wake+(self.sn.p_peak-self.sn.p_idle)*demand/capacity)/max(self.sn.p_peak,EPS)
        cpu_headroom=(state['cpu'][pnode]-demand)/capacity
        quality=0.
        total=0.
        for edge,profile in context['incident']:
            value=profile[pnode]
            if not math.isfinite(value):
                return -math.inf
            weight=max(edge.bandwidth,EPS)
            quality+=weight*value
            total+=weight
        if total:
            quality/=total
        if (self.cut_pruning and self.exact_packing and not context.get('defer_packing', False)
                and not self._first_hop_feasible(
            vnr, vnode, pnode, mapping, state
        )):
            return -math.inf
        energy_weight=self.energy_weight*(1-.45*context['pressure']) if self.adaptive_energy else self.energy_weight
        resources=context['cpu_weight']*cpu_headroom+context['bw_weight']*quality
        return (1-energy_weight)*resources-energy_weight*marginal

    def _destination_bounds(self, target, bandwidth, state, cache=None):
        """Independent optimistic hop/delay bounds, never bounded path failure."""
        cache = self._request_profiles if cache is None else cache
        key = ('destination_bounds', target, bandwidth)
        if key in cache:
            return cache[key]
        self.qos_bound_builds += 1
        hops = {target: 0}
        queue = [target]
        for node in queue:
            for neighbor in sorted(self.sn.neighbors[node]):
                edge = canonical_edge(node, neighbor)
                if state['bw'][edge] + EPS >= bandwidth and neighbor not in hops:
                    hops[neighbor] = hops[node] + 1
                    queue.append(neighbor)
        delays = {target: 0.0}
        heap = [(0.0, target)]
        while heap:
            delay, node = heapq.heappop(heap)
            if delay > delays[node] + EPS:
                continue
            for neighbor in sorted(self.sn.neighbors[node]):
                edge = canonical_edge(node, neighbor)
                if state['bw'][edge] + EPS < bandwidth:
                    continue
                candidate = delay + self.sn.link_delay(node, neighbor)
                if candidate < delays.get(neighbor, math.inf):
                    delays[neighbor] = candidate
                    heapq.heappush(heap, (candidate, neighbor))
        cache[key] = (hops, delays)
        return hops, delays

    def _first_hop_feasible(self, vnr, vnode, pnode, mapping, state):
        """Exact local packing on request-start BW; success is only necessary.

        Independent optimistic destination bounds permit extra ports, which can
        cause false positives but never prune a valid simple QoS route. Previous
        tentative routes are repairable, so their reservations must not be used.
        """
        incident = [(edge, edge.v if edge.u == vnode else edge.u)
                    for edge in vnr.edges if vnode in (edge.u, edge.v) and edge.bandwidth > EPS]
        if len(incident) > self.packing_degree_limit:
            self.packing_bypasses += 1
            return True
        key = ('packing', vnode, pnode, tuple((other, mapping.get(other)) for _, other in incident))
        if key in self._request_profiles:
            return self._request_profiles[key]
        ports = sorted(self.sn.neighbors[pnode])
        capacities = [state['bw'][canonical_edge(pnode, node)] for node in ports]
        domains = []
        for edge, other in incident:
            target = mapping.get(other)
            bounds = self._destination_bounds(target, edge.bandwidth, state) if target is not None else None
            eligible = []
            for index, neighbor in enumerate(ports):
                first_delay = self.sn.link_delay(pnode, neighbor)
                if capacities[index] + EPS < edge.bandwidth or vnr.max_hops < 1 or first_delay > vnr.max_delay + EPS:
                    continue
                if bounds is not None:
                    hops, delays = bounds
                    if 1 + hops.get(neighbor, math.inf) > vnr.max_hops:
                        continue
                    if first_delay + delays.get(neighbor, math.inf) > vnr.max_delay + EPS:
                        continue
                eligible.append(index)
            domains.append(eligible)
        self.packing_checks += 1
        result = first_hop_packing_possible([edge.bandwidth for edge, _ in incident], capacities,
                                           domains, self.packing_degree_limit)
        if result is False:
            self.packing_rejections += 1
        allowed = result is not False
        self._request_profiles[key] = allowed
        return allowed

    def _green_edge_cost(self,u,v,state,powered):
        edge=canonical_edge(u,v)
        residual=state['bw'][edge]
        capacity=self.sn.bandwidth_capacity[edge]
        utilization=max(0.,1-residual/capacity)
        watts=0.0 if residual<capacity-EPS else self.sn.p_link
        if v not in powered:
            watts+=self.sn.p_idle+self.sn.boot_energy_joules/self.boot_amortization_seconds
        # Nonnegative additive surrogate: marginal wake/link power, physical
        # footprint/congestion, and delay. Exact energy is measured by simulator.
        # The default retains its earlier service/energy tradeoff. A larger
        # footprint improves admission resource cost on development cases but
        # hurt held-out acceptance, so it remains an explicit control.
        return .50*watts/max(self.sn.p_idle,EPS)+.30*(self.hop_footprint+utilization**2)+.20*self.sn.link_delay(u,v)/25.

    def path_cost(self,path,state):
        powered=self.sn.powered_nodes(state)
        return sum(self._green_edge_cost(u,v,state,powered) for u,v in zip(path,path[1:]))

    def _path_options(self, source, target, bandwidth, delay, hops, state, k):
        if self.lazy_paths:
            return self.iter_shortest_paths(source, target, bandwidth, delay, hops, state, k)
        return super()._path_options(source, target, bandwidth, delay, hops, state, k)

    def _repair_routes(self, vnr, mapping, state, old_paths, closed, new_edges):
        """Optionally repair only request-local paths blocking relaxed probes.

        A probe is a neighborhood heuristic, not an infeasibility certificate.
        Unrelated current-request routes are retained during the local attempt;
        older admitted requests are never moved. Local and fallback calls share
        the original route-state budget. Probes add bounded path-search work,
        so this variant does not have an identical total-work budget.
        """
        budget = self.route_budget
        if self.conflict_repair and old_paths and new_edges and budget >= 6:
            relaxed = self.sn.clone_state(state)
            relaxed['bw'] = dict(self.sn.bandwidth_residual)
            blocked = set()
            unknown = False
            for edge in new_edges:
                before_probe = self.route_expansions
                options = self.find_shortest_paths(mapping[edge.u], mapping[edge.v],
                    edge.bandwidth, vnr.max_delay, vnr.max_hops, relaxed, k=1)
                self.conflict_probe_expansions += self.route_expansions - before_probe
                if not options:
                    unknown = True
                    break
                blocked.update(canonical_edge(u, w) for u, w in zip(options[0], options[0][1:])
                               if state['bw'][canonical_edge(u, w)] + EPS < edge.bandwidth)
            affected = {key for key, path in old_paths.items()
                        if any(canonical_edge(u, w) in blocked for u, w in zip(path, path[1:]))}
            local_edges = [edge for edge in closed
                           if (edge.u, edge.v) in affected or (edge.u, edge.v) not in old_paths]
            quota = budget // 3
            if (not unknown and affected and len(local_edges) < len(closed)
                    and len(local_edges) + 1 <= quota):
                retained = {key: path for key, path in old_paths.items() if key not in affected}
                local_state = self.sn.clone_state(relaxed)
                demands = {(edge.u, edge.v): edge.bandwidth for edge in closed}
                for key, path in retained.items():
                    if not self.reserve_path(local_state, path, demands[key]):
                        raise AssertionError('A retained route does not fit request-start bandwidth')
                self.conflict_repair_attempts += 1
                visited_before = self.route_search_nodes
                try:
                    self.route_budget = quota
                    repaired = self.route_link_set(vnr, mapping, local_state,
                                                  k=self.k_paths, edge_subset=local_edges)
                finally:
                    self.route_budget = budget
                spent = self.route_search_nodes - visited_before
                self.conflict_local_states += spent
                if spent > quota:
                    raise AssertionError('Local repair exceeded its route-state quota')
                if repaired is not None:
                    state['cpu'], state['bw'] = local_state['cpu'], local_state['bw']
                    self.conflict_repair_successes += 1
                    self.conflict_repair_links += len(affected)
                    return {**retained, **repaired}
                self.conflict_repair_fallbacks += 1
                budget -= spent
        state['bw'] = dict(self.sn.bandwidth_residual)
        configured_budget = self.route_budget
        before_fallback = self.route_search_nodes
        try:
            self.route_budget = budget
            return self.route_link_set(vnr, mapping, state, k=self.k_paths, edge_subset=closed)
        finally:
            if self.conflict_repair:
                self.conflict_fallback_states += self.route_search_nodes - before_fallback
            self.route_budget = configured_budget

    def _backtrack(self,vnr,order,index,mapping,state,paths):
        if self.last_search_nodes>=self.search_budget:
            self._mark_search_exhausted()
            return None
        self.last_search_nodes+=1
        self.search_nodes+=1
        if index==len(order):
            return dict(mapping),self.sn.clone_state(state),dict(paths)
        vnode=order[index]
        score_state=self.sn.clone_state(state)
        # Prior routes may be repaired; don't prune on their tentative BW use.
        score_state['bw']=dict(self.sn.bandwidth_residual)
        context=self._score_context(vnr,vnode,mapping,score_state)
        context['defer_packing'] = self.selective_packing
        candidates=[]
        used=set(mapping.values())
        for node in sorted(self.sn.cpu_residual):
            if node in used or state['cpu'][node]+EPS<vnr.node_cpu[vnode]:
                continue
            score=self._node_score(vnr,vnode,node,mapping,score_state,context)
            if math.isfinite(score):
                candidates.append((score,node))
        candidates.sort(key=lambda pair:(-pair[0],pair[1]))
        on_demand = (getattr(self, 'on_demand_packing', False) and self.selective_packing
                     and self.cut_pruning and self.exact_packing)
        if self.selective_packing and self.cut_pruning and self.exact_packing and not on_demand:
            feasible_candidates = []
            for candidate in candidates:
                if self._first_hop_feasible(vnr, vnode, candidate[1], mapping, score_state):
                    feasible_candidates.append(candidate)
                    # One extra candidate preserves the truncation diagnostic;
                    # lower-ranked nodes cannot change the explored shortlist.
                    if len(feasible_candidates) > self.candidate_limit:
                        break
            candidates = feasible_candidates
        self.last_candidate_truncated |= len(candidates)>self.candidate_limit
        explored = 0
        for _,node in (candidates if on_demand else candidates[:self.candidate_limit]):
            if on_demand:
                if not self._first_hop_feasible(vnr, vnode, node, mapping, score_state):
                    continue
                if explored >= self.candidate_limit:
                    self.last_candidate_truncated = True
                    break
                explored += 1
            if self.last_search_nodes>=self.search_budget:
                self._mark_search_exhausted()
                return None
            trial=self.sn.clone_state(state)
            if not self.reserve_cpu(trial,node,vnr.node_cpu[vnode]):
                continue
            placed={**mapping,vnode:node}
            closed=[edge for edge in vnr.edges if edge.u in placed and edge.v in placed]
            new_edges=[edge for edge in closed if (edge.u,edge.v) not in paths]
            before=self.route_budget_exhaustions
            if not self.incremental_routing:
                trial['bw']=dict(self.sn.bandwidth_residual)
                if closed:
                    self.always_joint_batches += 1
                trial_paths=self.route_link_set(vnr,placed,trial,k=self.k_paths,edge_subset=closed)
            else:
                if new_edges:
                    self.fast_route_batches += 1
                    self.fast_route_batch_links += len(new_edges)
                added=self.route_link_set(vnr,placed,trial,k=1,edge_subset=new_edges)
                if added is not None:
                    if new_edges:
                        self.fast_route_successes+=1
                    trial_paths={**paths,**added}
                elif self.joint_repair:
                    self.joint_route_repairs+=1
                    trial_paths=self._repair_routes(vnr,placed,trial,paths,closed,new_edges)
                    if trial_paths is not None:
                        self.repair_successes+=1
                else:
                    trial_paths=None
            self.last_routing_budget_exhausted |= self.route_budget_exhaustions>before
            if trial_paths is None:
                continue
            result=self._backtrack(vnr,order,index+1,placed,trial,trial_paths)
            if result is not None:
                return result
            if self.last_search_budget_exhausted:
                return None
        return None


    def _constrained_shortest_path(
        self,
        source: int,
        target: int,
        request_bw: float,
        max_delay: float,
        max_hops: int,
        state: Dict[str, Dict],
        removed_edges: Optional[Set[Tuple[int, int]]] = None,
        removed_nodes: Optional[Set[int]] = None,
        max_expansions: int = 20000,
    ) -> Optional[List[int]]:
        """Bounded label-setting search, optionally with optimistic QoS bounds.

        Bounds use a supergraph of every tentative reservation state, ignoring
        visited/removed vertices and edges. Prefix plus lower remaining delay
        or hops exceeding its cap certifies that prefix cannot finish. This
        does not certify global infeasibility after a search budget runs out.
        """
        if (not math.isfinite(request_bw) or request_bw < 0
                or not math.isfinite(max_delay) or max_delay < -EPS
                or max_hops < 0 or source not in self.sn.neighbors
                or target not in self.sn.neighbors):
            return None
        if source == target:
            return [source]
        removed_edges = removed_edges or set()
        removed_nodes = removed_nodes or set()
        if source in removed_nodes or target in removed_nodes:
            return None

        max_expansions = min(max_expansions, self.path_expansion_budget)
        powered = self.sn.powered_nodes(state)
        direct = canonical_edge(source, target)
        # Every non-direct simple route has >=2 edges. The nonnegative
        # footprint term gives an admissible lower bound on its route cost.
        # Return the direct edge only when this proves it globally cheapest.
        if (max_expansions > 0 and max_hops >= 1 and direct in self.sn.edges
                and direct not in removed_edges and (source,target) not in removed_edges
                and state["bw"][direct] + EPS >= request_bw
                and self.sn.link_delay(source,target) <= max_delay + EPS
                and self._green_edge_cost(source,target,state,powered) <= .60*self.hop_footprint + EPS):
            self.route_expansions += 1
            return [source,target]
        bounds = None
        if self.qos_route_bounds:
            # Standalone path calls use a fresh cache so releasing background
            # allocations between calls cannot leave an invalid stale bound.
            background = (self.sn.bandwidth_residual if self._routing_request_bw is None
                          else self._routing_request_bw)
            cache = {} if self._routing_request_bw is None else self._request_profiles
            bounds = self._destination_bounds(target, request_bw, {'bw': background}, cache=cache)
            lower_hops, lower_delay = bounds
            if (lower_hops.get(source, math.inf) > max_hops
                    or lower_delay.get(source, math.inf) > max_delay + EPS):
                self.qos_bound_prunes += 1
                return None
        queue = [(0.0, 0.0, 0, source, (source,))]
        labels: Dict[int, List[Tuple[float, float, int, Tuple[int, ...]]]] = (
            defaultdict(list)
        )
        labels[source].append((0.0, 0.0, 0, (source,)))
        expansions = 0

        while queue and expansions < max_expansions:
            cost, delay, hops, node, path_tuple = heapq.heappop(queue)
            expansions += 1
            self.route_expansions += 1
            if node == target:
                return list(path_tuple)
            if hops >= max_hops:
                continue
            for nxt in sorted(self.sn.neighbors[node]):
                if nxt in removed_nodes or nxt in path_tuple:
                    continue
                directed = (node, nxt)
                undirected = canonical_edge(node, nxt)
                if directed in removed_edges or undirected in removed_edges:
                    continue
                if state["bw"][undirected] + EPS < request_bw:
                    continue
                new_delay = delay + self.sn.link_delay(node, nxt)
                new_hops = hops + 1
                if new_delay > max_delay + EPS:
                    continue
                if bounds is not None and (new_hops + lower_hops.get(nxt, math.inf) > max_hops
                        or new_delay + lower_delay.get(nxt, math.inf) > max_delay + EPS):
                    self.qos_bound_prunes += 1
                    continue
                new_cost = cost + self._green_edge_cost(node, nxt, state, powered)
                new_path = path_tuple + (nxt,)
                if self._label_dominated(
                    labels[nxt], new_cost, new_delay, new_hops
                ):
                    continue
                labels[nxt] = [
                    old for old in labels[nxt]
                    if not (
                        new_cost <= old[0] + EPS
                        and new_delay <= old[1] + EPS
                        and new_hops <= old[2]
                    )
                ]
                labels[nxt].append((new_cost, new_delay, new_hops, new_path))
                heapq.heappush(
                    queue, (new_cost, new_delay, new_hops, nxt, new_path)
                )
        if queue and expansions >= max_expansions:
            self.path_budget_exhaustions += 1
        return None

    def _link_profile(self,vnr,edge,target,state):
        key=('link_profile',edge.bandwidth,vnr.max_delay,vnr.max_hops,target)
        cached=self._request_profiles.get(key)
        if cached is not None:
            return cached
        adjacency_key = ('eligible_adjacency', edge.bandwidth, vnr.max_delay)
        shared = self._request_profiles.get(adjacency_key)
        if shared is None:
            adjacent, details = {}, {}
            for node in self.sn.neighbors:
                neighbors, values = set(), []
                for neighbor in self.sn.neighbors[node]:
                    physical = canonical_edge(node, neighbor)
                    delay = self.sn.link_delay(node, neighbor)
                    if state['bw'][physical]+EPS < edge.bandwidth or delay > vnr.max_delay+EPS:
                        continue
                    neighbors.add(neighbor)
                    headroom = max(0., state['bw'][physical]-edge.bandwidth)/self.sn.bandwidth_capacity[physical]
                    values.append((neighbor, headroom, delay))
                adjacent[node], details[node] = neighbors, values
            shared = adjacent, details
            self._request_profiles[adjacency_key] = shared
        adjacent, details = shared
        reachable=None
        if target is not None:
            # Necessary hop-feasibility check. Cumulative delay and joint
            # bandwidth remain the exact router's responsibility.
            reached={target:0}
            queue=[target]
            for node in queue:
                if reached[node]>=vnr.max_hops:
                    continue
                for neighbor in adjacent[node]:
                    if neighbor not in reached:
                        reached[neighbor]=reached[node]+1
                        queue.append(neighbor)
            reachable=set(reached)
        scores={}
        for node,neighbors in adjacent.items():
            if vnr.max_hops<1 or not neighbors or (reachable is not None and node not in reachable):
                scores[node]=-math.inf
                continue
            best=-math.inf
            for neighbor, headroom, delay in details[node]:
                proximity=0.
                if target is not None:
                    if neighbor==target:
                        proximity=1.
                    elif vnr.max_hops>=2 and target in adjacent[neighbor]:
                        if delay+self.sn.link_delay(neighbor,target)<=vnr.max_delay+EPS:
                            proximity=.5
                best=max(best,.45*headroom+.40*proximity+.15*(1-delay/max(vnr.max_delay,EPS)))
            scores[node]=best
        self._request_profiles[key]=scores
        return scores


class GRCVNE(BaseVNEAlgorithm):
    """GRC ranking with the simulator's explicitly shared QoS routing adaptation.

    Ranking: Gong et al., INFOCOM 2014, equations 11--13:
    https://www3.ntu.edu.sg/home/ygwen/Paper/GWZL-Infocom-14.pdf
    Both graphs use absolute available/requested resources and fixed CPU
    personalization. Shared bounded joint K routing adds delay/hop constraints;
    this is not an exact end-to-end reproduction of the paper's routing or
    optional profit-threshold admission policy.
    """

    name = "GRC"

    def _scores(self, vnr=None):
        nodes, cpu, adjacency = _ranking_graph_data(self.sn, vnr)
        return _resource_walk_rank(nodes, cpu, adjacency, "grc")

    def _virtual_order(self, vnr):
        ranks = self._scores(vnr)
        return sorted(vnr.nodes, key=lambda n: (-ranks[n], -vnr.node_cpu[n], n))

    def embed(self, vnr):
        mapping = self.map_nodes_by_score(
            vnr, self._scores(), order=self._virtual_order(vnr)
        )
        if mapping is None:
            return None
        state = self.sn.empty_state()
        for vnode, pnode in mapping.items():
            if not self.reserve_cpu(state, pnode, vnr.node_cpu[vnode]):
                return None
        paths = self.route_link_set(vnr, mapping, state)
        if paths is None:
            return None
        return self.commit_embedding(vnr, state, mapping, paths)


class NodeRankVNE(BaseVNEAlgorithm):
    """Cheng NodeRank ranking with the simulator's shared QoS routing adaptation.

    Cheng et al., ACM SIGCOMM CCR 41(2), 2011, equations 6--10:
    https://doi.org/10.1145/1971162.1971168
    H=CPU*sum(incident BW); global H-personalized jump probability 0.15,
    neighboring H-weighted forward probability 0.85. Both virtual/substrate
    nodes are ranked. Shared bounded joint K routing differs from RW-MaxMatch's
    original link-mapping stage; no full paper-reproduction claim is made.
    """

    name = "NodeRank"

    def _scores(self, vnr=None):
        nodes, cpu, adjacency = _ranking_graph_data(self.sn, vnr)
        return _resource_walk_rank(nodes, cpu, adjacency, "noderank")

    def _virtual_order(self, vnr):
        ranks = self._scores(vnr)
        return sorted(vnr.nodes, key=lambda n: (-ranks[n], -vnr.node_cpu[n], n))

    def embed(self, vnr):
        mapping = self.map_nodes_by_score(
            vnr, self._scores(), order=self._virtual_order(vnr)
        )
        if mapping is None:
            return None
        state = self.sn.empty_state()
        for vnode, pnode in mapping.items():
            if not self.reserve_cpu(state, pnode, vnr.node_cpu[vnode]):
                return None
        paths = self.route_link_set(vnr, mapping, state)
        if paths is None:
            return None
        return self.commit_embedding(vnr, state, mapping, paths)


class GreedyKSPVNE(BaseVNEAlgorithm):
    name = "GreedyKSP"

    def embed(self, vnr: VirtualNetworkRequest) -> Optional[Dict]:
        score = {
            node: self.sn.cpu_residual[node] / max(
                self.sn.cpu_capacity[node], EPS
            )
            for node in self.sn.cpu_residual
        }
        mapping = self.map_nodes_by_score(vnr, score)
        if mapping is None:
            return None
        state = self.sn.empty_state()
        for vnode, pnode in mapping.items():
            if not self.reserve_cpu(state, pnode, vnr.node_cpu[vnode]):
                return None
        paths = self.route_link_set(vnr, mapping, state, k=self.k_paths)
        if paths is None:
            return None
        return self.commit_embedding(vnr, state, mapping, paths)


class EnergyAwareVNE(BaseVNEAlgorithm):
    """EA-VNE: custom incremental-power packing with common QoS routing.

    This generic label has no verified source-paper identity. It is an explicit
    custom baseline, not a reproduction of Su et al. or another named EA-VNE.
    Node selection minimizes marginal watts under this simulator's power model,
    including already-powered transit nodes. Common link routing is not an
    energy optimizer; neither global energy optimality nor paper fidelity is
    claimed. Boot joules and future routing power are not node-score terms.
    """

    name = "EnergyAware"

    def embed(self, vnr):
        state = self.sn.empty_state()
        mapping = {}
        used = set()
        for vnode in self.node_order(vnr):
            demand = vnr.node_cpu[vnode]
            powered = self.sn.powered_nodes(state)
            candidates = [
                node for node in sorted(state["cpu"])
                if node not in used and state["cpu"][node] + EPS >= demand
            ]
            if not candidates:
                return None

            def placement_cost(node):
                wake_watts = 0.0 if node in powered else self.sn.p_idle
                dynamic_watts = (self.sn.p_peak - self.sn.p_idle) * (
                    demand / max(self.sn.cpu_capacity[node], EPS)
                )
                return (
                    wake_watts + dynamic_watts,
                    state["cpu"][node] - demand,
                    node,
                )

            selected = min(candidates, key=placement_cost)
            if not self.reserve_cpu(state, selected, demand):
                return None
            mapping[vnode] = selected
            used.add(selected)
        paths = self.route_link_set(vnr, mapping, state)
        if paths is None:
            return None
        return self.commit_embedding(vnr, state, mapping, paths)


class PSOVNE(BaseVNEAlgorithm):
    """Optional custom discrete PSO; not a reproduction of Cheng RW-PSO."""

    name = "PSO"

    def __init__(
        self,
        substrate: SubstrateNetwork,
        rng: Optional[random.Random] = None,
        k_paths: int = 1,
        particles: int = 12,
        iterations: int = 12,
    ):
        super().__init__(substrate, rng, k_paths, candidate_limit=substrate.num_nodes)
        self.particles = max(2, particles)
        self.iterations = max(1, iterations)

    def _repair_position(
        self, position: Sequence[int], vnr: VirtualNetworkRequest
    ) -> Optional[Dict[int, int]]:
        mapping = {}
        used = set()
        for vnode, preferred in zip(self.node_order(vnr), position):
            candidates = [preferred] + list(self.sn.cpu_residual)
            selected = next(
                (
                    p for p in candidates
                    if p not in used
                    and self.sn.cpu_residual[p] + EPS >= vnr.node_cpu[vnode]
                ),
                None,
            )
            if selected is None:
                return None
            mapping[vnode] = selected
            used.add(selected)
        return mapping

    def _evaluate(
        self, vnr: VirtualNetworkRequest, position: Sequence[int]
    ) -> Tuple[float, Optional[Dict], Optional[Dict]]:
        mapping = self._repair_position(position, vnr)
        if mapping is None:
            return math.inf, None, None
        state = self.sn.empty_state()
        for vnode, pnode in mapping.items():
            if not self.reserve_cpu(state, pnode, vnr.node_cpu[vnode]):
                return math.inf, None, None
        paths = self.route_link_set(vnr, mapping, state, k=1)
        if paths is None:
            return math.inf, None, None
        # Custom PSO minimizes the exact admission resource cost reported.
        # Evaluations operate only on private state; no commit/release side effects.
        cost = vnr.total_cpu + sum(
            edge.bandwidth*self.path_hops(paths[(edge.u,edge.v)]) for edge in vnr.edges
        )
        return cost, mapping, paths

    def embed(self, vnr: VirtualNetworkRequest) -> Optional[Dict]:
        nodes = list(self.sn.cpu_residual)
        n = len(self.node_order(vnr))
        if n > len(nodes):
            return None
        velocity = np.zeros((self.particles, n, len(nodes)), dtype=float)
        positions = []
        pbest_positions = []
        pbest_scores = []
        global_position = None
        global_score = math.inf

        for _ in range(self.particles):
            order = self.node_order(vnr)
            shuffled = nodes[:]
            self.rng.shuffle(shuffled)
            position = shuffled[:n]
            score, _, _ = self._evaluate(vnr, position)
            positions.append(position)
            pbest_positions.append(position[:])
            pbest_scores.append(score)
            if score < global_score:
                global_score = score
                global_position = position[:]

        if global_position is None or not math.isfinite(global_score):
            # A deterministic greedy seed can still recover a feasible
            # solution when random initial particles all fail.
            fallback = GreedyKSPVNE(self.sn, self.rng, k_paths=1,
                                    route_budget=self.route_budget,
                                    path_expansion_budget=self.path_expansion_budget)
            result = fallback.embed(vnr)
            for field in ("route_expansions","route_search_nodes","route_budget_exhaustions","path_budget_exhaustions"):
                setattr(self,field,getattr(self,field,0)+getattr(fallback,field,0))
            return result

        for iteration in range(self.iterations):
            inertia = 0.9 - 0.5 * iteration / max(self.iterations - 1, 1)
            for i, position in enumerate(positions):
                current = np.zeros((n, len(nodes)), dtype=float)
                for row, pnode in enumerate(position):
                    current[row, nodes.index(pnode)] = 1.0
                personal = np.zeros_like(current)
                social = np.zeros_like(current)
                for row, pnode in enumerate(pbest_positions[i]):
                    personal[row, nodes.index(pnode)] = 1.0
                for row, pnode in enumerate(global_position):
                    social[row, nodes.index(pnode)] = 1.0
                velocity[i] = (
                    inertia * velocity[i]
                    + 1.4 * self.rng.random() * (personal - current)
                    + 1.4 * self.rng.random() * (social - current)
                )
                desirability = velocity[i] + 0.05 * np.random.default_rng(
                    self.rng.randrange(2**32)
                ).random((n, len(nodes)))
                next_position = []
                used = set()
                for row in range(n):
                    ranking = np.argsort(desirability[row])[::-1]
                    chosen = next(
                        (nodes[j] for j in ranking if nodes[j] not in used),
                        None,
                    )
                    if chosen is None:
                        chosen = nodes[row % len(nodes)]
                    next_position.append(chosen)
                    used.add(chosen)
                positions[i] = next_position
                score, _, _ = self._evaluate(vnr, next_position)
                if score < pbest_scores[i]:
                    pbest_scores[i] = score
                    pbest_positions[i] = next_position[:]
                if score < global_score:
                    global_score = score
                    global_position = next_position[:]
            self.history.append(global_score)

        mapping = self._repair_position(global_position, vnr)
        if mapping is None:
            return None
        state = self.sn.empty_state()
        for vnode, pnode in mapping.items():
            if not self.reserve_cpu(state, pnode, vnr.node_cpu[vnode]):
                return None
        paths = self.route_link_set(vnr, mapping, state, k=1)
        if paths is None:
            return None
        return self.commit_embedding(vnr, state, mapping, paths)


def _ranking_graph_data(substrate, vnr=None):
    """Return deterministic CPU/BW graph data for substrate or virtual ranking."""
    if vnr is None:
        cpu = dict(substrate.cpu_residual)
        bandwidth = dict(substrate.bandwidth_residual)
    else:
        cpu = dict(vnr.node_cpu)
        bandwidth = {}
        for edge in vnr.edges:
            key = canonical_edge(edge.u, edge.v)
            bandwidth[key] = bandwidth.get(key, 0.0) + float(edge.bandwidth)
    nodes = sorted(cpu)
    adjacency = {node: [] for node in nodes}
    for (u, v), value in sorted(bandwidth.items()):
        if u == v:
            continue
        weight = max(0.0, float(value))
        adjacency[u].append((v, weight))
        adjacency[v].append((u, weight))
    for node in nodes:
        adjacency[node].sort()
    return nodes, cpu, adjacency


def _normalize_rank_resources(nodes, weights, fallback=None):
    """Probability vector; zero-resource graphs use fallback then uniform mass."""
    if not nodes:
        return {}
    nonnegative = {n: max(0.0, float(weights.get(n, 0.0))) for n in nodes}
    total = sum(nonnegative.values())
    if total > EPS:
        return {n: nonnegative[n] / total for n in nodes}
    if fallback is not None:
        return _normalize_rank_resources(nodes, fallback)
    return {n: 1.0 / len(nodes) for n in nodes}


def _resource_walk_rank(nodes, cpu, adjacency, kind, damping=0.85,
                        tolerance=1e-12, max_iterations=2000):
    """Canonical resource walks plus an explicit dangling/zero-resource rule.

    GRC: fixed CPU personalization; transitions proportional to outgoing BW.
    NodeRank: H=CPU*incident BW personalization; transitions proportional to
    destination H over the source's neighbors. Dangling rows redistribute to
    personalization. If every H is zero, CPU then uniform fallback is used.
    """
    if kind not in ("grc", "noderank"):
        raise ValueError("Unknown resource-ranking method")
    if not 0.0 < damping < 1.0:
        raise ValueError("Ranking damping must be in (0, 1)")
    if not nodes:
        return {}
    resource = {
        n: max(0.0, float(cpu[n])) * sum(w for _, w in adjacency[n])
        for n in nodes
    }
    personal = _normalize_rank_resources(
        nodes, cpu if kind == "grc" else resource, fallback=cpu
    )
    transition = {}
    for node in nodes:
        weights = [
            (nxt, bw if kind == "grc" else resource[nxt])
            for nxt, bw in adjacency[node]
        ]
        total = sum(weight for _, weight in weights)
        transition[node] = (
            [(nxt, weight / total) for nxt, weight in weights if weight > 0.0]
            if total > EPS else []
        )
    rank = dict(personal)
    for _ in range(max_iterations):
        updated = {n: (1.0 - damping) * personal[n] for n in nodes}
        dangling_mass = 0.0
        for node in nodes:
            mass = damping * rank[node]
            if not transition[node]:
                dangling_mass += mass
            else:
                for nxt, probability in transition[node]:
                    updated[nxt] += mass * probability
        if dangling_mass:
            for node in nodes:
                updated[node] += dangling_mass * personal[node]
        difference = max(abs(updated[n] - rank[n]) for n in nodes)
        rank = updated
        if difference <= tolerance:
            return _normalize_rank_resources(nodes, rank)
    raise RuntimeError("Resource ranking did not converge within its iteration limit")


class ProposedGreedyVNE(LegacyAdaptiveVNE):
    """Ablation: identical adaptive score and router, one placement candidate."""

    name = "ProposedGreedy"

    def __init__(
        self, substrate: SubstrateNetwork, rng: Optional[random.Random] = None,
        k_paths: int = 3, search_budget: int = 24,
    ):
        super().__init__(
            substrate, rng=rng, k_paths=k_paths, candidate_limit=1,
            search_budget=search_budget,
        )


class GRCRankedSearchVNE(LegacyAdaptiveVNE):
    """Ablation: GRC node ranks with current green routing/search and budgets."""
    name = "GRCRankedSearch"
    def embed(self, vnr):
        ranker = GRCVNE(self.sn)
        self._control_scores = ranker._scores()
        self._control_order = ranker._virtual_order(vnr)
        return super().embed(vnr)
    def node_order(self, vnr):
        return list(self._control_order)
    def _node_score(self, vnr, vnode, pnode, mapping, state=None, context=None):
        # Retain the proposal's necessary feasibility filters. Only ranking
        # and virtual-node order change, not search resources or route cost.
        if not math.isfinite(LegacyAdaptiveVNE._node_score(
                self,vnr,vnode,pnode,mapping,state,context)):
            return -math.inf
        return self._control_scores[pnode]


class NodeRankSearchVNE(GRCRankedSearchVNE):
    """Ablation: NodeRank ranks with current green routing/search and budgets."""
    name = "NodeRankSearch"
    def embed(self, vnr):
        ranker = NodeRankVNE(self.sn)
        self._control_scores = ranker._scores()
        self._control_order = ranker._virtual_order(vnr)
        return LegacyAdaptiveVNE.embed(self, vnr)


class GRCScoreOnlyVNE(GRCRankedSearchVNE):
    """Change substrate rank only; keep proposed virtual-node order."""
    name = "GRCScoreOnly"
    def embed(self, vnr):
        self._control_scores = GRCVNE(self.sn)._scores()
        return LegacyAdaptiveVNE.embed(self, vnr)
    def node_order(self, vnr):
        return BaseVNEAlgorithm.node_order(self, vnr)


class NodeRankScoreOnlyVNE(NodeRankSearchVNE):
    """Change substrate rank only; keep proposed virtual-node order."""
    name = "NodeRankScoreOnly"
    def embed(self, vnr):
        self._control_scores = NodeRankVNE(self.sn)._scores()
        return LegacyAdaptiveVNE.embed(self, vnr)
    def node_order(self, vnr):
        return BaseVNEAlgorithm.node_order(self, vnr)


def algorithm_parameters(algorithm):
    """Record actual constructor settings, not inferred paper identities."""
    fields = ('k_paths', 'candidate_limit', 'route_budget', 'path_expansion_budget',
              'search_budget', 'energy_weight', 'boot_amortization_seconds',
              'exact_packing', 'cut_pruning', 'packing_degree_limit', 'adaptive_energy',
              'incremental_routing', 'joint_repair', 'selective_packing', 'lazy_paths',
              'hop_footprint', 'conflict_repair', 'qos_route_bounds', 'particles', 'iterations',
              'compact_weight', 'fast_profiles', 'hop_routing', 'fast_link_batches', 'on_demand_packing',
              'repair_link_limit', 'joint_qos_checks', 'domain_ordering',
              'green_two_hop', 'greedy_first', 'batch_scores', 'reference_source_sha256',
              'ranking_method', 'shortest_method', 'rank_tolerance', 'rank_max_iterations',
              'max_visit', 'max_depth', 'p_i', 'p_c', 'p_s', 'pso_scheduler')
    return {field: getattr(algorithm, field) for field in fields if hasattr(algorithm, field)}


def algorithm_factory(name, substrate, seed, include_pso=False):
    rng = random.Random(seed)
    if name in REFERENCE_ALGORITHMS:
        from .reference_baselines import REFERENCE_CLASSES
        return REFERENCE_CLASSES[name](substrate, rng=rng)
    if name == 'ProposedAdaptive':
        from .green import GreenAdaptiveVNE
        return GreenAdaptiveVNE(substrate, rng=rng)
    compact_switches = {'CompactNoRepair': {'joint_repair': False},
                        'FullJointRepair': {'repair_link_limit': 0},
                        'NoCompactPlacement': {'compact_weight': 0.},
                        'GreenCostRouting': {'hop_routing': False}}
    if name in compact_switches:
        from .efficient import EfficientAdaptiveVNE
        algorithm = EfficientAdaptiveVNE(substrate, rng=rng,
                                        **compact_switches[name])
        algorithm.name = name
        return algorithm
    registry = {"LegacyAdaptive": LegacyAdaptiveVNE, "GRC": GRCVNE,
                "NodeRank": NodeRankVNE, "GreedyKSP": GreedyKSPVNE,
                "EnergyAware": EnergyAwareVNE, "ProposedGreedy": ProposedGreedyVNE,
                "GRCRankedSearch": GRCRankedSearchVNE, "NodeRankSearch": NodeRankSearchVNE,
                "GRCScoreOnly": GRCScoreOnlyVNE, "NodeRankScoreOnly": NodeRankScoreOnlyVNE}
    switches = {'NoExactPacking': {'exact_packing': False},
                'NoCutPruning': {'cut_pruning': False, 'exact_packing': False},
                'FixedEnergyWeight': {'adaptive_energy': False},
                'AlwaysJointRouting': {'incremental_routing': False},
                'NoJointRepair': {'joint_repair': False},
                'FullHopFootprint': {'hop_footprint': 1.0},
                'EagerPacking': {'selective_packing': False},
                'EagerPathGeneration': {'lazy_paths': False},
                'ConflictRepair': {'conflict_repair': True},
                'QoSBoundRouting': {'qos_route_bounds': True}}
    if name in switches:
        algorithm = LegacyAdaptiveVNE(substrate, rng=rng, **switches[name])
        algorithm.name = name
        return algorithm
    if name == "GreedyCSP":
        algorithm = GreedyKSPVNE(substrate, rng=rng, k_paths=1)
        algorithm.name = name
        return algorithm
    if name == "PSO" and include_pso:
        return PSOVNE(substrate, rng=rng)
    if name not in registry:
        raise ValueError("Unknown or disabled algorithm: " + name)
    algorithm = registry[name](substrate, rng=rng)
    algorithm.name = name
    return algorithm


def _algorithm_names(include_pso=False, include_ablations=False, include_reference_baselines=False):
    names = list(DEFAULT_ALGORITHMS) + ([OPTIONAL_PSO] if include_pso else [])
    if include_ablations:
        names += ["ProposedGreedy", "GRCRankedSearch", "NodeRankSearch", "GreedyCSP",
                  "GRCScoreOnly", "NodeRankScoreOnly", "NoExactPacking", "NoCutPruning",
                  "FixedEnergyWeight", "AlwaysJointRouting", "NoJointRepair",
                  "FullHopFootprint", "EagerPacking", "EagerPathGeneration", "ConflictRepair", "QoSBoundRouting",
                  "LegacyAdaptive", "CompactNoRepair", "FullJointRepair",
                  "NoCompactPlacement", "GreenCostRouting"]
    if include_reference_baselines:
        names += list(REFERENCE_ALGORITHMS)
    return names


