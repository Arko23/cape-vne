"""Read-only inventory and optional import check of an external Virne checkout.

This does not train or benchmark RL policies, modify the checkout, or establish
paper fidelity. A module's presence is not proof that its implementation works.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tomllib


def inspect_checkout(root):
    project = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf-8'))['project']
    files = sorted((root/'virne').rglob('*.py')) + sorted((root/'settings').rglob('*.yaml'))
    files += [root/'pyproject.toml']
    digest, inventory, registrations, syntax_errors = hashlib.sha256(), {}, [], []
    for path in files:
        relative = path.relative_to(root).as_posix()
        data = path.read_bytes()
        inventory[relative] = hashlib.sha256(data).hexdigest()
        digest.update(relative.encode() + b'\0' + data + b'\0')
        if path.suffix != '.py':
            continue
        try:
            tree = ast.parse(data, filename=relative)
        except (SyntaxError, UnicodeError) as error:
            syntax_errors.append(dict(file=relative, error=str(error)))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for decorator in node.decorator_list:
                    if isinstance(decorator, ast.Call) and ast.unparse(decorator.func).endswith('SolverRegistry.register'):
                        registrations.append(dict(file=relative, line=node.lineno, class_name=node.name,
                                                  registration=ast.unparse(decorator)))
    modules = {}
    for name in ('torch', 'torch_geometric', 'torch_sparse', 'torch_scatter',
                 'torch_cluster', 'torch_spline_conv', 'pyg_lib', 'gym', 'hydra', 'ortools'):
        spec = importlib.util.find_spec(name)
        modules[name] = dict(found=spec is not None, origin=spec.origin if spec else None)
    checkpoints = [str(path.relative_to(root)) for pattern in ('*.pt', '*.pth', '*.ckpt')
                   for path in root.rglob(pattern) if '.git' not in path.parts]
    return dict(root=str(root), project_name=project['name'], version=project.get('version'),
        python=platform.python_version(), platform=platform.platform(),
        upstream_revision='unverified local snapshot; no Git metadata' if not (root/'.git').exists()
                          else 'Git metadata present; revision not resolved by this audit',
        source_and_settings_sha256=digest.hexdigest(), files=inventory,
        dependencies=project.get('dependencies'), extras=project.get('optional-dependencies'),
        registered_solver_classes=registrations, syntax_errors=syntax_errors,
        installed_module_locations=modules, checkpoint_files=checkpoints)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--probe-import', action='store_true')
    args = parser.parse_args()
    root, out = args.root.resolve(), args.output_dir.resolve()
    if not (root/'virne').is_dir() or not (root/'pyproject.toml').is_file():
        parser.error('Root must contain the Virne package and pyproject.toml')
    if out == root or root in out.parents:
        parser.error('Save the audit outside the read-only reference checkout')
    out.mkdir(parents=True, exist_ok=True)
    report = inspect_checkout(root)
    if args.probe_import:
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', WANDB_MODE='disabled', WANDB_DISABLED='true')
        code = 'import sys; sys.path.insert(0, sys.argv[1]); import virne; print(virne.__file__)'
        try:
            result = subprocess.run([sys.executable, '-B', '-c', code, str(root)], cwd=out,
                env=environment, capture_output=True, text=True, timeout=45)
            log = result.stdout + '\n' + result.stderr
            report['import_probe'] = dict(returncode=result.returncode, success=result.returncode == 0,
                note='Import only; no solver trained or evaluated')
        except subprocess.TimeoutExpired as error:
            log = str(error)
            report['import_probe'] = dict(success=False, timed_out=True)
        (out/'import_probe.log').write_text(log, encoding='utf-8')
    (out/'audit.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    probe = report.get('import_probe', {})
    text = f"""# Local Virne audit

Read-only checkout: `{root}`. Version `{report['version']}`.
Source/settings fingerprint: `{report['source_and_settings_sha256']}`.
Upstream provenance: {report['upstream_revision']}.

Found {len(report['registered_solver_classes'])} decorated solver classes,
{len(report['syntax_errors'])} Python syntax errors and {len(report['checkpoint_files'])} checkpoint files.
Syntax parsing does not verify solver behavior. Module presence does not verify native extensions.
Import probe succeeded: `{probe.get('success', 'not requested')}`.
See [audit.json](audit.json) and [import log](import_probe.log) for exact evidence.

The local PyG extras name Linux CPython 3.10 wheels, while this audit interpreter
is Python {platform.python_version()} on {platform.system()}. Do not install those wheel URLs
into this interpreter or substitute stub modules for functional RL dependencies.
Use a separate compatible environment, pinned author revision and real trained
checkpoints before reporting FlagVNE, CONAL or HRL-ACRA results.

| Component | Alignment required before comparison |
|---|---|
| Physical graph | Local default YAML uses 100-node Waxman rather than our 50-node connected random graph. Align topology/capacities or label distinct scenarios. |
| Requests | Local defaults use 2–10 nodes, CPU 0–20 and BW 0–50; our defaults use 3–7, CPU 17–42 and BW 37–72. Use identical traces for paired comparisons. |
| Arrival rate | Local lambda is requests per second; ours is requests per 100 seconds. Convert units explicitly. |
| QoS | Default local resource YAML does not impose our delay/hop caps. Align constraints and verify every accepted embedding independently. |
| Energy | Use the same host/transit, link and boot accounting; Virne paper scores do not establish our energy outcome. |
| Learned policies | Record both training/inference cost, device and search/decoder width. An untrained policy or partial HRL hierarchy is not a valid author benchmark. |

Virne is a benchmark framework, not one competing algorithm. Its publication is
verified on the [ICLR 2026 page](https://iclr.cc/virtual/2026/poster/10007855).
The current simulator's GRC/NodeRank variants remain ranking adaptations, and
its EnergyAware/PSO policies remain custom baselines. This audit does not add
any tested published RL baseline.
"""
    (out/'REPORT.md').write_text(text, encoding='utf-8')
    print(json.dumps(dict(solvers=len(report['registered_solver_classes']),
                         checkpoints=len(report['checkpoint_files']), import_probe=probe), indent=2))


if __name__ == '__main__':
    main()
