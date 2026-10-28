"""Normal Notebook validation only; embedded verbatim in derived notebooks."""


def validate_model_backend(process, base_url, model, diagnostics_path, *, timeout_s=2700):
    import json
    from pathlib import Path
    import time
    from urllib.request import Request, urlopen

    started = time.monotonic()
    while True:
        if process.poll() is not None:
            raise RuntimeError("Validation model server exited before readiness")
        if time.monotonic() - started >= timeout_s:
            raise RuntimeError("Validation model readiness deadline exceeded")
        try:
            with urlopen(base_url.removesuffix("/v1") + "/health", timeout=5) as response:
                ready = response.status == 200
        except Exception:
            ready = False
        if ready:
            break
        time.sleep(5)
    payload = {"model": model, "messages": [{"role": "user", "content": "Reply READY."}],
               "max_tokens": 16, "temperature": 0,
               "chat_template_kwargs": {"enable_thinking": False}}
    request = Request(base_url.rstrip("/") + "/chat/completions",
                      data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=120) as response:
        result = json.load(response)
    tokens = int(result.get("usage", {}).get("completion_tokens", 0))
    if not result.get("choices") or tokens <= 0:
        raise RuntimeError("Validation model produced no completion tokens")
    report = {"backend_ready": True, "probe_completion_tokens": tokens,
              "readiness_wait_seconds": time.monotonic() - started,
              "scope": "Normal Save Version connectivity; not an official score"}
    Path(diagnostics_path).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def validate_game_inference(game_runs, diagnostics_path):
    import json
    from pathlib import Path

    tokens = sum(sum(a.generated_tokens for a in run.history) + run.final_generated_tokens for run in game_runs)
    actions = sum(sum(a.action.id.name != "RESET" for a in run.history) for run in game_runs)
    path = Path(diagnostics_path)
    report = json.loads(path.read_text(encoding="utf-8"))
    report.update({"game_generated_tokens": tokens, "non_reset_game_actions": actions,
                   "passed": tokens > 0 and actions > 0})
    path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        raise RuntimeError("Validation requires generated game tokens and a non-RESET game action")
    return report
