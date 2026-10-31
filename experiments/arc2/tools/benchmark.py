#!/usr/bin/env python3
"""Evaluate disjoint task ranges under one frozen source/configuration manifest."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from arc2.runner import atomic_json, code_manifest, score_submission


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--tasks",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--limit",type=int)
    parser.add_argument("--shards",type=int,default=4)
    parser.add_argument("--seconds-per-task",type=float,default=8)
    parser.add_argument("--max-states",type=int,default=4000)
    parser.add_argument("--beam-width",type=int,default=32)
    parser.add_argument("--max-depth",type=int,default=3)
    parser.add_argument("--backend",choices=("hybrid","python"),default="hybrid")
    parser.add_argument("--cpp-memory-mb",type=int,default=768)
    args=parser.parse_args()
    if args.shards<1 or args.shards>8: parser.error("shards must be 1..8")
    args.tasks=args.tasks.resolve();args.output=args.output.resolve()
    paths=sorted(args.tasks.glob("*.json"))
    if args.limit: paths=paths[:args.limit]
    if not paths: parser.error("No tasks")
    args.output.mkdir(parents=True,exist_ok=True)
    code=code_manifest()
    manifest={"created_utc":datetime.now(timezone.utc).isoformat(),"code_sha256":code,
              "tasks":[p.stem for p in paths],"config":{k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()},
              "dataset_sha256":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
              "evaluation_policy":"all declared tasks, disjoint fixed shards; no score feedback during run"}
    if args.backend=="hybrid":
        from arc2.cpp_backend import prepare_cpp_backend
        manifest["cpp_preparation"]=prepare_cpp_backend(compile_seconds=180)
        print(json.dumps(manifest["cpp_preparation"]),flush=True)
    atomic_json(args.output/"frozen_manifest.json",manifest)
    env=os.environ.copy();env.update(OPENBLAS_NUM_THREADS="1",OMP_NUM_THREADS="1",MKL_NUM_THREADS="1")
    count=math.ceil(len(paths)/args.shards); jobs=[];start=time.monotonic()
    for shard,offset in enumerate(range(0,len(paths),count)):
        folder=args.output/f"shard_{shard}";folder.mkdir(exist_ok=True)
        cmd=[sys.executable,"-m","arc2","evaluate","--tasks",str(args.tasks),"--output",str(folder/"report.json"),
             "--offset",str(offset),"--limit",str(min(count,len(paths)-offset)),
             "--seconds-per-task",str(args.seconds_per_task),"--max-states",str(args.max_states),
             "--beam-width",str(args.beam_width),"--max-depth",str(args.max_depth),"--backend",args.backend,
             "--cpp-memory-mb",str(args.cpp_memory_mb)]
        log=(folder/"run.log").open("w")
        p=subprocess.Popen(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        jobs.append((p,log,folder))
    try:
        pending=set(range(len(jobs)))
        while pending:
            for i in sorted(pending.copy()):
                process,log,folder=jobs[i]
                if process.poll() is not None:
                    log.close();pending.remove(i)
                    print(f"Shard {i}: exit={process.returncode}",flush=True)
            time.sleep(.2)
    finally:
        for process,log,folder in jobs:
            if process.poll() is None:
                process.terminate();process.wait(timeout=5)
            log.close()
    if any(p.returncode for p,_,_ in jobs):
        raise RuntimeError("A shard failed; inspect run.log, no aggregate score emitted")
    if code_manifest()!=code:
        raise RuntimeError("Source changed during benchmark; result is not frozen")
    submission={};diagnostics={};task_reports={};symbolic={};cpp_only={}
    for _,_,folder in jobs:
        report=json.loads((folder/"report.json").read_text())
        if report["code_sha256"]!=code:
            raise RuntimeError("A shard used different source hashes")
        sub=json.loads((folder/"report.submission.json").read_text())
        dia=json.loads((folder/"report.diagnostics.json").read_text())
        if set(sub)&set(submission): raise RuntimeError("Overlapping task shards")
        submission.update(sub);diagnostics.update(dia["tasks"])
        task_reports.update(report["metrics"]["tasks"])
    if set(submission)!={p.stem for p in paths}: raise RuntimeError("Missing tasks")
    solutions={p.stem:[pair["output"] for pair in json.loads(p.read_text())["test"]] for p in paths}
    for task_id,own in submission.items():
        d=diagnostics[task_id]
        symbolic[task_id]=d.get("symbolic_attempts",own)
        predicted=d.get("cpp_predictions",[])
        task=json.loads((args.tasks/f"{task_id}.json").read_text())
        cpp_only[task_id]=[]
        for i,t in enumerate(task["test"]):
            choices=predicted[i] if i<len(predicted) else []
            a=choices[0] if choices else t["input"]
            b=choices[1] if len(choices)>1 else a
            cpp_only[task_id].append({"attempt_1":a,"attempt_2":b})
    metrics=score_submission(submission,solutions)
    symbolic_metrics=score_submission(symbolic,solutions)
    cpp_metrics=score_submission(cpp_only,solutions)
    status={}
    for d in diagnostics.values():
        k=d.get("runner_status","unknown");status[k]=status.get(k,0)+1
    report={"created_utc":datetime.now(timezone.utc).isoformat(),"wall_seconds":time.monotonic()-start,
            "config":manifest["config"],"code_sha256":code,"dataset_sha256":manifest["dataset_sha256"],
            "metrics":metrics,"component_metrics":{"python_same_run":symbolic_metrics,"cpp_same_run":cpp_metrics},
            "runner_status_counts":status,"answer_visibility":"answers stripped before each inference worker",
            "component_warning":"Component metrics use their allocated fraction of total time, not full-budget standalone runs.",
            "shards":len(jobs),"source_unchanged":True}
    atomic_json(args.output/"submission.json",submission)
    atomic_json(args.output/"diagnostics.json",diagnostics)
    atomic_json(args.output/"report.json",report)
    print(json.dumps({"metrics":{k:v for k,v in metrics.items() if k!="tasks"},
                      "component_metrics":{name:{k:v for k,v in vals.items() if k!="tasks"}
                                           for name,vals in report["component_metrics"].items()},
                      "runner_status_counts":status,"wall_seconds":report["wall_seconds"]},indent=2),flush=True)


if __name__=="__main__": main()
