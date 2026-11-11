"""Self-contained regression fixtures; no archived simulator is imported."""
import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import vne


def regression_fixture(name):
    return json.loads((Path(__file__).parent / 'fixtures' / name).read_text(encoding='utf-8'))


def run_case(case, names, include_reference_baselines=False):
    scenario = vne.Scenario(**case['scenario'])
    with patch.object(vne.experiments, '_algorithm_names', return_value=list(names)):
        records = vne.run_simulation(case['load'], case['duration'], case['nodes'],
                                     case['seed'], include_pso=True, include_ablations=True,
                                     scenario=scenario, include_reference_baselines=include_reference_baselines)
    return vne._flatten_results(records).set_index('Algorithm').sort_index()


def expected_outcomes(item):
    return pd.DataFrame(item['outcomes']).set_index('Algorithm').sort_index()
