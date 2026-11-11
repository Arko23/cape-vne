"""Execute unchanged pinned Virne decision code using CPU/BW data adapters.

Only imports and unrelated classes are omitted. No decision-method AST is edited.
This avoids importing Virne's optional RL dependencies or altering its checkout.
The adapters expose the common simulator's CPU/BW constraints and transactions;
they are not a full Virne environment or a paper-reproduction assertion.
"""
import __future__
import abc
import ast
import copy
from collections import defaultdict, deque
import hashlib
from itertools import islice
import multiprocessing as mp
from pathlib import Path
import random
from types import SimpleNamespace
import zipfile

import networkx as nx
import numpy as np

ARCHIVE = Path(__file__).resolve().parents[1] / 'third_party/virne/source.zip'
ARCHIVE_SHA256 = '46686e3ff015da3a6ed4e440aece936e29a8e96516d0d99202bbccfddc12e86f'
if hashlib.sha256(ARCHIVE.read_bytes()).hexdigest() != ARCHIVE_SHA256:
    raise ValueError('Pinned Virne oracle archive has changed')


class Solution(dict):
    __getattr__ = dict.__getitem__

    @classmethod
    def from_v_net(cls, network):
        return cls(result=False, node_slots={}, node_slots_info={}, link_paths={}, link_paths_info={},
                   v_net_cost=0., v_net_revenue=0.,
                   v_net_constraint_offsets={'node_level': defaultdict(dict), 'link_level': defaultdict(dict),
                                             'path_level': defaultdict(dict)})

    def __deepcopy__(self, memo):
        return type(self)(copy.deepcopy(dict(self), memo))


class Registry:
    @staticmethod
    def register(**kwargs):
        return lambda cls: cls


class Solver:
    def __init__(self, controller, recorder, counter, logger, config, **kwargs):
        self.controller, self.counter, self.config = controller, counter, config
        self.reusable = False


NAMESPACE = dict(abc=abc, copy=copy, defaultdict=defaultdict, deque=deque, islice=islice,
                 mp=mp, nx=nx, np=np, random=random, Solver=Solver, SolverRegistry=Registry,
                 Solution=Solution, INFEASIBLE_FITNESS=float('inf'),
                 path_to_links=lambda path: list(zip(path, path[1:])))


def load_definitions(path, names, class_name=None):
    with zipfile.ZipFile(ARCHIVE) as archive:
        tree = ast.parse(archive.read(path), filename=path)
    body = tree.body if class_name is None else next(n for n in tree.body if isinstance(n, ast.ClassDef)
                                                    and n.name == class_name).body
    selected = [n for n in body if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name in names]
    if {n.name for n in selected} != set(names):
        raise ValueError(f'Missing native definitions in {path}')
    code = compile(ast.Module(body=selected, type_ignores=[]), path, 'exec',
                   flags=__future__.annotations.compiler_flag)
    exec(code, NAMESPACE)
    return [NAMESPACE[name] for name in names]


load_definitions('virne/solver/rank/node_rank.py',
                 ['NodeRankRegistry', 'NodeRank', 'OrderNodeRank', 'FFDNodeRank', 'GRCNodeRank',
                  'RWNodeRank', 'rank_nodes'])
load_definitions('virne/solver/heuristic/node_rank.py',
                 ['BaseNodeRankSolver', 'GRCRankSolver', 'FFDRankSolver', 'RandomWalkRankSolver'])
load_definitions('virne/solver/heuristic/bfs_trials.py', ['BfsSolver', 'RandomWalkRankBfsSolver'])
load_definitions('virne/solver/meta_heuristic/base_meta_heuristic_solver.py',
                 ['BaseMetaHeuristicSolver', 'Individual', 'FitnessRecorder'])
load_definitions('virne/solver/meta_heuristic/particle_swarm_optimization_solver.py',
                 ['Particle', 'ParticleSwarmOptimizationSolver'])


def native_method(path, cls, name):
    return load_definitions(path, [name], cls)[0]


class Network(nx.Graph):
    @property
    def num_nodes(self):
        return self.number_of_nodes()

    @property
    def num_links(self):
        return self.number_of_edges()

    @property
    def links(self):
        return self.edges

    def get_node_attrs(self, *args):
        return ['cpu']

    def get_link_attrs(self, *args):
        return [SimpleNamespace(name='bw')]

    def get_node_attrs_data(self, attrs):
        return [[self.nodes[n]['cpu'] for n in self.nodes]]

    def get_adjacency_attrs_data(self, attrs, normalized=False):
        return [ADJACENCY(SimpleNamespace(name='bw'), self, normalized)]


ADJACENCY = native_method('virne/network/attribute/link_attribute.py', 'LinkAttribute', 'get_adjacency_data')


class Checker:
    def check_link_level_constraints(self, virtual, physical, link, plink):
        return physical.edges[plink]['bw'] + 1e-9 >= virtual.edges[link]['bw'], {}

    def check_path_level_constraints(self, virtual, physical, link, path):
        return all(self.check_link_level_constraints(virtual, physical, link, e)[0]
                   for e in zip(path, path[1:])), {'link_level': {}, 'path_level': {}}


class Updater:
    def update_link_resources(self, physical, link, resources, operator='-', safe=True):
        for attr, amount in resources.items():
            physical.edges[link][attr] -= amount


class Topology:
    find_shortest_paths = native_method('virne/core/controller/topology_analyzer.py', 'TopologyAnalyzer',
                                       'find_shortest_paths')
    find_bfs_shortest_path = native_method('virne/core/controller/topology_analyzer.py', 'TopologyAnalyzer',
                                          'find_bfs_shortest_path')
    constraint_checker = Checker()


class NodeIO:
    node_mapping = native_method('virne/core/controller/node_mapper.py', 'NodeMapper', '_safely_node_mapping')

    def place(self, virtual, physical, vnode, pnode, solution, **kwargs):
        solution['v_net_constraint_offsets']['node_level'][vnode] = {}
        if pnode not in physical or pnode in solution.node_slots.values():
            return False, {}
        if physical.nodes[pnode]['cpu'] + 1e-9 < virtual.nodes[vnode]['cpu']:
            return False, {}
        physical.nodes[pnode]['cpu'] -= virtual.nodes[vnode]['cpu']
        solution.node_slots[vnode] = pnode
        return True, {}

    def record_place_constraint_violation(self, *args):
        pass  # Diagnostic fields are not used to choose the next host.


class LinkIO:
    link_mapping = native_method('virne/core/controller/link_mapper.py', 'LinkMapper', '_safely_link_mapping')
    _route = native_method('virne/core/controller/link_mapper.py', 'LinkMapper', '_safely_route')
    constraint_checker, resource_updator, topology_analyzer = Checker(), Updater(), Topology()
    step_constraint_offset_placeholder = {'link_level': {}, 'path_level': {}}
    link_resource_attrs = [SimpleNamespace(name='bw')]

    def route(self, virtual, physical, link, *args, **kwargs):
        result = self._route(virtual, physical, link, *args, **kwargs)
        solution = args[1]
        solution['v_net_constraint_offsets']['link_level'][link] = {}
        solution['v_net_constraint_offsets']['path_level'][link] = {}
        return result


class Controller:
    bfs_deploy = native_method('virne/core/controller/controller.py', 'Controller', 'bfs_deploy')
    _place_route = native_method('virne/core/controller/controller.py', 'Controller', '_safely_place_and_route')
    deploy_with_node_slots = native_method('virne/core/controller/controller.py', 'Controller',
                                           '_safely_deploy_with_node_slots')
    node_mapper, link_mapper = NodeIO(), LinkIO()

    def place_and_route(self, virtual, physical, vnode, pnode, solution, **kwargs):
        self.saved = copy.deepcopy((physical, solution))
        return self._place_route(virtual, physical, vnode, pnode, solution, **kwargs)

    def undo_place_and_route(self, virtual, physical, vnode, pnode, solution):
        previous, saved = self.saved
        for node in physical:
            physical.nodes[node].update(previous.nodes[node])
        for link in physical.edges:
            physical.edges[link].update(previous.edges[link])
        solution.clear()
        solution.update(saved)

    def _calculate_link_and_path_level_step_constraint_offset(self, *args):
        pass

    def _calculate_max_single_step_constraint_violation(self, *args):
        pass


class Counter:
    def count_solution(self, virtual, solution):
        if not solution['result']:
            return
        cpu = sum(virtual.nodes[n]['cpu'] for n in virtual)
        solution['v_net_revenue'] = cpu + sum(virtual.edges[e]['bw'] for e in virtual.edges)
        solution['v_net_cost'] = cpu + sum(virtual.edges[e]['bw'] * len(path)
                                          for e, path in solution.link_paths.items())


def networks(substrate, request):
    # A Graph(existing_graph) copy groups edge insertion by source node and can
    # change equal-length path ties. Translate the original dictionaries/lists
    # directly and independently, retaining their actual adjacency insertion.
    virtual, physical = Network(), Network()
    virtual.add_nodes_from((node, {'cpu': float(cpu)}) for node, cpu in request.node_cpu.items())
    virtual.add_edges_from((edge.u, edge.v, {'bw': float(edge.bandwidth)}) for edge in request.edges)
    physical.add_nodes_from((node, {'cpu': float(cpu)}) for node, cpu in substrate.cpu_residual.items())
    physical.add_edges_from((u, v, {'bw': float(bw)}) for (u, v), bw in substrate.bandwidth_residual.items())
    return virtual, physical


def heuristic(substrate, request, name):
    virtual, physical = networks(substrate, request)
    cls = NAMESPACE[{'VirneGRC': 'GRCRankSolver', 'VirneFFD': 'FFDRankSolver',
                     'VirneRWMaxMatch': 'RandomWalkRankSolver', 'VirneRWBFS': 'RandomWalkRankBfsSolver'}[name]]
    solver = cls(Controller(), None, Counter(), None, None)
    return solver.solve({'v_net': virtual, 'p_net': physical})


class NativeMetaRunProbe:
    """Picklable process target to exercise the original meta_run loop on Windows."""
    max_iteration = 1

    def __init__(self):
        self.child_changed = mp.get_context('spawn').Event()

    def initialize(self, *args):
        self.particles = [SimpleNamespace(position=0)]

    def evolve(self, particle):
        particle.position = 1
        self.child_changed.set()

    def update_best_individual(self, population):
        self.best_individual = SimpleNamespace(best_solution=population[0].position)
