"""Network, workload, power and resource-state models.

Time is seconds; physical link delay is milliseconds. Sleep/wake is idealized.
"""
from __future__ import annotations
import copy
import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple
import numpy as np

EPS = 1e-9

def canonical_edge(u: int, v: int) -> Tuple[int, int]:
    return (u, v) if u < v else (v, u)


def safe_mean(values: Sequence[float]) -> float:
    return float(np.mean(values)) if values else 0.0


@dataclass(frozen=True)
class VirtualEdge:
    u: int
    v: int
    bandwidth: float


@dataclass
class VirtualNetworkRequest:
    request_id: int
    arrival: float
    departure: float
    node_cpu: Dict[int, float]
    edges: List[VirtualEdge]
    max_delay: float = 25.0
    max_hops: int = 8
    slice_type: str = "healthcare"

    @property
    def lifetime(self) -> float:
        return max(0.0, self.departure - self.arrival)

    @property
    def nodes(self) -> List[int]:
        return list(self.node_cpu)

    @property
    def total_cpu(self) -> float:
        return float(sum(self.node_cpu.values()))

    @property
    def total_bandwidth(self) -> float:
        return float(sum(e.bandwidth for e in self.edges))


class SubstrateNetwork:
    """Undirected substrate with one residual capacity per physical link."""

    def __init__(
        self,
        num_nodes: int = 50,
        link_prob: float = 0.35,
        cpu_range: Tuple[int, int] = (70, 130),
        bw_range: Tuple[int, int] = (40, 80),
        seed: int = 42,
        p_idle: float = 150.0,
        p_peak: float = 350.0,
        p_link: float = 5.0,
        boot_energy_joules: float = 50.0,
    ):
        if not isinstance(num_nodes, int) or num_nodes < 2:
            raise ValueError("num_nodes must be at least 2")
        if not math.isfinite(link_prob) or not 0 <= link_prob <= 1:
            raise ValueError("link_prob must be in [0,1]")
        for bounds in (cpu_range, bw_range):
            if len(bounds) != 2 or bounds[0] <= 0 or bounds[1] < bounds[0]:
                raise ValueError("CPU and bandwidth ranges must be ordered and positive")
        if not all(math.isfinite(x) for x in (p_idle,p_peak,p_link,boot_energy_joules)) or not 0 <= p_idle <= p_peak or p_link < 0 or boot_energy_joules < 0:
            raise ValueError("Invalid physical power/boot parameters")
        self.num_nodes = int(num_nodes)
        self.link_prob = float(link_prob)
        self.cpu_range = tuple(cpu_range)
        self.bw_range = tuple(bw_range)
        self.p_idle = float(p_idle)
        self.p_peak = float(p_peak)
        self.p_link = float(p_link)
        self.boot_energy_joules = float(boot_energy_joules)
        self.rng = random.Random(seed)
        self.coordinates = {
            n: (self.rng.uniform(0, 100), self.rng.uniform(0, 100))
            for n in range(self.num_nodes)
        }
        self.cpu_capacity = {
            n: float(self.rng.randint(*self.cpu_range))
            for n in range(self.num_nodes)
        }
        self.cpu_residual = dict(self.cpu_capacity)
        self.edges: Dict[Tuple[int, int], Dict[str, float]] = {}
        self.neighbors: Dict[int, Set[int]] = {
            n: set() for n in range(self.num_nodes)
        }
        self._build_connected_graph()
        self.bandwidth_capacity = {
            e: float(self.edges[e]["bandwidth"]) for e in self.edges
        }
        self.bandwidth_residual = dict(self.bandwidth_capacity)

    def _distance(self, u: int, v: int) -> float:
        x1, y1 = self.coordinates[u]
        x2, y2 = self.coordinates[v]
        return math.hypot(x1 - x2, y1 - y2)

    def _add_edge(self, u: int, v: int) -> None:
        edge = canonical_edge(u, v)
        if edge in self.edges:
            return
        # Delay is in milliseconds. This scaling makes the default 25 ms
        # request constraint meaningful on the 0--100 coordinate square.
        self.edges[edge] = {
            "delay": 1.0 + self._distance(u, v) / 10.0,
            "bandwidth": float(self.rng.randint(*self.bw_range)),
        }
        self.neighbors[u].add(v)
        self.neighbors[v].add(u)

    def _build_connected_graph(self) -> None:
        # Random spanning tree guarantees connectivity. Extra links are added
        # using the configured probability; this is deliberately documented as
        # a connected Erdos-Renyi-like model, not a Waxman model.
        for node in range(1, self.num_nodes):
            parent = self.rng.randrange(node)
            self._add_edge(node, parent)
        for u in range(self.num_nodes):
            for v in range(u + 1, self.num_nodes):
                if canonical_edge(u, v) not in self.edges:
                    if self.rng.random() < self.link_prob:
                        self._add_edge(u, v)

    def clone(self) -> "SubstrateNetwork":
        return copy.deepcopy(self)

    def edge_info(self, u: int, v: int) -> Dict[str, float]:
        return self.edges[canonical_edge(u, v)]

    def link_delay(self, u: int, v: int) -> float:
        return float(self.edge_info(u, v)["delay"])

    def path_delay(self, path: Sequence[int]) -> float:
        return sum(self.link_delay(a, b) for a, b in zip(path, path[1:]))

    def path_hops(self, path: Sequence[int]) -> int:
        return max(0, len(path) - 1)

    def cpu_utilization(self) -> float:
        used = sum(self.cpu_capacity[n] - self.cpu_residual[n]
                   for n in self.cpu_capacity)
        total = sum(self.cpu_capacity.values())
        return float(used / total) if total else 0.0

    def link_utilization(self) -> float:
        used = sum(self.bandwidth_capacity[e] - self.bandwidth_residual[e]
                   for e in self.edges)
        total = sum(self.bandwidth_capacity.values())
        return float(used / total) if total else 0.0

    def active_node_count(self):
        return len(self.powered_nodes())


    def active_link_count(self) -> int:
        return sum(
            1 for e in self.bandwidth_capacity
            if self.bandwidth_residual[e] < self.bandwidth_capacity[e] - EPS
        )

    def power_watts(self):
        """Idle+linear CPU watts on powered nodes; active-link watts separately.

        A forwarding-only node incurs idle power. Boot energy is charged once
        per off-to-on physical node transition by commit_embedding. No boot
        latency, cooldown, migration, or server/switch-specific power is modeled.
        """
        node_power = sum(self.p_idle + (self.p_peak-self.p_idle) *
                         (self.cpu_capacity[n]-self.cpu_residual[n])/self.cpu_capacity[n]
                         for n in self.powered_nodes())
        return node_power + self.p_link*self.active_link_count()


    def empty_state(self) -> Dict[str, Dict]:
        return {
            "cpu": dict(self.cpu_residual),
            "bw": dict(self.bandwidth_residual),
        }

    @staticmethod
    def clone_state(state: Dict[str, Dict]) -> Dict[str, Dict]:
        return {"cpu": dict(state["cpu"]), "bw": dict(state["bw"])}

    def state_is_valid(self, state):
        if set(state) != {"cpu","bw"}:
            return False
        for field,capacities in (("cpu",self.cpu_capacity),("bw",self.bandwidth_capacity)):
            if set(state[field]) != set(capacities):
                return False
            for key,value in state[field].items():
                if not math.isfinite(value) or value < -EPS or value > capacities[key]+EPS:
                    return False
        return True


    def apply_state(self, state: Dict[str, Dict]) -> None:
        if not self.state_is_valid(state):
            raise RuntimeError("Attempted to commit an invalid substrate state")
        self.cpu_residual = dict(state["cpu"])
        self.bandwidth_residual = dict(state["bw"])

    def powered_nodes(self, state=None):
        """Powered hosts OR forwarding nodes; empty infrastructure is asleep."""
        state = self.empty_state() if state is None else state
        powered = {n for n,c in self.cpu_capacity.items() if state["cpu"][n] < c-EPS}
        for edge,capacity in self.bandwidth_capacity.items():
            if state["bw"][edge] < capacity-EPS:
                powered.update(edge)
        return powered


class VirtualNetworkGenerator:
    def __init__(
        self,
        node_count_range: Tuple[int, int] = (3, 7),
        cpu_range: Tuple[int, int] = (17, 42),
        bw_range: Tuple[int, int] = (37, 72),
        link_prob: float = 0.4,
        max_delay: float = 25.0,
        max_hops: int = 8,
        lifetime_mean: float = 500.0,
    ):
        for bounds in (node_count_range, cpu_range, bw_range):
            if (len(bounds) != 2 or any(not isinstance(value, int) for value in bounds)
                    or bounds[0] <= 0 or bounds[1] < bounds[0]):
                raise ValueError("Generator ranges must contain ordered positive integers")
        if not math.isfinite(link_prob) or not 0 <= link_prob <= 1:
            raise ValueError("link_prob must be in [0,1]")
        if not math.isfinite(max_delay) or max_delay < 0:
            raise ValueError("max_delay must be finite and nonnegative")
        if not isinstance(max_hops, int) or max_hops < 1:
            raise ValueError("max_hops must be a positive integer")
        if not math.isfinite(lifetime_mean) or lifetime_mean <= 0:
            raise ValueError("lifetime_mean must be finite and positive")
        self.node_count_range = node_count_range
        self.cpu_range = cpu_range
        self.bw_range = bw_range
        self.link_prob = link_prob
        self.max_delay = max_delay
        self.max_hops = max_hops
        self.lifetime_mean = lifetime_mean

    def _connected_edges(
        self, n: int, rng: random.Random
    ) -> List[Tuple[int, int]]:
        edges: Set[Tuple[int, int]] = set()
        for node in range(1, n):
            edges.add(canonical_edge(node, rng.randrange(node)))
        for u in range(n):
            for v in range(u + 1, n):
                if (u, v) not in edges and rng.random() < self.link_prob:
                    edges.add((u, v))
        return sorted(edges)

    def generate(
        self, request_id: int, arrival: float, rng: random.Random
    ) -> VirtualNetworkRequest:
        n = rng.randint(*self.node_count_range)
        node_cpu = {
            node: float(rng.randint(*self.cpu_range)) for node in range(n)
        }
        edges = [
            VirtualEdge(u, v, float(rng.randint(*self.bw_range)))
            for u, v in self._connected_edges(n, rng)
        ]
        lifetime = rng.expovariate(1.0 / self.lifetime_mean)
        return VirtualNetworkRequest(
            request_id=request_id,
            arrival=float(arrival),
            departure=float(arrival + lifetime),
            node_cpu=node_cpu,
            edges=edges,
            max_delay=self.max_delay,
            max_hops=self.max_hops,
        )


def generate_trace(
    lam: float,
    duration: float,
    seed: int,
    generator: Optional[VirtualNetworkGenerator] = None,
) -> List[VirtualNetworkRequest]:
    """Generate one common request trace for every algorithm."""
    if not math.isfinite(lam) or lam <= 0:
        raise ValueError("lambda must be positive")
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("duration must be finite and nonnegative")
    generator = generator or VirtualNetworkGenerator()
    rng = random.Random(seed)
    # Lambda is interpreted as requests per 100 simulation-time units.
    rate = lam / 100.0
    arrival = 0.0
    request_id = 0
    trace = []
    while True:
        arrival += rng.expovariate(rate)
        if arrival > duration:
            break
        trace.append(generator.generate(request_id, arrival, rng))
        request_id += 1
    return trace


