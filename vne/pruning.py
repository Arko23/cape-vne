"""Necessary local feasibility conditions for unsplittable first-hop traffic.

A feasible simple embedding induces a packing of each positive incident demand
onto exactly one first-hop port. Failure of this exact local test is therefore
safe to prune. Success proves only local feasibility, not a full embedding.
"""
from typing import Optional, Sequence
from .models import EPS


def first_hop_packing_possible(
    demands: Sequence[float],
    capacities: Sequence[float],
    eligible_ports: Optional[Sequence[Sequence[int]]] = None,
    max_demands: int = 10,
) -> Optional[bool]:
    """Subset DP; None means degree exceeds the limit, never infeasibility.

    Only exhaustive completion can return False. No greedy packing or bounded
    routing failure is used as an infeasibility certificate. Eligibility must be
    a conservative superset of the ports a feasible embedding could use.
    """
    count = len(demands)
    if count > max_demands:
        return None
    if not count:
        return True
    if not capacities:
        return False
    if eligible_ports is None:
        eligible_ports = [range(len(capacities)) for _ in demands]
    if len(eligible_ports) != count:
        raise ValueError('One eligible-port domain is required per demand')
    # A successful constructive assignment is already a packing witness. A
    # greedy failure is NEVER an infeasibility certificate: exact DP follows.
    domains = [set(ports) for ports in eligible_ports]
    residual = list(capacities)
    witnessed = True
    for i in sorted(range(count), key=lambda i: (len(domains[i]), -demands[i], i)):
        choices = [p for p in sorted(domains[i])
                   if 0 <= p < len(residual) and residual[p] + EPS >= demands[i]]
        if not choices:
            witnessed = False
            break
        port = min(choices, key=lambda p: (residual[p] - demands[i], p))
        residual[port] -= demands[i]
    if witnessed:
        return True
    full = (1 << count) - 1
    weights = [0.0] * (full + 1)
    for mask in range(1, full + 1):
        bit = mask & -mask
        weights[mask] = weights[mask ^ bit] + demands[bit.bit_length() - 1]
    reachable = {0}
    for port, capacity in enumerate(capacities):
        allowed = sum(1 << i for i in range(count) if port in domains[i])
        next_reachable = set(reachable)
        for assigned in reachable:
            available = allowed & (full ^ assigned)
            subset = available
            while subset:
                if weights[subset] <= capacity + EPS:
                    combined = assigned | subset
                    if combined == full:
                        return True
                    next_reachable.add(combined)
                subset = (subset - 1) & available
        reachable = next_reachable
    return full in reachable
