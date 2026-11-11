"""Maintained simulator API. Scientific implementation scopes are documented in REFERENCES.md."""
import os
for _name in ('OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
    os.environ.setdefault(_name, '1')
from .models import EPS, SubstrateNetwork, VirtualEdge, VirtualNetworkRequest, VirtualNetworkGenerator, canonical_edge, generate_trace
from .configuration import Scenario
from .algorithms import (ALGORITHM_SCOPE, DEFAULT_ALGORITHMS, REFERENCE_ALGORITHMS, BaseVNEAlgorithm,
    LegacyAdaptiveVNE, GRCVNE, NodeRankVNE, GreedyKSPVNE, EnergyAwareVNE,
    PSOVNE, ProposedGreedyVNE, GRCRankedSearchVNE, NodeRankSearchVNE,
    GRCScoreOnlyVNE, NodeRankScoreOnlyVNE,
    algorithm_factory, algorithm_parameters, _algorithm_names, _resource_walk_rank)
from .efficient import EfficientAdaptiveVNE
from .green import GreenAdaptiveVNE, GreenAdaptiveVNE as ProposedAdaptiveVNE
from .reference_baselines import (VirneGRCVNE, VirneRWVNE, VirneRWBFSVNE, VirneFFDVNE, VirnePSOVNE)
from .experiments import (run_simulation, run_full_evaluation, run_scalability_experiment,
    smoke_test, write_summary, write_statistics, _flatten_results,
    _validate_active_state, _experiment_spec)
