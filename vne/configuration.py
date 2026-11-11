"""Validated scenario settings for sensitivity experiments.

Algorithm policies and resource-demand ranges are fixed in the maintained code
and covered by its source fingerprint. Scenario changes are recorded explicitly.
"""
from dataclasses import asdict, dataclass
import math

from .models import VirtualNetworkGenerator


@dataclass(frozen=True)
class Scenario:
    link_prob: float = 0.35
    vnr_link_prob: float = 0.4
    lifetime_mean: float = 500.0
    max_delay: float = 25.0
    max_hops: int = 8
    p_idle: float = 150.0
    p_peak: float = 350.0
    p_link: float = 5.0
    boot_energy_joules: float = 50.0

    def __post_init__(self):
        values = asdict(self)
        if not all(math.isfinite(value) for value in values.values()):
            raise ValueError("Scenario settings must be finite")
        if not 0 <= self.link_prob <= 1 or not 0 <= self.vnr_link_prob <= 1:
            raise ValueError("Link probabilities must be in [0,1]")
        if self.lifetime_mean <= 0 or self.max_delay < 0:
            raise ValueError("Lifetime must be positive and delay nonnegative")
        if not isinstance(self.max_hops, int) or self.max_hops < 1:
            raise ValueError("max_hops must be a positive integer")
        if not 0 <= self.p_idle <= self.p_peak or self.p_link < 0 or self.boot_energy_joules < 0:
            raise ValueError("Invalid scenario power settings")

    def to_dict(self):
        return asdict(self)

    def substrate_kwargs(self):
        return {name: getattr(self, name) for name in
                ("link_prob", "p_idle", "p_peak", "p_link", "boot_energy_joules")}

    def generator(self):
        return VirtualNetworkGenerator(link_prob=self.vnr_link_prob,
                                       lifetime_mean=self.lifetime_mean,
                                       max_delay=self.max_delay, max_hops=self.max_hops)
