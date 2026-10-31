"""Keep original GPU notebooks and derive gateway-safe short-validation copies."""
import copy
import cycle


def build():
    record = cycle.read(cycle.HERE / "DERIVED_CANDIDATES.json")
    for profile in ("gpu-baseline", "gpu-memory"):
        original = cycle.read(cycle.HERE / "notebooks" / (profile + ".ipynb"))
        derived = copy.deepcopy(original)
        factory_changes = validation_changes = deadline_changes = readiness_changes = 0
        for cell in derived["cells"]:
            if cell["cell_type"] != "code":
                continue
            source = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
            if '# ---- launch detached and wait for health ----' in source:
                source += ('\n# Validate actual inference before the short normal benchmark.\n'
                    + (cycle.HERE / 'gpu_validation.py').read_text(encoding='utf-8')
                    + '\nif not TRUE_SUBMISSION:\n'
                    '    validate_model_backend(proc, SERVER_BASE_URL, SERVED_MODEL_NAME, WORKING_DIR / "model-diagnostics.json")\n')
                readiness_changes += 1
            if "def _competition_games():" in source:
                assert source.count('environments_dir=""') == 2
                source = source.replace('    import arc_agi\n', '    import arc_agi\n    import tempfile\n', 1)
                source = source.replace('    spec = taaf.game_api.ArcadeSpec(\n',
                    '    remote_only_dir = tempfile.mkdtemp(prefix="arc3_remote_only_")\n    spec = taaf.game_api.ArcadeSpec(\n', 1)
                source = source.replace('environments_dir=""', 'environments_dir=remote_only_dir')
                old = 'soft_end = datetime.fromtimestamp(NOTEBOOK_START_EPOCH) + timedelta(seconds=budget - min(600.0, budget / 2))'
                assert source.count(old) == 1
                source = source.replace(old, 'soft_end = datetime.now() + timedelta(seconds=300.0)')
                anchor = 'await bm.run(soft_end_time=soft_end, runtime_environment=target, minimal_diagnostics=TRUE_SUBMISSION)'
                assert source.count(anchor) == 1
                source = source.replace(anchor, anchor + '\nif not TRUE_SUBMISSION:\n'
                    '    validate_game_inference(bm.game_runs, WORKING_DIR / "model-diagnostics.json")')
                factory_changes += 1
                deadline_changes += 1
            if 'bm.solver.max_runtime_s_per_game = 48*60' in source:
                source += ('\n# Save Version checks connectivity; competition reruns retain the full settings above.\n'
                    'if not TRUE_SUBMISSION:\n'
                    '    bm.n_passes = 1\n'
                    '    bm.solver.concurrency = 4\n'
                    '    bm.solver.max_runtime_s_per_game = 90.0\n'
                    '    bm.solver.max_actions_per_game = 2\n')
                validation_changes += 1
            cell["source"] = source
        assert (factory_changes, validation_changes, deadline_changes, readiness_changes) == (1, 1, 1, 1)
        derived["cells"].insert(0, {"cell_type": "markdown", "metadata": {}, "id": "connection-validation-scope",
            "source": "# Official SDK connection variant\nGateway discovery uses a fresh empty directory. Normal Save Version waits for model health and a real completion, then uses one pass, four concurrent games, at most two actions and 90 seconds per game with a five-minute benchmark budget. It requires generated game tokens and a non-RESET action. Competition reruns keep the original full solver configuration. Original notebook retained separately.\n"})
        target = cycle.HERE / "notebooks" / (profile + "-connected.ipynb")
        cycle.save(target, cycle.clean_notebook(derived))
        record[profile + "-connected"] = {"baseline": profile, "original_code_sha256": cycle.code_hash(original),
            "candidate_code_sha256": cycle.code_hash(derived),
            "competition_path_change": "Explicit fresh empty environment directory; no cwd demo scan",
            "save_version_change": "Short connectivity run; competition solver policy and budgets unchanged",
            "official_score": None}
    cycle.save(cycle.HERE / "DERIVED_CANDIDATES.json", record)


if __name__ == "__main__":
    build()
