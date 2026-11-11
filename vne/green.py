"""Bounded green search with cached domains and a necessary host matching.

Joint hop/delay bounds tighten optimistic first-hop domains. They certify only
necessary local conditions. Fail-first ordering and power-aware equal-hop
preferences remain heuristics; they do not guarantee global VNE optimality.
Host matching is a relaxation; faster work does not imply lower total energy.
"""
import math

import numpy as np

from .efficient import EfficientAdaptiveVNE
from .models import EPS, canonical_edge
from .pruning import first_hop_packing_possible


class GreenAdaptiveVNE(EfficientAdaptiveVNE):
    name = 'ProposedAdaptive'

    def __init__(self, substrate, rng=None, *, joint_qos_checks=True,
                 domain_ordering=True, green_two_hop=True,
                 greedy_first=True, batch_scores=True, **kwargs):
        super().__init__(substrate, rng, **kwargs)
        self.joint_qos_checks = bool(joint_qos_checks)
        self.domain_ordering = bool(domain_ordering)
        self.green_two_hop = bool(green_two_hop)
        self.greedy_first = bool(greedy_first)
        self.batch_scores = bool(batch_scores)
        self.qos_bound_layers = self.qos_bound_transitions = 0
        self.host_matching_rejections = 0
        self._green_bw = None
        self._batch_powered = None
        self._host_capacity = np.array([substrate.cpu_capacity[n] for n in self._nodes])
        # Directed arcs already follow sorted host/port order. These indices
        # remove repeated neighbor sorting and physical-edge lookups.
        degree = np.bincount(self._arc_u, minlength=len(self._nodes))
        self._port_arcs = np.split(np.arange(len(self._arcs)), np.cumsum(degree)[:-1])

    def embed(self, vnr):
        demands = sorted(vnr.node_cpu.values(), reverse=True)
        capacities = sorted(self.sn.cpu_residual.values(), reverse=True)
        # An injective CPU-only matching certificate. This screens fragmented
        # capacity without running any route search and cannot reject a valid
        # injective embedding. It uses current resources, not future arrivals.
        cpu_possible = (len(demands) <= len(capacities)
                        and all(demand <= capacity + EPS for demand, capacity in zip(demands, capacities)))
        if not cpu_possible or not self._local_matching_possible(vnr):
            self.last_search_nodes = 0
            self.last_search_budget_exhausted = self.last_candidate_truncated = False
            self.last_routing_budget_exhausted = False
            self.last_failure_reason = 'injective_cpu_capacity' if not cpu_possible else 'local_host_matching'
            self.host_matching_rejections += 1
            self._request_profiles.clear()
            return None
        self._green_bw = self._edge_residual({'bw': self.sn.bandwidth_residual})
        try:
            return super().embed(vnr)
        finally:
            self._green_bw = None
            self._request_profiles.clear()

    def _local_matching_possible(self, vnr):
        """Necessary injective matching over CPU and optimistic incident cuts.

        Failure proves that even the relaxed per-host domains cannot support
        distinct hosts. Success says nothing about joint routing feasibility.
        A small augmenting-path matching avoids wasted bounded search on these
        impossible arrivals; it never changes a feasible placement's score.
        """
        residual = self._edge_residual({'bw': self.sn.bandwidth_residual})[self._arc_edge]
        eligible = self._arc_delay <= vnr.max_delay + EPS
        if vnr.max_hops < 1:
            eligible[:] = False
        residual = np.where(eligible, residual, 0.)
        n = len(self._nodes)
        totals = np.bincount(self._arc_u, weights=residual, minlength=n)
        degree = np.bincount(self._arc_u, weights=eligible, minlength=n)
        cpu = np.fromiter((self.sn.cpu_residual[node] for node in self._nodes), dtype=float)
        domains, threshold_counts = {}, {}
        for vnode in vnr.nodes:
            demands = [e.bandwidth for e in vnr.edges if vnode in (e.u, e.v) and e.bandwidth > EPS]
            allowed = cpu + EPS >= vnr.node_cpu[vnode]
            if self.cut_pruning:
                allowed &= totals + EPS * degree >= sum(demands)
                for weight in set(demands):
                    if weight not in threshold_counts:
                        threshold_counts[weight] = np.bincount(self._arc_u,
                            weights=np.where(eligible, np.floor((residual + EPS) / weight), 0.), minlength=n)
                    allowed &= threshold_counts[weight] >= sum(d >= weight for d in demands)
            domains[vnode] = np.flatnonzero(allowed).tolist()
        assigned = {}

        def augment(vnode, visited):
            for node in domains[vnode]:
                if node in visited:
                    continue
                visited.add(node)
                if node not in assigned or augment(assigned[node], visited):
                    assigned[node] = vnode
                    return True
            return False

        return all(augment(vnode, set()) for vnode in sorted(domains, key=lambda v: len(domains[v])))

    def _green_cache(self):
        # Standalone diagnostic calls receive fresh caches. During embedding,
        # all pruning uses the fixed request-start BW: tentative routes may
        # later be repaired and must never shrink these optimistic domains.
        return self._request_profiles if self._green_bw is not None else {}

    def _joint_delay_layers(self, target, bandwidth, hops, state, cache):
        key = ('green_delay_layers', target, bandwidth, hops)
        if key in cache:
            return cache[key]
        graph_key = ('green_arcs', bandwidth)
        arcs = cache.get(graph_key)
        if arcs is None:
            residual = self._edge_residual(state) if self._green_bw is None else self._green_bw
            allowed = residual[self._arc_edge] + EPS >= bandwidth
            arcs = self._arc_u[allowed], self._arc_v[allowed], self._arc_delay[allowed]
            cache[graph_key] = arcs
        source, destination, delay = arcs
        distance = np.full(len(self._nodes), np.inf)
        distance[self._index[target]] = 0.
        layers = [distance]
        # At-most-h-hop minimum delay. This computes joint QoS feasibility,
        # unlike independently minimizing hops and delay on different paths.
        for _ in range(min(hops, len(self._nodes) - 1)):
            following = distance.copy()
            np.minimum.at(following, source, distance[destination] + delay)
            self.qos_bound_layers += 1
            self.qos_bound_transitions += len(source)
            layers.append(following)
            if np.array_equal(following, distance):
                break
            distance = following
        self.qos_bound_builds += 1
        cache[key] = layers
        return layers

    def _port_domain(self, vnr, bandwidth, target, state, cache):
        key = ('green_ports', bandwidth, target, vnr.max_hops, vnr.max_delay, self.joint_qos_checks)
        if key in cache:
            return cache[key]
        residual = self._edge_residual(state) if self._green_bw is None else self._green_bw
        eligible = ((residual[self._arc_edge] + EPS >= bandwidth)
                    & (self._arc_delay <= vnr.max_delay + EPS))
        if vnr.max_hops < 1:
            eligible[:] = False
        elif target is not None:
            if self.joint_qos_checks:
                layers = self._joint_delay_layers(target, bandwidth, vnr.max_hops, state, cache)
                remaining = layers[min(vnr.max_hops - 1, len(layers) - 1)]
                eligible &= self._arc_delay + remaining[self._arc_v] <= vnr.max_delay + EPS
            else:
                hops, delays = self._destination_bounds(target, bandwidth, state, cache)
                h = np.array([hops.get(n, math.inf) for n in self._nodes])
                d = np.array([delays.get(n, math.inf) for n in self._nodes])
                eligible &= 1 + h[self._arc_v] <= vnr.max_hops
                eligible &= self._arc_delay + d[self._arc_v] <= vnr.max_delay + EPS
        cache[key] = eligible
        return eligible

    def _first_hop_feasible(self, vnr, vnode, pnode, mapping, state):
        incident = [(edge, edge.v if edge.u == vnode else edge.u)
                    for edge in vnr.edges if vnode in (edge.u, edge.v) and edge.bandwidth > EPS]
        if len(incident) > self.packing_degree_limit:
            self.packing_bypasses += 1
            return True
        cache = self._green_cache()
        key = ('green_packing', vnode, pnode, tuple((other, mapping.get(other)) for _, other in incident))
        if key in cache:
            return cache[key]
        ports = self._port_arcs[self._index[pnode]]
        residual = self._edge_residual(state) if self._green_bw is None else self._green_bw
        capacities = residual[self._arc_edge[ports]].tolist()
        domains = [np.flatnonzero(self._port_domain(vnr, edge.bandwidth,
                        mapping.get(other), state, cache)[ports]).tolist()
                   for edge, other in incident]
        self.packing_checks += 1
        result = first_hop_packing_possible([edge.bandwidth for edge, _ in incident],
                                            capacities, domains, self.packing_degree_limit)
        self.packing_rejections += int(result is False)
        cache[key] = result is not False
        return cache[key]

    def _link_profile(self, vnr, edge, target, state):
        cache = self._green_cache()
        key = ('green_profile', edge.bandwidth, vnr.max_delay, vnr.max_hops, target, self.joint_qos_checks)
        if key in cache:
            return cache[key]
        profile = super()._link_profile(vnr, edge, target, state)
        if not self.joint_qos_checks or target is None:
            return profile
        layers = self._joint_delay_layers(target, edge.bandwidth, vnr.max_hops,
                                          state, cache)
        feasible = layers[-1] <= vnr.max_delay + EPS
        # Each returned profile is request-local, so this does not alter any
        # other algorithm or persist after arrivals/releases change the state.
        result = {node: profile[node] if feasible[i] else -math.inf
                  for i, node in enumerate(self._nodes)}
        cache[key] = result
        return result

    def _score_context(self, vnr, vnode, mapping, state, cache=None):
        # Backtracking calls this twice for its chosen variable: once for the
        # domain count and once for scoring. Both use the request-start BW.
        # CPU reservations and mapped endpoints are part of the key.
        if self._green_bw is None:
            return super()._score_context(vnr, vnode, mapping, state, cache)
        key = ('green_context', vnode, self.joint_qos_checks, tuple(sorted(mapping.items())),
               tuple(state['cpu'][node] for node in self._nodes))
        cached = self._request_profiles.get(key)
        if cached is None:
            cached = super()._score_context(vnr, vnode, mapping, state, cache)
            self._request_profiles[key] = cached
        return cached

    def _profile_values(self, profile):
        key = ('green_values', id(profile))
        values = self._request_profiles.get(key)
        if values is None:
            values = np.fromiter((profile[node] for node in self._nodes), dtype=float)
            self._request_profiles[key] = values
        return values

    def _host_domain(self, vnr, vnode, mapping, state, context):
        cached = context.get('green_host_domain')
        if cached is not None:
            return cached
        cpu = np.fromiter((state['cpu'][node] for node in self._nodes), dtype=float)
        used = set(mapping.values())
        possible = np.array([node not in used and node in context['allowed']
                             for node in self._nodes])
        possible &= cpu + EPS >= vnr.node_cpu[vnode]
        for _, profile in context['incident']:
            possible &= np.isfinite(self._profile_values(profile))
        context['green_host_domain'] = possible, cpu
        return possible, cpu

    def _host_scores(self, vnr, vnode, mapping, state, context):
        """The scalar placement formula, evaluated once for all physical hosts."""
        possible, cpu = self._host_domain(vnr, vnode, mapping, state, context)
        demand = vnr.node_cpu[vnode]
        wake = np.array([0. if node in context['powered'] else
                         self.sn.p_idle + self.sn.boot_energy_joules / self.boot_amortization_seconds
                         for node in self._nodes])
        marginal = (wake + (self.sn.p_peak - self.sn.p_idle) * demand / self._host_capacity
                    ) / max(self.sn.p_peak, EPS)
        quality, total = np.zeros(len(self._nodes)), 0.
        for edge, profile in context['incident']:
            weight = max(edge.bandwidth, EPS)
            values = self._profile_values(profile)
            quality += weight * np.where(np.isfinite(values), values, 0.)
            total += weight
        if total:
            quality /= total
        weight = (self.energy_weight * (1 - .45 * context['pressure'])
                  if self.adaptive_energy else self.energy_weight)
        resources = (context['cpu_weight'] * (cpu - demand) / self._host_capacity
                     + context['bw_weight'] * quality)
        scores = (1 - weight) * resources - weight * marginal
        connections = context['compact_connections']
        if connections and self.compact_weight:
            footprint = sum(w * np.where(np.isfinite(hops), np.maximum(0., hops - 1), 0.)
                            for w, hops in connections)
            scores -= self.compact_weight * footprint / sum(w for w, _ in connections)
        scores[~possible] = -math.inf
        return scores

    def _node_score(self, vnr, vnode, pnode, mapping, state=None, context=None):
        if (not self.batch_scores or self._green_bw is None or context is None
                or not context.get('defer_packing', False)):
            return super()._node_score(vnr, vnode, pnode, mapping, state, context)
        scores = context.get('green_host_scores')
        if scores is None:
            use_batch = context.get('green_use_batch')
            if use_batch is None:
                use_batch = np.count_nonzero(self._host_domain(vnr, vnode, mapping, state, context)[0]) >= 16
                context['green_use_batch'] = use_batch
            if not use_batch:
                return super()._node_score(vnr, vnode, pnode, mapping, state, context)
            scores = self._host_scores(vnr, vnode, mapping, state, context)
            context['green_host_scores'] = scores
        return float(scores[self._index[pnode]])

    def _backtrack(self, vnr, order, index, mapping, state, paths):
        if self.greedy_first and index == 0 and not mapping:
            # One original-order construction, then fail-first recovery.
            # Both passes share counters, caches and the SAME total quota.
            candidates, ordering = self.candidate_limit, self.domain_ordering
            try:
                self.candidate_limit, self.domain_ordering = 1, False
                result = super()._backtrack(vnr, order, index, mapping, state, paths)
            finally:
                self.candidate_limit, self.domain_ordering = candidates, ordering
            if result is not None or self.last_search_budget_exhausted:
                return result
        if (self.domain_ordering and index < len(order)
                and self.last_search_nodes < self.search_budget):
            relaxed = self.sn.clone_state(state)
            relaxed['bw'] = dict(self.sn.bandwidth_residual)
            choices = []
            for vnode in order[index:]:
                count = self._domain_count(vnr, vnode, mapping, relaxed)
                incident = [edge for edge in vnr.edges if vnode in (edge.u, edge.v)]
                closed = sum((edge.v if edge.u == vnode else edge.u) in mapping for edge in incident)
                choices.append((count, -closed, -sum(e.bandwidth for e in incident),
                                -vnr.node_cpu[vnode], vnode))
            chosen = min(choices)[-1]
            order = order[:index] + [chosen] + [v for v in order[index:] if v != chosen]
        return super()._backtrack(vnr, order, index, mapping, state, paths)

    def _domain_count(self, vnr, vnode, mapping, state):
        # Ordering needs only domain membership, never headroom/energy scores
        # or pairwise proximity matrices for all remaining virtual nodes.
        if not self.joint_qos_checks or self._green_bw is None:
            context = self._score_context(vnr, vnode, mapping, state)
            return int(np.count_nonzero(self._host_domain(vnr, vnode, mapping, state, context)[0]))
        cache = self._request_profiles
        incident = [e for e in vnr.edges if vnode in (e.u, e.v)]
        key = ('node_cut', vnode)
        allowed = cache.get(key)
        if allowed is None:
            demands = [e.bandwidth for e in incident if e.bandwidth > EPS]
            residual = self._green_bw[self._arc_edge]
            totals = np.bincount(self._arc_u, weights=residual, minlength=len(self._nodes))
            degree = np.bincount(self._arc_u, minlength=len(self._nodes))
            possible = np.ones(len(self._nodes), dtype=bool)
            if self.cut_pruning:
                possible &= totals + EPS * degree >= sum(demands)
                for weight in set(demands):
                    threshold_key = ('compact_threshold', weight)
                    counts = cache.get(threshold_key)
                    if counts is None:
                        counts = np.bincount(self._arc_u,
                            weights=np.floor_divide(residual + EPS, weight), minlength=len(self._nodes))
                        cache[threshold_key] = counts
                    possible &= counts >= sum(d >= weight for d in demands)
                self.cut_checks += len(self._nodes)
                self.cut_rejections += len(self._nodes) - int(possible.sum())
            allowed = {node for i, node in enumerate(self._nodes) if possible[i]}
            cache[key] = allowed
        used = set(mapping.values())
        possible = np.array([node not in used and node in allowed
                             and state['cpu'][node] + EPS >= vnr.node_cpu[vnode]
                             for node in self._nodes])
        for edge in incident:
            port_key = ('green_has_port', edge.bandwidth, vnr.max_delay, vnr.max_hops)
            ports = cache.get(port_key)
            if ports is None:
                eligible = ((self._green_bw[self._arc_edge] + EPS >= edge.bandwidth)
                            & (self._arc_delay <= vnr.max_delay + EPS))
                ports = np.bincount(self._arc_u[eligible], minlength=len(self._nodes)) > 0
                if vnr.max_hops < 1:
                    ports[:] = False
                cache[port_key] = ports
            possible &= ports
            target = mapping.get(edge.v if edge.u == vnode else edge.u)
            if target is not None:
                layers = self._joint_delay_layers(target, edge.bandwidth, vnr.max_hops, state, cache)
                possible &= layers[-1] <= vnr.max_delay + EPS
        return int(possible.sum())

    def route_link_set(self, vnr, mapping, state, k=None, edge_subset=None):
        k_value = self.k_paths if k is None else max(1, int(k))
        if self._green_bw is None or not self.fast_link_batches or k_value != 1:
            return super().route_link_set(vnr, mapping, state, k, edge_subset)
        # Internal K=1 batches only receive states created by reserve_cpu,
        # reserve_path and cloning. Each reservation checks its own resources;
        # the final commit independently validates the complete embedding and
        # every residual. Public calls retain the inherited whole-state check.
        edges = sorted(vnr.edges if edge_subset is None else edge_subset,
                       key=lambda edge: (-edge.bandwidth, edge.u, edge.v))
        self.last_route_failure_reason = None
        if not edges:
            return {}
        trial, chosen = self.sn.clone_state(state), {}
        previous_powered = self._batch_powered
        self._batch_powered = self.sn.powered_nodes(trial)
        try:
            for index, edge in enumerate(edges):
                if index >= self.route_budget:
                    break
                self.route_search_nodes += 1
                before = self.path_budget_exhaustions
                path = self._constrained_shortest_path(mapping[edge.u], mapping[edge.v],
                    edge.bandwidth, vnr.max_delay, vnr.max_hops, trial)
                if path is None or not self.reserve_path(trial, path, edge.bandwidth):
                    self.last_route_failure_reason = ('path_expansion_budget_exhausted'
                        if self.path_budget_exhaustions > before else 'no_route_within_k_paths')
                    return None
                chosen[(edge.u, edge.v)] = path
                if edge.bandwidth > EPS:
                    self._batch_powered.update(path)
                else:
                    for u, w in zip(path, path[1:]):
                        link = canonical_edge(u, w)
                        if trial['bw'][link] < self.sn.bandwidth_capacity[link] - EPS:
                            self._batch_powered.update((u, w))
            if len(chosen) >= self.route_budget or len(chosen) != len(edges):
                self.route_budget_exhaustions += 1
                self.last_route_failure_reason = 'route_budget_exhausted'
                return None
            self.route_search_nodes += 1  # Original terminal-state quota.
            state['cpu'], state['bw'] = trial['cpu'], trial['bw']
            return chosen
        finally:
            self._batch_powered = previous_powered

    def _two_hop_context(self, state):
        if not self.green_two_hop:
            return None
        return self._batch_powered if self._batch_powered is not None else self.sn.powered_nodes(state)

    def _two_hop_key(self, source, middle, target, bandwidth, delay, state, context):
        if not self.green_two_hop:
            return super()._two_hop_key(source, middle, target, bandwidth, delay, state, context)
        a, b = canonical_edge(source, middle), canonical_edge(middle, target)
        wake = 0. if middle in context else self.sn.p_idle + self.sn.boot_energy_joules / self.boot_amortization_seconds
        watts = wake + self.sn.p_link * sum(state['bw'][e] >= self.sn.bandwidth_capacity[e] - EPS
                                          for e in (a, b))
        return watts, delay, middle
