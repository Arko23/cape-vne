"""Strict external adjacency loading with explicitly synthetic resources/delay.

No network file is fetched or modified. Historical mapped adjacency is not a
measurement of current network capacity, latency, power, traffic or performance.
"""
import hashlib
import math
from pathlib import Path
import random

import networkx as nx

from vne.models import SubstrateNetwork, canonical_edge


def load_topology(path, simplify=False):
    path = Path(path)
    if path.suffix.lower() == '.gml':
        graph = nx.read_gml(path, label=None)
    elif path.suffix.lower() in ('.graphml', '.xml'):
        # Some local SNDlib files are downloaded HTML redirect/error pages.
        header = path.read_text(encoding='utf-8-sig')[:4096].lower()
        if '<graphml' not in header:
            raise ValueError('Not GraphML: missing graphml root; possible downloaded HTML page')
        graph = nx.read_graphml(path)
    else:
        raise ValueError('Expected a GML or GraphML file')
    if graph.is_directed():
        raise ValueError('Directed graphs cannot be silently converted to undirected substrates')
    if graph.number_of_nodes() < 2:
        raise ValueError('Topology must contain at least two nodes')
    loops = nx.number_of_selfloops(graph)
    simple = nx.Graph(graph)
    parallel = graph.number_of_edges() - simple.number_of_edges()
    if (loops or parallel) and not simplify:
        raise ValueError('Self loops/parallel links require explicit --simplify; no capacity aggregation is inferred')
    simple.remove_edges_from(list(nx.selfloop_edges(simple)))
    original_nodes = sorted(simple.nodes, key=lambda n: (type(n).__name__, str(n)))
    index = {node: i for i, node in enumerate(original_nodes)}
    edges = tuple(sorted(canonical_edge(index[u],index[w]) for u,w in simple.edges))
    metadata = dict(path=str(path.resolve()),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    nodes=len(original_nodes),edges=len(edges),components=nx.number_connected_components(simple),
                    removed_self_loops=loops,collapsed_parallel_edges=parallel,
                    labels={str(index[n]):str(n) for n in original_nodes},
                    graph_attributes={str(k):str(v) for k,v in graph.graph.items()},
                    resources='Synthetic CPU U{70..130}, BW U{40..80}; not measured file capacities',
                    delay='Synthetic coordinates U[0,100]^2; delay_ms=1+EuclideanDistance/10',
                    conversion='Retain all nodes/components; no spanning-tree edges added; parallel edges collapsed only by explicit opt-in')
    return metadata, edges


def substrate_from_topology(metadata, edges, seed, **power):
    """Build a fresh substrate per method from identical geometry/resource RNG.

    The normal constructor adds a spanning tree, so it must not be used here.
    This fills its data contract without modifying imported adjacency.
    """
    sn = SubstrateNetwork.__new__(SubstrateNetwork)
    sn.num_nodes, sn.link_prob = metadata['nodes'], 0.
    sn.cpu_range, sn.bw_range = (70,130), (40,80)
    sn.p_idle, sn.p_peak = power.get('p_idle',150.),power.get('p_peak',350.)
    sn.p_link, sn.boot_energy_joules = power.get('p_link',5.),power.get('boot_energy_joules',50.)
    sn.rng = random.Random(seed)
    sn.coordinates = {n:(sn.rng.uniform(0,100),sn.rng.uniform(0,100)) for n in range(sn.num_nodes)}
    sn.cpu_capacity = {n:float(sn.rng.randint(*sn.cpu_range)) for n in range(sn.num_nodes)}
    sn.cpu_residual = dict(sn.cpu_capacity)
    sn.edges = {}
    sn.neighbors = {n:set() for n in range(sn.num_nodes)}
    for u,w in edges:
        a,b = sn.coordinates[u],sn.coordinates[w]
        sn.edges[(u,w)] = dict(delay=1.+math.hypot(a[0]-b[0],a[1]-b[1])/10.,
                             bandwidth=float(sn.rng.randint(*sn.bw_range)))
        sn.neighbors[u].add(w)
        sn.neighbors[w].add(u)
    sn.bandwidth_capacity = {e:info['bandwidth'] for e,info in sn.edges.items()}
    sn.bandwidth_residual = dict(sn.bandwidth_capacity)
    return sn
