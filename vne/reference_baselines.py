"""Ports of the pinned local Virne policies with an explicit hard-QoS adapter.

Derived from GeminiLight/Virne (Copyright 2023 GeminiLight), Apache-2.0.
Original files and license: third_party/virne/source.zip and third_party/virne/LICENSE.
These are reference-code comparisons, not claims of complete original-paper fidelity.
No proposal placement, constrained-path search or joint repair is used here.
"""
from collections import deque
from dataclasses import dataclass
from itertools import islice
import math

import networkx as nx
import numpy as np

from .algorithms import BaseVNEAlgorithm
from .models import EPS, VirtualEdge, canonical_edge


REFERENCE_SOURCE_SHA256 = '46686e3ff015da3a6ed4e440aece936e29a8e96516d0d99202bbccfddc12e86f'


def resource_graph(substrate, request=None):
    """Convert CPU/BW attributes without changing topology, demands or resources."""
    result = nx.Graph()
    cpu = substrate.cpu_residual if request is None else request.node_cpu
    result.add_nodes_from((node, {'cpu': float(value)}) for node, value in cpu.items())
    edges = ([(u, v, value) for (u, v), value in substrate.bandwidth_residual.items()]
             if request is None else [(e.u, e.v, e.bandwidth) for e in request.edges])
    result.add_edges_from((u, v, {'bw': float(bandwidth)}) for u, v, bandwidth in edges)
    return result


def reference_rank(network, method):
    """Virne resource equations, L2 stopping norms and stable insertion-order ties.

    Nonpositive/dangling resources have an explicit CPU/uniform fallback; the
    upstream GRC divides by zero on these inputs. Positive nondegenerate inputs
    are differentially checked against the unmodified source ranker classes.
    """
    nodes = list(network.nodes)
    cpu = np.array([network.nodes[node]['cpu'] for node in nodes], dtype=float)
    bw = nx.to_numpy_array(network, nodelist=nodes, weight='bw')
    if method == 'ffd':
        rank = cpu
    elif method == 'order':
        rank = np.ones(len(nodes)) / max(len(nodes), 1)
    else:
        h = cpu * bw.sum(axis=0)
        personal = cpu if method == 'grc' else h
        if personal.sum() <= EPS:
            personal = cpu if cpu.sum() > EPS else np.ones(len(nodes))
        personal = personal / personal.sum()
        weights = bw if method == 'grc' else (nx.to_numpy_array(network, nodelist=nodes) > 0) * h[None, :]
        sums = weights.sum(axis=1)
        transition = np.divide(weights, sums[:, None], out=np.zeros_like(weights), where=sums[:, None] > 0)
        transition[sums <= 0] = personal
        if method == 'rw' and h.sum() > EPS:
            # Preserve the upstream 1e-9 denominator on ordinary inputs.
            personal = h / (h.sum() + 1e-9)
        rank = personal.copy()
        tolerance = 1e-5 if method == 'grc' else 1e-4
        for _ in range(10000):
            updated = ((.15 * personal + .85 * rank @ transition) if method == 'grc'
                       else rank @ (.15 * np.tile(personal, (len(nodes), 1)) + .85 * transition))
            delta = np.linalg.norm(updated - rank)
            rank = updated
            if delta < tolerance:
                break
        else:
            raise RuntimeError('Reference rank iteration failed to converge')
    return dict(sorted(zip(nodes, map(float, rank)), key=lambda item: item[1], reverse=True))


class ReferenceVNE(BaseVNEAlgorithm):
    """Reference controller behavior, atomic commit and unchanged common hard QoS."""
    ranking_method = 'ffd'
    shortest_method = 'k_shortest'

    def __init__(self, substrate, rng=None, k_paths=10):
        super().__init__(substrate, rng, k_paths, candidate_limit=substrate.num_nodes)
        # The reference controller has no proposal label/route expansion quota.
        self.route_budget = self.path_expansion_budget = None
        self.reference_source_sha256 = REFERENCE_SOURCE_SHA256
        self.rank_tolerance = 1e-5 if self.ranking_method == 'grc' else 1e-4
        self.rank_max_iterations = 10000
        self.reference_deployments = self.reference_path_candidates = self.reference_pso_updates = 0

    def _path_candidates(self, network, source, target, bandwidth, state, method=None):
        method = method or self.shortest_method
        if method == 'bfs_shortest':
            # Same bandwidth-feasible BFS choice as the reference controller.
            queue, seen = deque([(source, [source])]), {source}
            while queue:
                node, path = queue.popleft()
                for neighbor in network.neighbors(node):
                    if state['bw'][canonical_edge(node, neighbor)] + EPS < bandwidth:
                        continue
                    if neighbor == target:
                        return [path + [neighbor]]
                    if neighbor not in seen:
                        seen.add(neighbor)
                        queue.append((neighbor, path + [neighbor]))
            # Fix the upstream unbound shortest_path on disconnected residual BW.
            return []
        try:
            # Upstream eagerly enumerates K unweighted paths on the full graph,
            # then tests resources. Do not substitute the proposal's CSP search.
            return list(islice(nx.shortest_simple_paths(network, source, target, weight=None), self.k_paths))
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            return []

    def _route_one(self, request, edge, mapping, state, network, method=None):
        source, target = mapping[edge.u], mapping[edge.v]
        paths = self._path_candidates(network, source, target, edge.bandwidth, state, method)
        self.reference_path_candidates += len(paths)
        self.route_search_nodes += 1
        self.route_expansions += sum(max(0, len(path) - 1) for path in paths)
        for path in paths:
            # These two gates are the common-scenario QoS extension.
            if len(path) - 1 > request.max_hops or self.path_delay(path) > request.max_delay + EPS:
                continue
            links = [canonical_edge(u, v) for u, v in zip(path, path[1:])]
            if all(state['bw'][link] + EPS >= edge.bandwidth for link in links):
                for link in links:
                    state['bw'][link] -= edge.bandwidth
                return path
        return None

    def _deploy(self, request, mapping, network):
        self.reference_deployments += 1
        state = self.sn.empty_state()
        if set(mapping) != set(request.nodes) or len(set(mapping.values())) != len(mapping):
            return None
        for vnode, pnode in mapping.items():
            if pnode not in state['cpu'] or not self.reserve_cpu(state, pnode, request.node_cpu[vnode]):
                return None
        paths = {}
        # Native Graph.edges iteration order, not descending demand/joint routing.
        by_edge = {canonical_edge(e.u, e.v): e for e in request.edges}
        for u, v in resource_graph(self.sn, request).edges:
            edge = by_edge[canonical_edge(u, v)]
            path = self._route_one(request, VirtualEdge(u, v, edge.bandwidth), mapping, state, network)
            if path is None:
                return None
            paths[(edge.u, edge.v)] = path if edge.u == u else path[::-1]
        cost = request.total_cpu + sum(edge.bandwidth * (len(paths[(edge.u, edge.v)]) - 1)
                                       for edge in request.edges)
        return cost / max(request.total_cpu + request.total_bandwidth, EPS), state, dict(mapping), paths

    def embed(self, request):
        network = resource_graph(self.sn)
        physical_order = list(reference_rank(network, self.ranking_method))
        virtual_order = list(reference_rank(resource_graph(self.sn, request), self.ranking_method))
        mapping, remaining = {}, physical_order.copy()
        for vnode in virtual_order:
            selected = next((p for p in remaining if self.sn.cpu_residual[p] + EPS >= request.node_cpu[vnode]), None)
            if selected is None:
                return None
            mapping[vnode] = selected
            remaining.remove(selected)
        result = self._deploy(request, mapping, network)
        return None if result is None else self.commit_embedding(request, result[1], result[2], result[3])


class VirneGRCVNE(ReferenceVNE):
    name = 'VirneGRC'
    ranking_method = 'grc'


class VirneRWVNE(ReferenceVNE):
    name = 'VirneRWMaxMatch'
    ranking_method = 'rw'


class VirneFFDVNE(ReferenceVNE):
    name = 'VirneFFD'


class VirneRWBFSVNE(ReferenceVNE):
    name = 'VirneRWBFS'
    ranking_method = 'rw'
    shortest_method = 'bfs_shortest'

    def __init__(self, substrate, rng=None):
        super().__init__(substrate, rng)
        self.max_visit, self.max_depth = 50, 5

    def embed(self, request):
        network, virtual = resource_graph(self.sn), resource_graph(self.sn, request)
        vrank, prank = reference_rank(virtual, 'rw'), reference_rank(network, 'rw')
        if not vrank or not prank:
            return None
        levels = nx.single_source_shortest_path_length(virtual, next(iter(vrank)))
        order = sorted(levels, key=lambda node: (levels[node], -vrank[node]))
        if len(order) != len(request.nodes):
            return None
        start = next(iter(prank))
        queue, visited = deque([(start, 0)]), {start}
        state, mapping, paths = self.sn.empty_state(), {}, {}
        self.reference_deployments += 1
        while queue:
            pnode, depth = queue.popleft()
            if depth > self.max_depth:
                break
            vnode = order[len(mapping)]
            candidate = {'cpu': dict(state['cpu']), 'bw': dict(state['bw'])}
            if pnode not in mapping.values() and self.reserve_cpu(candidate, pnode, request.node_cpu[vnode]):
                trial_mapping, trial_paths = dict(mapping), dict(paths)
                trial_mapping[vnode] = pnode
                success = True
                by_edge = {canonical_edge(e.u, e.v): e for e in request.edges}
                for other in virtual.neighbors(vnode):
                    if other not in mapping:
                        continue
                    edge = by_edge[canonical_edge(vnode, other)]
                    incident = VirtualEdge(vnode, other, edge.bandwidth)
                    path = self._route_one(request, incident, trial_mapping, candidate, network)
                    if path is None:
                        success = False
                        break
                    trial_paths[(edge.u, edge.v)] = path if edge.u == vnode else path[::-1]
                if success:
                    state, mapping, paths = candidate, trial_mapping, trial_paths
                    if len(mapping) == len(order):
                        return self.commit_embedding(request, state, mapping, paths)
            if depth == self.max_depth:
                continue
            neighbors = list(network.neighbors(pnode))
            # Preserve the upstream unusual per-depth truncation condition.
            if len(neighbors) > self.max_visit:
                neighbors = neighbors[:int(self.max_visit ** (1 / self.max_depth))]
            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))
        return None


@dataclass
class _Particle:
    position: dict
    velocity: list
    best_position: dict
    best: object = None


class VirnePSOVNE(ReferenceVNE):
    """Virne equality-bit discrete PSO with parent-visible serial evolution.

    The original mp.Process loop discards child updates. Correct that execution
    defect, retaining the source's probability weights, initialization, objective,
    particles and iterations. No legacy categorical repair or greedy fallback.
    """
    name = 'VirnePSO'
    ranking_method = 'order'

    def __init__(self, substrate, rng=None):
        super().__init__(substrate, rng)
        self.particles, self.iterations = 8, 12
        self.p_i, self.p_c, self.p_s = .1, .2, .7
        self.pso_scheduler = 'serial parent-visible updates; fixed global snapshot per iteration'
        self.np_rng = np.random.RandomState(self.rng.randrange(2**32))

    def _choose(self, vnode, position, candidates):
        available = list(set(candidates[vnode]).difference(set(position.values())))
        return self.rng.choices(available, weights=[1 / len(available)] * len(available), k=1)[0] if available else -1

    def _evolve(self, particle, global_position, candidates):
        nodes = list(particle.position)
        particle.velocity = [int(self.np_rng.choice(
            [particle.velocity[i], int(particle.best_position[node] == particle.position[node]),
             int(global_position[node] == particle.position[node])], p=[self.p_i, self.p_c, self.p_s]))
            for i, node in enumerate(nodes)]
        for index, vnode in enumerate(nodes):
            if particle.velocity[index] == 0:
                chosen = self._choose(vnode, particle.position, candidates)
                if chosen != -1:
                    particle.position[vnode] = chosen
        self.reference_pso_updates += 1

    def embed(self, request):
        network = resource_graph(self.sn)
        nodes = list(request.nodes)
        candidates = {v: [p for p in network if self.sn.cpu_residual[p] + EPS >= request.node_cpu[v]] for v in nodes}
        # Upstream's computed link-domain mask is discarded; its effective
        # candidates are CPU-only. Preserve that behavior rather than guess it.
        population, best = [], None
        # Native initialize constructs every Particle (and its velocity) before
        # drawing any initial node slots. Preserve that RNG consumption order.
        velocities = [[self.rng.randint(0, 1) for _ in nodes] for _ in range(self.particles)]
        for velocity in velocities:
            position = dict.fromkeys(nodes, -1)
            for vnode in nodes:
                position[vnode] = self._choose(vnode, position, candidates)
            result = self._deploy(request, position, network)
            particle = _Particle(position, velocity, dict(position), result)
            population.append(particle)
            if result is not None and (best is None or result[0] < best[0]):
                best = result
        leader = min(population, key=lambda p: math.inf if p.best is None else p.best[0])
        self.history = [math.inf if best is None else best[0]]
        for _ in range(self.iterations):
            global_position = dict(leader.best_position)
            for particle in population:
                self._evolve(particle, global_position, candidates)
                result = self._deploy(request, particle.position, network)
                if result is not None and (particle.best is None or result[0] < particle.best[0]):
                    particle.best, particle.best_position = result, dict(particle.position)
                if result is not None and (best is None or result[0] < best[0]):
                    best = result
            for particle in population:
                if particle.best is not None and (leader.best is None or particle.best[0] < leader.best[0]):
                    leader = particle
            self.history.append(math.inf if best is None else best[0])
        return None if best is None else self.commit_embedding(request, best[1], best[2], best[3])


REFERENCE_CLASSES = {cls.name: cls for cls in
                     (VirneGRCVNE, VirneRWVNE, VirneRWBFSVNE, VirneFFDVNE, VirnePSOVNE)}
