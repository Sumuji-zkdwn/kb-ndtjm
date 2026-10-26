#!/usr/bin/env python3
"""Local DQI gates. NEVER sends a Kaggle submission."""
import argparse, hashlib, json, math, re, shutil, struct, sys, time, zipfile
from pathlib import Path

BASE_SHA = "04cf2fc7518e9cc2f9207f61b9421448a0b02368756c6b342fb4cea8c47b0f43"
MAGIC = bytes.fromhex("d750c7d5c329d326e3cc9f6834f2b8bf")
NAMES = {*(f"S{i}" for i in range(70)), *(f"E{i}" for i in range(4095))}
EEA_CHECKPOINT_SHA = "416c70ef2097a07d166b8f9276872a911177694e12fe44cbf4ac23277fa94cb1"
MULTIPLY42_CHECKPOINT_SHA = "7312fd51394bc186eb189f89647c3c8a1198c023513f0cae105b005b9b1eeab6"

def sha(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        while chunk:=f.read(1<<22):
            h.update(chunk)
    return h.hexdigest()

def exact(f,n):
    b=f.read(n)
    if len(b)!=n: raise ValueError("truncated KMB")
    return b

def inspect_kmb(f):
    b=exact(f,104)
    if b[:16]!=MAGIC: raise ValueError("invalid KMB signature")
    version,nq,nb,nr=struct.unpack_from("<IIII",b,16)
    totals=struct.unpack_from("<9Q",b,32)
    if version!=2 or nr!=4165 or nq>1000000 or nb>1000000:
        raise ValueError("invalid DQI header")
    names=set()
    qubits=set()
    bits=set()
    for _ in range(nr):
        typ,length=struct.unpack("<QQ",exact(f,16))
        nl,count=struct.unpack("<II",exact(f,8))
        if typ!=0 or count!=12 or length!=8+nl+4*count or nl>64:
            raise ValueError("bad KMB register packet")
        name=exact(f,nl).decode()
        vals=struct.unpack("<12I",exact(f,4*count))
        if name in names or not re.fullmatch(r"[SE][0-9]+",name):
            raise ValueError(f"bad register {name!r}")
        names.add(name)
        qtype=name.startswith("S")
        target=qubits if qtype else bits
        maximum=nq if qtype else nb
        for x in vals:
            if bool(x & (1<<31))!=qtype or x&0x7fffffff>=maximum or (x&0x7fffffff) in target:
                raise ValueError(f"bad register mapping {name}")
            target.add(x&0x7fffffff)
    if names!=NAMES: raise ValueError(f"DQI register mismatch: missing {len(NAMES-names)}")
    return {"qubits":nq,"bits":nb,"registers":nr,"ops":totals[0],
            "3q_ops":totals[1],"2q_ops":totals[2],"register_contract":"PASS"}

def baseline(path):
    checksum=sha(path)
    if checksum!=BASE_SHA: raise ValueError(f"baseline SHA mismatch {checksum}")
    with zipfile.ZipFile(path) as z:
        names=z.namelist()
        if len(names)!=len(set(names)) or len(names)!=13:
            raise ValueError("baseline zip member count or duplicates")
        if not {"invsqrt.kmb","dqi.kmb","dfthcsos/submission.npz"}<=set(names):
            raise ValueError("missing baseline member")
        angle=[x for x in names if re.fullmatch(r"dfthcsos/angle_k_\d+\.kmb",x)]
        if sorted(angle)!=sorted(f"dfthcsos/angle_k_{i}.kmb" for i in range(len(angle))) or not angle:
            raise ValueError("nonconsecutive angle circuits")
        with z.open("dqi.kmb") as f: info=inspect_kmb(f)
        for name in names:
            with z.open(name) as f:
                while f.read(1<<22): pass
    return {"archive_sha256":checksum,"members":len(names),
            "angle_count":len(angle),"dqi":info,"status":"PASS"}

def candidate(path):
    if Path(path).suffix!=".kmb":
        raise ValueError("candidate must be a complete dqi.kmb, not the local WFS .kmx")
    with open(path,"rb") as f: info=inspect_kmb(f)
    return {"candidate_sha256":sha(path),"candidate_bytes":Path(path).stat().st_size,
            "dqi":info,"quantum_correctness":"NOT_YET_VERIFIED","status":"PASS"}

def smoke_shot_count(verifier):
    """Smallest batch-aligned budget able to pass the UNMODIFIED confidence gate.

    Even zero observed errors cannot pass with only 512 shots at delta=2^-128.
    Ask the official bound instead of weakening its confidence or error limit.
    """
    batch=verifier.DEFAULT_BATCH_SIZE
    shots=2*batch
    while verifier.clopper_pearson_upper_bound(0,shots,verifier.DEFAULT_LOG2_DELTA)>=1/16:
        shots+=batch
        if shots>verifier.DEFAULT_NUM_SHOTS:
            raise ValueError("official default shot budget cannot satisfy smoke confidence")
    return shots

def verify(path,data,shots,salt):
    sys.path.insert(0,str(Path(data)/"kickmix"))
    sys.path.insert(0,str(Path(data)/"verifiers"))
    import kickmix
    from dqi import verify_submission_dqi as vdqi
    spec=vdqi.ProblemSpecDQI.benchmark_instance(num_shots=shots)
    circuit=kickmix.Circuit.from_file(path,format="kmb")
    t=time.monotonic()
    # Shared explicit seed couples candidate/baseline inputs and measurement draws.
    # Salt alone does not: the official default also mixes in each circuit's SHA.
    result=vdqi.verify(circuit,spec,salt=salt,seed=20261025,max_workers=1)
    score=float(result["score"])
    if not math.isfinite(score) or not score>0: raise RuntimeError("nonfinite or nonpositive verifier cost")
    return {"status":"PASS","cost":score,"num_shots":shots,
            "value_errors":result["value_errors"],"phase_errors":result["phase_errors"],
            "effective_error_rate":result["effective_error_rate"],
            "log2_delta":result["log2_delta"],"seed":20261025,"max_workers":1,
            "toffoli_count":result["toffoli_count"],
            "elapsed_seconds":round(time.monotonic()-t,2),
            "verifier_sha256":sha(Path(data)/"verifiers/dqi/verify_submission_dqi.py"),
            "candidate_sha256":sha(path),"source":"published verifier; non-secret local salt"}

def validate_comparison_measurement(report,reference,verifier,verifier_sha):
    """Check a saved full measurement against actual reference bytes and verifier.

    This is only for an unchanged comparison circuit. Every new candidate still
    receives a fresh full run. The caller additionally pins the archived evidence.
    """
    if report.get("status")!="PASS" or report.get("stage")!="full-package":
        raise ValueError("comparison measurement is not a passed full-package report")
    measured=report.get("candidate",{})
    for key in ("candidate_sha256","candidate_bytes","dqi"):
        if measured.get(key)!=reference.get(key):
            raise ValueError(f"comparison reference {key} mismatch")
    full=report.get("full",{})
    expected={"status":"PASS","candidate_sha256":reference["candidate_sha256"],
              "verifier_sha256":verifier_sha,"num_shots":verifier.DEFAULT_NUM_SHOTS,
              "log2_delta":verifier.DEFAULT_LOG2_DELTA,"seed":20261025,"max_workers":1}
    if any(full.get(k)!=v for k,v in expected.items()):
        raise ValueError("comparison measurement hash or verifier configuration mismatch")
    errors=[full.get(k) for k in ("value_errors","phase_errors")]
    if any(type(e) is not int or not 0<=e<=full["num_shots"] for e in errors):
        raise ValueError("invalid comparison error counts")
    # Match the published verifier's union bound: value plus phase errors.
    if sum(errors)>full["num_shots"]:
        raise ValueError("comparison total error count exceeds shot count")
    bound=verifier.clopper_pearson_upper_bound(sum(errors),full["num_shots"],full["log2_delta"])
    if not math.isfinite(bound) or not 0<=bound<1/16:
        raise ValueError("comparison fails official error bound")
    if not math.isclose(full.get("effective_error_rate",math.nan),bound,rel_tol=1e-12):
        raise ValueError("comparison error bound mismatch")
    toffoli=full.get("toffoli_count",math.nan)
    if not math.isfinite(toffoli) or not 0<toffoli<=reference["dqi"]["3q_ops"]:
        raise ValueError("invalid comparison Toffoli count")
    cost=verifier.repetition_overhead(bound)*reference["dqi"]["qubits"]**2*toffoli
    saved=full.get("cost",math.nan)
    if not math.isfinite(saved) or saved<=0 or not math.isclose(saved,cost,rel_tol=1e-12):
        raise ValueError("comparison cost mismatch")
    return dict(full)

def reuse_comparison_checkpoint(path,reference,data,verifier):
    checkpoint_sha=sha(path)
    if checkpoint_sha not in (EEA_CHECKPOINT_SHA, MULTIPLY42_CHECKPOINT_SHA):
        raise ValueError("comparison checkpoint is not the pinned successful comparison evidence")
    checkpoint=json.loads(Path(path).read_text())
    if checkpoint["status"]!="PASS" or checkpoint["actions_run_conclusion"]!="success":
        raise ValueError("comparison checkpoint did not pass")
    report=checkpoint["all_site_gates"]["gates"]["full-package"]
    full=validate_comparison_measurement(report,reference,verifier,
        sha(Path(data)/"verifiers/dqi/verify_submission_dqi.py"))
    full["source"]="REUSED_VERIFIED_REPORT; unchanged reference was not rerun in this job"
    full["measurement_actions_run"]=checkpoint["actions_run"]
    full["measurement_source_commit"]=checkpoint["source_commit"]
    full["checkpoint_sha256"]=checkpoint_sha
    return full

def pack(baseline_path,candidate_path,dest):
    with zipfile.ZipFile(baseline_path) as src, zipfile.ZipFile(dest,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as dst:
        for info in src.infolist():
            if info.filename=="dqi.kmb":
                with open(candidate_path,"rb") as f, dst.open("dqi.kmb","w") as out:
                    shutil.copyfileobj(f,out,length=1<<22)
            else:
                with src.open(info) as f, dst.open(info.filename,"w") as out:
                    shutil.copyfileobj(f,out,length=1<<22)
    with zipfile.ZipFile(dest) as z:
        if z.testzip() is not None: raise ValueError("invalid candidate ZIP CRC")
    return {"zip_sha256":sha(dest),"zip_bytes":Path(dest).stat().st_size}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--stage",required=True,choices=["baseline","candidate","smoke","full-package"])
    p.add_argument("--baseline",required=True)
    p.add_argument("--candidate")
    p.add_argument("--comparison", help="Optional complete previously validated DQI for incremental full comparison")
    p.add_argument("--comparison-checkpoint", help="Reuse only a pinned successful comparison measurement; new candidates are always rerun")
    p.add_argument("--data-root")
    p.add_argument("--out",default="build/gated")
    a=p.parse_args()
    out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
    result={"stage":a.stage,"submits_to_kaggle":False,"platform_secret_salt":"unavailable"}
    try:
        if a.comparison_checkpoint and not a.comparison:
            raise ValueError("comparison checkpoint requires an explicit complete comparison circuit")
        result["baseline"]=baseline(a.baseline)
        if a.stage!="baseline":
            if not a.candidate or not Path(a.candidate).is_file():
                raise ValueError("explicit full DQI candidate is mandatory")
            result["candidate"]=candidate(a.candidate)
            if a.comparison:
                result["comparison"]=candidate(a.comparison)
        if a.stage in ("smoke","full-package"):
            if not a.data_root: raise ValueError("published official verifier data missing")
            sys.path.insert(0,str(Path(a.data_root)/"verifiers"))
            from dqi import verify_submission_dqi as v
            salt="wfs-dqi-public-local-seed-20261025"
            smoke_shots=smoke_shot_count(v)
            result["smoke_plan"]={"num_shots":smoke_shots,
                "zero_error_upper_bound":v.clopper_pearson_upper_bound(0,smoke_shots,v.DEFAULT_LOG2_DELTA),
                "log2_delta":v.DEFAULT_LOG2_DELTA,"error_limit":1/16,"confidence_unmodified":True}
            result["smoke"]=verify(a.candidate,a.data_root,smoke_shots,salt)
            if a.stage=="full-package":
                result["full"]=verify(a.candidate,a.data_root,v.DEFAULT_NUM_SHOTS,salt)
                if a.comparison:
                    reference_dqi=Path(a.comparison)
                    reference_key="comparison_full"
                    result["comparison_kind"]="incremental versus explicitly supplied DQI; ZIP baseline remains v1.0"
                else:
                    reference_dqi=out/"baseline-dqi.kmb"
                    with zipfile.ZipFile(a.baseline) as z, reference_dqi.open("wb") as f:
                        with z.open("dqi.kmb") as src:
                            shutil.copyfileobj(src,f,length=1<<22)
                    reference_key="baseline_full"
                    result["comparison_kind"]="versus v1.0 DQI"
                if a.comparison_checkpoint:
                    result[reference_key]=reuse_comparison_checkpoint(a.comparison_checkpoint,result["comparison"],a.data_root,v)
                else:
                    result[reference_key]=verify(reference_dqi,a.data_root,v.DEFAULT_NUM_SHOTS,salt)
                old=result[reference_key]["cost"]
                new=result["full"]["cost"]
                result["local_improvement"]=new<old
                if not result["local_improvement"]:
                    raise RuntimeError(f"No cost reduction versus comparison circuit: {new} >= {old}")
                result["packaging"]=pack(a.baseline,a.candidate,out/"submission-candidate.zip")
                result["candidate_status"]="ready for USER-APPROVED Kaggle submission"
        result["status"]="PASS"
    except Exception as e:
        result["status"]="FAIL"
        result["failure"]=f"{type(e).__name__}: {e}"
        raise
    finally:
        (out/"report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
        print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=="__main__":main()

