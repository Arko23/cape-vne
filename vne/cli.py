"""Command-line entry point. Does not start experiments on import."""
import argparse
import json
import math
import time
from pathlib import Path
from .experiments import smoke_test, run_full_evaluation, run_scalability_experiment, _atomic_write_csv
from .configuration import Scenario

def save_config(output_dir, args):
    path = Path(output_dir)
    path.mkdir(parents=True,exist_ok=True)
    # Preserve invocation history; immutable experiment manifests sit beside CSVs.
    with (path / "invocations.jsonl").open("a",encoding="utf-8") as handle:
        handle.write(json.dumps({"unix_time":time.time(),"arguments":vars(args)},sort_keys=True)+"\n")


def parse_args():
    parser = argparse.ArgumentParser(description="Validated VNE simulation; one time unit = one second")
    parser.add_argument("--mode",choices=("smoke","full","scalability"),default="smoke")
    parser.add_argument("--output-dir",default="results")
    parser.add_argument("--workers",type=int,default=1)
    parser.add_argument("--duration",type=float,default=None,help="Seconds; defaults: smoke=250, full=10000, scalability=5000")
    parser.add_argument("--num-nodes",type=int,default=None,help="Defaults: smoke=20, full=50")
    parser.add_argument("--lambdas",default="2,4,6,8,10,12")
    parser.add_argument("--sizes",default="25,50,75,100,150")
    parser.add_argument("--seeds",default="0,1,2,3,4,5,6,7,8,9")
    parser.add_argument("--include-pso",action="store_true",help="Include optional custom discrete PSO")
    parser.add_argument("--include-ablations",action="store_true",help="Add score/search controls")
    parser.add_argument("--include-reference-baselines",action="store_true",help="Add five pinned Virne reference ports with the common hard QoS extension")
    parser.add_argument("--no-resume",action="store_true")
    parser.add_argument("--link-prob",type=float,default=0.35)
    parser.add_argument("--vnr-link-prob",type=float,default=0.4)
    parser.add_argument("--lifetime-mean",type=float,default=500.0,help="Seconds")
    parser.add_argument("--max-delay",type=float,default=25.0,help="Milliseconds per virtual link")
    parser.add_argument("--max-hops",type=int,default=8)
    parser.add_argument("--p-idle",type=float,default=150.0,help="Watts per powered node")
    parser.add_argument("--p-peak",type=float,default=350.0)
    parser.add_argument("--p-link",type=float,default=5.0)
    parser.add_argument("--boot-energy-joules",type=float,default=50.0)
    args = parser.parse_args()
    if args.duration is None:
        args.duration = {"smoke":250.,"full":10000.,"scalability":5000.}[args.mode]
    if args.num_nodes is None:
        args.num_nodes = 20 if args.mode == "smoke" else 50
    if not math.isfinite(args.duration) or args.duration <= 0 or args.num_nodes < 2 or args.workers < 1:
        parser.error("duration must be finite/positive, num-nodes >= 2 and workers >= 1")
    try:
        _scenario(args)
    except ValueError as error:
        parser.error(str(error))
    return args


def _scenario(args):
    fields = Scenario.__dataclass_fields__
    return Scenario(**{name: getattr(args, name) for name in fields})


def main():
    args = parse_args()
    save_config(args.output_dir,args)
    if args.mode == "smoke":
        frame = smoke_test(args.duration,args.num_nodes,args.include_pso,args.include_ablations,_scenario(args),
                           args.include_reference_baselines)
        _atomic_write_csv(frame,Path(args.output_dir)/"smoke.csv")
        return
    seeds = tuple(int(s) for s in args.seeds.split(",") if s.strip())
    if args.mode == "full":
        lambdas = tuple(float(s) for s in args.lambdas.split(",") if s.strip())
        run_full_evaluation(args.output_dir,lambdas,seeds,args.duration,args.num_nodes,args.workers,
                            args.include_pso,not args.no_resume,args.include_ablations,_scenario(args),
                            args.include_reference_baselines)
    else:
        sizes = tuple(int(s) for s in args.sizes.split(",") if s.strip())
        run_scalability_experiment(args.output_dir,sizes,seeds,args.duration,args.workers,
                                    args.include_pso,args.include_ablations,not args.no_resume,_scenario(args),
                                    args.include_reference_baselines)


