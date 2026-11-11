"""Compact placement and fast, exact single-link minimum-hop routing.

The hop-layered delay DP is established constrained-path machinery, not a new
optimal VNE solver. Placement, finite candidate search and joint repair remain
heuristics. Only the single-link minimum-hop claim is exact when its budget
finishes. Accounting, constraints and the five primary baselines are unchanged.
"""
from __future__ import annotations

import math
import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

from .algorithms import LegacyAdaptiveVNE
from .models import EPS, canonical_edge


class EfficientAdaptiveVNE(LegacyAdaptiveVNE):
    name = 'ProposedAdaptive'

    def __init__(self, substrate, rng=None, *, compact_weight=.30,
                 fast_profiles=True, hop_routing=True, fast_link_batches=True,
                 on_demand_packing=True, repair_link_limit=4, **kwargs):
        kwargs.setdefault('qos_route_bounds', True)
        kwargs.setdefault('energy_weight', .60)
        super().__init__(substrate, rng=rng, **kwargs)
        if not math.isfinite(compact_weight) or compact_weight < 0:
            raise ValueError('compact_weight must be finite and nonnegative')
        self.compact_weight = float(compact_weight)
        self.fast_profiles = bool(fast_profiles)
        self.hop_routing = bool(hop_routing)
        self.fast_link_batches = bool(fast_link_batches)
        self.on_demand_packing = bool(on_demand_packing)
        if not isinstance(repair_link_limit, int) or repair_link_limit < 0:
            raise ValueError('repair_link_limit must be a nonnegative integer; zero means no link-count cap')
        self.repair_link_limit = repair_link_limit
        self.repair_size_skips = 0
        self.dp_transitions = 0
        self.path_cache_hits = self.two_hop_successes = 0
        self._nodes = tuple(sorted(substrate.cpu_capacity))
        self._index = {node: i for i, node in enumerate(self._nodes)}
        directed = [(u, v, canonical_edge(u, v), substrate.link_delay(u, v))
                    for u in self._nodes for v in sorted(substrate.neighbors[u])]
        if any(not math.isfinite(delay) or delay < 0 for _, _, _, delay in directed):
            raise ValueError('Minimum-hop delay DP requires finite nonnegative physical delays')
        self._arcs = tuple(directed)
        self._edges = tuple(substrate.bandwidth_capacity)
        edge_index = {edge: i for i, edge in enumerate(self._edges)}
        self._arc_edge = np.array([edge_index[e] for _, _, e, _ in directed], dtype=int)
        self._arc_u = np.array([self._index[u] for u, _, _, _ in directed], dtype=int)
        self._arc_v = np.array([self._index[v] for _, v, _, _ in directed], dtype=int)
        self._arc_delay = np.array([d for _, _, _, d in directed], dtype=float)
        self._arc_capacity = np.array([substrate.bandwidth_capacity[e]
                                       for _, _, e, _ in directed], dtype=float)
        self._delay_matrix = np.full((len(self._nodes), len(self._nodes)), np.inf)
        self._delay_matrix[self._arc_u, self._arc_v] = self._arc_delay
        self._cpu_total = sum(substrate.cpu_capacity.values())
        self._bw_total = sum(substrate.bandwidth_capacity.values())
        self._background_powered = None

    def embed(self, vnr):
        self._background_powered = self.sn.powered_nodes()
        try:
            return super().embed(vnr)
        finally:
            self._background_powered = None

    def _profile_graph(self, bandwidth, delay, state):
        key = ('compact_graph', bandwidth, delay)
        cached = self._request_profiles.get(key)
        if cached is not None:
            return cached
        residual = self._edge_residual(state)[self._arc_edge]
        eligible = (residual + EPS >= bandwidth) & (self._arc_delay <= delay + EPS)
        n = len(self._nodes)
        adjacent = np.zeros((n, n), dtype=bool)
        adjacent[self._arc_u[eligible], self._arc_v[eligible]] = True
        quality = np.full((n, n), -np.inf)
        headroom = np.maximum(0., residual - bandwidth) / self._arc_capacity
        quality[self._arc_u[eligible], self._arc_v[eligible]] = (
            .45 * headroom[eligible] + .15 * (1 - self._arc_delay[eligible] / max(delay, EPS)))
        cached = adjacent, quality
        self._request_profiles[key] = cached
        return cached

    def _edge_residual(self, state):
        # Simulator clones retain insertion order; public callers may supply a
        # reordered dictionary, which must receive the identical interpretation.
        bw = state['bw']
        if tuple(bw) == self._edges:
            return np.fromiter(bw.values(), dtype=float, count=len(self._edges))
        return np.array([bw[edge] for edge in self._edges], dtype=float)

    def _destination_bounds(self, target, bandwidth, state, cache=None):
        if self._background_powered is None or not self.fast_profiles:
            return super()._destination_bounds(target, bandwidth, state, cache)
        cache = self._request_profiles if cache is None else cache
        key = ('destination_bounds', target, bandwidth)
        if key in cache:
            return cache[key]
        graph_key = ('compact_bound_graph', bandwidth)
        matrix = cache.get(graph_key)
        if matrix is None:
            residual = self._edge_residual(state)[self._arc_edge]
            allowed = residual + EPS >= bandwidth
            # Explicit sparse construction preserves zero-delay physical edges.
            matrix = csr_matrix((self._arc_delay[allowed],
                                 (self._arc_u[allowed], self._arc_v[allowed])),
                                shape=(len(self._nodes), len(self._nodes)))
            cache[graph_key] = matrix
        self.qos_bound_builds += 1
        target_index = self._index[target]
        h = dijkstra(matrix, directed=False, indices=target_index, unweighted=True)
        d = dijkstra(matrix, directed=False, indices=target_index)
        result = ({node: float(h[i]) for i, node in enumerate(self._nodes) if np.isfinite(h[i])},
                  {node: float(d[i]) for i, node in enumerate(self._nodes) if np.isfinite(d[i])})
        cache[key] = result
        return result

    def _profile_hops(self, bandwidth, delay, target, state):
        key = ('compact_hops', bandwidth, delay, target)
        cached = self._request_profiles.get(key)
        if cached is not None:
            return cached
        adjacent, _ = self._profile_graph(bandwidth, delay, state)
        hops = np.full(len(self._nodes), np.inf)
        start = self._index[target]
        hops[start] = 0
        frontier = np.zeros(len(self._nodes), dtype=bool)
        frontier[start] = True
        depth = 0
        while frontier.any():
            following = adjacent[frontier].any(axis=0) & ~np.isfinite(hops)
            depth += 1
            hops[following] = depth
            frontier = following
        self._request_profiles[key] = hops
        return hops

    def _link_profile(self, vnr, edge, target, state):
        if not self.fast_profiles:
            return super()._link_profile(vnr, edge, target, state)
        key = ('compact_profile', edge.bandwidth, vnr.max_delay, vnr.max_hops, target)
        cached = self._request_profiles.get(key)
        if cached is not None:
            return cached
        adjacent, base = self._profile_graph(edge.bandwidth, vnr.max_delay, state)
        values = base
        if target is not None:
            t = self._index[target]
            proximity = np.zeros_like(base)
            if vnr.max_hops >= 2:
                two_hop = (adjacent[:, t][None, :] &
                           (self._delay_matrix + self._delay_matrix[:, t][None, :]
                            <= vnr.max_delay + EPS))
                proximity[two_hop] = .5
            proximity[:, t] = 1.
            values = base + .40 * proximity
        scores = values.max(axis=1)
        if vnr.max_hops < 1:
            scores[:] = -np.inf
        if target is not None:
            distances = self._profile_hops(edge.bandwidth, vnr.max_delay, target, state)
            scores[distances > vnr.max_hops] = -np.inf
        cached = {node: float(scores[i]) for i, node in enumerate(self._nodes)}
        self._request_profiles[key] = cached
        return cached

    def _score_context(self, vnr, vnode, mapping, state, cache=None):
        if not self.fast_profiles or self._background_powered is None:
            context = super()._score_context(vnr, vnode, mapping, state, cache)
        else:
            cpu_pressure = 1 - sum(state['cpu'].values()) / max(self._cpu_total, EPS)
            bw_pressure = 1 - sum(state['bw'].values()) / max(self._bw_total, EPS)
            cpu_weight, bw_weight = 1 + 2 * cpu_pressure, 1 + 2 * bw_pressure
            incident = []
            for edge in vnr.edges:
                other = edge.v if edge.u == vnode else edge.u if edge.v == vnode else None
                if other is not None:
                    incident.append((edge, self._link_profile(vnr, edge, mapping.get(other), state)))
            key = ('node_cut', vnode)
            allowed = self._request_profiles.get(key)
            if allowed is None:
                demands = [e.bandwidth for e, _ in incident if e.bandwidth > EPS]
                thresholds = {w: sum(d >= w for d in demands) for w in demands}
                if not self.cut_pruning:
                    allowed = set(self._nodes)
                else:
                    support = self._request_profiles.get('compact_cut_support')
                    n = len(self._nodes)
                    if support is None:
                        residual = self._edge_residual(state)[self._arc_edge]
                        totals = np.bincount(self._arc_u, weights=residual, minlength=n)
                        degrees = np.bincount(self._arc_u, minlength=n)
                        support = residual, totals, degrees
                        self._request_profiles['compact_cut_support'] = support
                    residual, totals, degrees = support
                    possible = totals + EPS * degrees >= sum(demands)
                    for w, count in thresholds.items():
                        threshold_key = ('compact_threshold', w)
                        ports = self._request_profiles.get(threshold_key)
                        if ports is None:
                            ports = np.bincount(self._arc_u,
                                weights=np.floor_divide(residual + EPS, w), minlength=n)
                            self._request_profiles[threshold_key] = ports
                        possible &= ports >= count
                    self.cut_checks += n
                    self.cut_rejections += n - int(possible.sum())
                    allowed = {node for i, node in enumerate(self._nodes) if possible[i]}
                self._request_profiles[key] = allowed
            powered = self._background_powered | {
                n for n in self._nodes if state['cpu'][n] < self.sn.cpu_residual[n] - EPS}
            context = dict(powered=powered, incident=incident, allowed=allowed,
                           cpu_weight=cpu_weight / (cpu_weight + bw_weight),
                           bw_weight=bw_weight / (cpu_weight + bw_weight),
                           pressure=max(cpu_pressure, bw_pressure))
        # A bandwidth-weighted optimistic footprint, never an infeasibility
        # certificate. Joint reservations are deliberately relaxed here.
        connections = []
        for edge, _ in context['incident']:
            other = edge.v if edge.u == vnode else edge.u
            if other in mapping:
                connections.append((max(edge.bandwidth, EPS), self._profile_hops(
                    edge.bandwidth, vnr.max_delay, mapping[other], state)))
        context['compact_connections'] = connections
        return context

    def _node_score(self, vnr, vnode, pnode, mapping, state=None, context=None):
        score = super()._node_score(vnr, vnode, pnode, mapping, state, context)
        if context is None or not math.isfinite(score) or not self.compact_weight:
            return score
        connections = context['compact_connections']
        if connections:
            index = self._index[pnode]
            footprint = sum(w * max(0., hops[index] - 1) for w, hops in connections)
            score -= self.compact_weight * footprint / sum(w for w, _ in connections)
        return score

    def _constrained_shortest_path(self, source, target, request_bw, max_delay,
                                   max_hops, state, removed_edges=None,
                                   removed_nodes=None, max_expansions=20000):
        if not self.hop_routing:
            return super()._constrained_shortest_path(source, target, request_bw,
                max_delay, max_hops, state, removed_edges, removed_nodes, max_expansions)
        if (not math.isfinite(request_bw) or request_bw < 0
                or not math.isfinite(max_delay) or max_delay < -EPS or max_hops < 0
                or source not in self._index or target not in self._index):
            return None
        removed_edges, removed_nodes = removed_edges or set(), removed_nodes or set()
        if source in removed_nodes or target in removed_nodes:
            return None
        if source == target:
            return [source]
        budget = min(max_expansions, self.path_expansion_budget)
        if budget <= 0 or max_hops < 1:
            return None
        direct = canonical_edge(source, target)
        if (direct in self.sn.edges and direct not in removed_edges
                and (source, target) not in removed_edges
                and state['bw'][direct] + EPS >= request_bw
                and self.sn.link_delay(source, target) <= max_delay + EPS):
            self.route_expansions += 1
            return [source, target]
        if max_hops == 1:
            self.route_expansions += 1
            return None  # The only possible one-hop route was checked above.
        # An exhaustive two-hop check proves the optimum whenever it succeeds.
        # Respect the same work budget rather than giving the shortcut free work.
        neighbors = self.sn.neighbors[source]
        if max_hops >= 2 and 1 + len(neighbors) <= budget:
            best = None
            preference = self._two_hop_context(state)
            for middle in sorted(neighbors):
                if middle in removed_nodes or middle == target:
                    continue
                a, b = canonical_edge(source, middle), canonical_edge(middle, target)
                if (b not in self.sn.edges or a in removed_edges or b in removed_edges
                        or (source, middle) in removed_edges or (middle, target) in removed_edges
                        or state['bw'][a] + EPS < request_bw or state['bw'][b] + EPS < request_bw):
                    continue
                delay = self.sn.link_delay(source, middle) + self.sn.link_delay(middle, target)
                if delay <= max_delay + EPS:
                    candidate = self._two_hop_key(source, middle, target,
                        request_bw, delay, state, preference)
                    if best is None or candidate < best:
                        best = candidate
            self.route_expansions += 1 + len(neighbors)
            budget -= 1 + len(neighbors)
            if best is not None:
                self.two_hop_successes += 1
                return [source, best[-1], target]
            if max_hops == 2:
                return None  # Exhaustive one/two-hop failure, not budget failure.
        eligible = (self._edge_residual(state)[self._arc_edge] + EPS >= request_bw)
        eligible &= self._arc_delay <= max_delay + EPS
        if removed_edges or removed_nodes:
            eligible &= np.array([e not in removed_edges and (u, v) not in removed_edges
                                  and u not in removed_nodes and v not in removed_nodes
                                  for u, v, e, _ in self._arcs], dtype=bool)
        cache_key = ('compact_path', source, target, max_delay, max_hops, budget,
                     np.packbits(eligible).tobytes())
        if cache_key in self._request_profiles:
            cached = self._request_profiles[cache_key]
            self.path_cache_hits += 1
            return None if cached is False else list(cached)
        src, dst = self._arc_u[eligible], self._arc_v[eligible]
        delays = self._arc_delay[eligible]
        n = len(self._nodes)
        distance = np.full(n, np.inf)
        distance[self._index[source]] = 0.
        parents, spent = [], 0
        # Minimum delay with exactly h edges. The first feasible h is the
        # minimum feasible hop count. Nonnegative delays imply a minimum-hop
        # feasible walk has no cycle: removing it would use fewer hops.
        for _ in range(min(max_hops, n - 1)):
            active = int(np.isfinite(distance).sum())
            if spent + active > budget:
                self.path_budget_exhaustions += 1
                return None
            spent += active
            self.route_expansions += active
            candidates = distance[src] + delays
            self.dp_transitions += int(np.isfinite(candidates).sum())
            following = np.full(n, np.inf)
            np.minimum.at(following, dst, candidates)
            parent = np.full(n, n, dtype=int)
            best = np.isfinite(candidates) & (candidates == following[dst])
            np.minimum.at(parent, dst[best], src[best])
            parents.append(parent)
            end = self._index[target]
            if following[end] <= max_delay + EPS:
                path = [end]
                for previous in reversed(parents):
                    end = int(previous[end])
                    path.append(end)
                path.reverse()
                answer = [self._nodes[i] for i in path]
                self._request_profiles[cache_key] = tuple(answer)
                return answer
            following[following > max_delay + EPS] = np.inf
            if not np.isfinite(following).any():
                self._request_profiles[cache_key] = False
                return None
            distance = following
        self._request_profiles[cache_key] = False
        return None

    def _two_hop_context(self, state):
        return None

    def _two_hop_key(self, source, middle, target, bandwidth, delay, state, context):
        # Original controls retain their exact minimum-delay tie ordering.
        return delay, middle

    def path_cost(self, path, state):
        if self.hop_routing:
            # A tuple expresses the lexicographic objective exactly, without
            # assuming a universal scalar big-M for arbitrary delay caps.
            return self.path_hops(path), self.path_delay(path)
        return super().path_cost(path, state)

    def _repair_routes(self, vnr, mapping, state, old_paths, closed, new_edges):
        # A work/quality policy, not an infeasibility certificate. Large closed
        # sets return to placement recovery instead of an expensive joint retry.
        if self.repair_link_limit and len(closed) > self.repair_link_limit:
            self.repair_size_skips += 1
            return None
        return super()._repair_routes(vnr, mapping, state, old_paths, closed, new_edges)

    def route_link_set(self, vnr, mapping, state, k=None, edge_subset=None):
        k_value = self.k_paths if k is None else max(1, int(k))
        if not self.fast_link_batches or k_value != 1:
            return super().route_link_set(vnr, mapping, state, k, edge_subset)
        edges = sorted(vnr.edges if edge_subset is None else edge_subset,
                       key=lambda e: (-e.bandwidth, e.u, e.v))
        self.last_route_failure_reason = None
        if not edges:
            return {}
        if not self.sn.state_is_valid(state):
            self.last_route_failure_reason = 'invalid_private_state'
            return None
        if any(e.u not in mapping or e.v not in mapping for e in edges):
            self.last_route_failure_reason = 'unmapped_virtual_endpoint'
            return None
        if len({(e.u, e.v) for e in edges}) != len(edges):
            self.last_route_failure_reason = 'duplicate_virtual_edge'
            return None
        trial, chosen = self.sn.clone_state(state), {}
        visited = 0
        for edge in edges:
            if visited >= self.route_budget:
                self.route_budget_exhaustions += 1
                self.last_route_failure_reason = 'route_budget_exhausted'
                return None
            visited += 1
            self.route_search_nodes += 1
            before = self.path_budget_exhaustions
            path = self._constrained_shortest_path(mapping[edge.u], mapping[edge.v],
                edge.bandwidth, vnr.max_delay, vnr.max_hops, trial)
            if path is None or not self.reserve_path(trial, path, edge.bandwidth):
                self.last_route_failure_reason = ('path_expansion_budget_exhausted'
                    if self.path_budget_exhaustions > before else 'no_route_within_k_paths')
                return None
            chosen[(edge.u, edge.v)] = path
        # The terminal recursive state consumes one unit in the shared router.
        if visited >= self.route_budget:
            self.route_budget_exhaustions += 1
            self.last_route_failure_reason = 'route_budget_exhausted'
            return None
        self.route_search_nodes += 1
        state['cpu'], state['bw'] = trial['cpu'], trial['bw']
        return chosen
