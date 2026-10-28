"""Offline tests for mutations, receipts, identity and comparison boundaries."""
import copy
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace as Obj
import unittest

import cycle


class MissingKernel(Exception):
    response = Obj(status_code=404)


class FakeKaggle:
    def __init__(self, bundle):
        self.bundle = Path(bundle)
        self.exists, self.pushes, self.submits = False, 0, 0
        self.push_timeout = self.submit_timeout = False
        self.invalid_models = []
        self.worker_status = "COMPLETE"
        self.history, self.status_queries = [], []
        self.source_changed = self.image_changed = False
        self.file_present = True
        self.username = "sumuji"
        self.absent_status = 404

    def get_config_value(self, key):
        return self.username

    def kernels_list(self, *, page=1, page_size=100, mine=False):
        return [Obj(ref=cycle.verify(self.bundle)["kernel"])] if self.exists else []

    def kernels_pull(self, kernel, path, metadata=False, quiet=True):
        if not self.exists:
            error = MissingKernel()
            error.response = Obj(status_code=self.absent_status)
            raise error
        path = Path(path)
        meta = cycle.read(self.bundle / "kernel-metadata.json")
        nb = cycle.read(self.bundle / "submission.ipynb")
        if self.source_changed:
            nb["cells"][0]["source"] = "print('other candidate')"
        if self.image_changed:
            meta["docker_image"] = "different-image"
        cycle.save(path / "kernel-metadata.json", meta)
        cycle.save(path / "submission.ipynb", nb)

    def kernels_push(self, folder, timeout=None, acc=None, no_run=False):
        self.pushes += 1
        self.exists = True
        if self.push_timeout:
            raise TimeoutError("Ambiguous push")
        return Obj(version_number=4, error="", url="https://www.kaggle.com/code/test/candidate",
                   invalid_model_sources=self.invalid_models)

    def kernels_status(self, kernel):
        self.status_queries.append(kernel)
        return Obj(status=self.worker_status, failure_message="")

    def competition_submissions(self, competition, *, page_number=-1, page_size=20):
        return self.history[(page_number-1)*page_size:page_number*page_size]

    def kernels_output(self, kernel, path, quiet=True, file_pattern=None):
        if self.file_present:
            (Path(path) / "submission.parquet").write_bytes(b"fixture-output-not-a-real-score")

    def competition_submit_code(self, file_name, message, competition, kernel, kernel_version, quiet=False):
        self.submits += 1
        self.history.append(Obj(ref=72, description=message, status="PENDING", public_score="",
                                private_score="", error_description=""))
        if self.submit_timeout:
            raise TimeoutError("Ambiguous submit")
        return Obj(ref=72, message="fixture")

    def get_submission(self, ref):
        return next(s for s in self.history if s.ref == ref)


class CycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.nb = self.root / "input.ipynb"
        cycle.save(self.nb, {"nbformat": 4, "nbformat_minor": 4, "metadata": {}, "cells": [
            {"cell_type": "code", "metadata": {}, "source": "print(1)", "execution_count": 9,
             "outputs": [{"output_type": "stream", "name": "stdout", "text": "historical"}]}]})
        self.bundle = self.make_bundle()
        self.api = FakeKaggle(self.bundle)

    def tearDown(self):
        self.temp.cleanup()

    def make_bundle(self, name="first", profile="cpu-c8b", env=None):
        path = self.root / name
        cycle.prepare(profile, path, name, "fixture hypothesis", notebook=self.nb, environment_path=env)
        if profile == "cpu-c8b":
            cycle.event(path, "public-smoke.json", passed=True, errors=[], results=[
                {"candidate_id": cycle.verify(path)["candidate_id"], "official_loop_unchanged": True}])
        return path

    def started(self):
        cycle.start(self.api, self.bundle)

    def score(self, bundle, value, ref):
        cycle.event(bundle, "readback.json", docker_image="same-test-image")
        cycle.event(bundle, "official-score.json", ref=ref, status="COMPLETE", public_score=value,
                    competition=cycle.COMPETITION)

    def test_prepare_preserves_code_and_removes_historical_outputs(self):
        original, clean = cycle.read(self.nb), cycle.read(self.bundle / "submission.ipynb")
        self.assertEqual(cycle.code_sources(original), cycle.code_sources(clean))
        self.assertEqual(clean["cells"][0]["outputs"], [])
        self.assertEqual(original["cells"][0]["execution_count"], 9)

    def test_changed_candidate_bytes_rejected(self):
        (self.bundle / "submission.ipynb").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "bytes changed"):
            cycle.start(self.api, self.bundle)
        self.assertEqual(self.api.pushes, 0)

    def test_cpu_without_game_evidence_cannot_start(self):
        (self.bundle / "evidence" / "public-smoke.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.started()
        self.assertEqual(self.api.pushes, 0)

    def test_existing_output_directory_not_overwritten(self):
        with self.assertRaises(FileExistsError):
            self.make_bundle()

    def test_push_uses_one_version_and_never_repeats(self):
        self.started()
        cycle.start(self.api, self.bundle)
        cycle.observe_kernel(self.api, self.bundle)
        self.assertEqual(self.api.pushes, 1)
        self.assertTrue(self.api.status_queries[0].endswith("/4"))

    def test_ambiguous_push_requires_adoption(self):
        self.api.push_timeout = True
        with self.assertRaises(TimeoutError):
            self.started()
        with self.assertRaisesRegex(ValueError, "Previous push"):
            self.started()
        cycle.adopt(self.api, self.bundle, 4)
        self.started()
        self.assertEqual(self.api.pushes, 1)

    def test_fresh_runner_refuses_existing_remote_candidate(self):
        self.api.exists = True
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.started()
        self.assertEqual(self.api.pushes, 0)

    def test_auth_failure_never_causes_push(self):
        def denied(*args, **kwargs):
            raise PermissionError("denied")
        self.api.kernels_pull = denied
        with self.assertRaises(PermissionError):
            self.started()
        self.assertEqual(self.api.pushes, 0)

    def test_kaggle_403_for_absent_owned_slug_can_create(self):
        self.api.absent_status = 403
        self.started()
        self.assertEqual(self.api.pushes, 1)

    def test_wrong_authenticated_owner_cannot_create(self):
        self.api.username = "another-user"
        with self.assertRaisesRegex(ValueError, "does not own"):
            self.started()
        self.assertEqual(self.api.pushes, 0)

    def test_readback_source_mismatch_stops_submission(self):
        self.started()
        self.api.source_changed = True
        with self.assertRaisesRegex(ValueError, "source differs"):
            cycle.submit(self.api, self.bundle)
        self.assertEqual(self.api.submits, 0)

    def test_invalid_model_mount_blocks_submission(self):
        self.api.invalid_models = ["missing-model"]
        with self.assertRaisesRegex(ValueError, "did not accept"):
            self.started()
        with self.assertRaisesRegex(ValueError, "Rejected push"):
            cycle.submit(self.api, self.bundle)

    def test_notebook_running_cannot_be_submitted(self):
        self.started()
        self.api.worker_status = "RUNNING"
        with self.assertRaisesRegex(ValueError, "not completed"):
            cycle.submit(self.api, self.bundle)

    def test_missing_output_cannot_be_submitted(self):
        self.started()
        self.api.file_present = False
        with self.assertRaisesRegex(ValueError, "did not produce"):
            cycle.submit(self.api, self.bundle)
        self.assertEqual(self.api.submits, 0)

    def test_collect_output_does_not_submit_and_can_be_reused(self):
        self.started()
        value = cycle.collect_output(self.api, self.bundle)
        self.assertIn("submission.parquet", value["files"])
        self.assertEqual(cycle.collect_output(self.api, self.bundle), value)
        self.assertEqual(self.api.submits, 0)

    def test_failed_notebook_output_can_be_collected_without_submission(self):
        self.started()
        self.api.worker_status = "ERROR"
        self.api.file_present = False
        value = cycle.collect_output(self.api, self.bundle)
        self.assertEqual(value["notebook_status"], "ERROR")
        self.assertEqual(self.api.submits, 0)

    def test_submit_once_and_observe_same_ref(self):
        self.started()
        cycle.submit(self.api, self.bundle)
        cycle.submit(self.api, self.bundle)
        value = cycle.observe_score(self.api, self.bundle)
        self.assertEqual(value["ref"], 72)
        self.assertEqual(self.api.submits, 1)

    def test_submit_timeout_reconciles_without_resubmission(self):
        self.started()
        self.api.submit_timeout = True
        with self.assertRaises(TimeoutError):
            cycle.submit(self.api, self.bundle)
        result = cycle.submit(self.api, self.bundle)
        self.assertEqual(result["action"], "adopted_existing")
        self.assertEqual(self.api.submits, 1)

    def test_invisible_timed_out_submit_is_not_retried(self):
        self.started()
        self.api.submit_timeout = True
        with self.assertRaises(TimeoutError):
            cycle.submit(self.api, self.bundle)
        self.api.history = []
        with self.assertRaisesRegex(ValueError, "Previous submit"):
            cycle.submit(self.api, self.bundle)
        self.assertEqual(self.api.submits, 1)

    def test_second_history_page_is_searched(self):
        self.started()
        self.api.history = [Obj(ref=n, description="unrelated") for n in range(100)] + [
            Obj(ref=999, description=cycle.marker(self.bundle))]
        value = cycle.submit(self.api, self.bundle)
        self.assertEqual(value["ref"], 999)
        self.assertEqual(self.api.submits, 0)

    def test_ambiguous_remote_submissions_rejected(self):
        self.api.history = [Obj(ref=n, description=cycle.marker(self.bundle)) for n in (1, 2)]
        with self.assertRaisesRegex(ValueError, "found 2"):
            cycle.reconcile_submission(self.api, self.bundle)

    def test_receipt_from_another_candidate_rejected(self):
        self.started()
        other = self.make_bundle("other")
        shutil.copytree(self.bundle / "evidence", other / "evidence", dirs_exist_ok=True)
        with self.assertRaisesRegex(ValueError, "another candidate"):
            cycle.observe_kernel(FakeKaggle(other), other)

    def test_gpu_without_image_can_prepare_but_cannot_start(self):
        gpu = self.make_bundle("gpu", "gpu-memory")
        self.assertTrue(cycle.verify(gpu)["launch_blockers"])
        with self.assertRaisesRegex(ValueError, "resolve original"):
            cycle.start(FakeKaggle(gpu), gpu)

    def test_zero_public_score_is_valid(self):
        other = self.make_bundle("other")
        self.score(self.bundle, "0.00", 1)
        self.score(other, "0.01", 2)
        self.assertEqual(cycle.compare(self.bundle, other)["absolute_change"], "0.01")

    def test_cross_line_scores_cannot_be_compared(self):
        gpu = self.make_bundle("gpu", "gpu-baseline")
        self.score(self.bundle, "0.01", 1)
        self.score(gpu, "0.02", 2)
        with self.assertRaisesRegex(ValueError, "line"):
            cycle.compare(self.bundle, gpu)

    def test_notebook_completion_is_not_an_official_score(self):
        self.started()
        cycle.observe_kernel(self.api, self.bundle)
        other = self.make_bundle("other")
        with self.assertRaises(FileNotFoundError):
            cycle.compare(self.bundle, other)

    def test_actual_runtime_image_drift_prevents_comparison(self):
        other = self.make_bundle("other")
        self.score(self.bundle, "0.01", 1)
        self.score(other, "0.02", 2)
        cycle.event(other, "readback.json", docker_image="another-image")
        with self.assertRaisesRegex(ValueError, "runtime images"):
            cycle.compare(self.bundle, other)

    def test_exact_measured_cpu_baseline_can_reuse_evidence(self):
        real = self.root / "measured"
        cycle.prepare("cpu-c8b", real, "measured", "baseline reproduction")
        value = cycle.reuse_cpu_baseline_evidence(real)
        self.assertTrue(value["passed"])
        self.assertIn("no new game execution", value["scope"])
        self.assertNotEqual(value["source_candidate_id"], value["candidate_id"])

    def test_changed_cpu_source_cannot_reuse_baseline_evidence(self):
        nb = cycle.read(cycle.HERE / "notebooks/cpu-c8b.ipynb")
        cell = next(c for c in nb["cells"] if c["cell_type"] == "code")
        source = "".join(cell["source"]) if isinstance(cell["source"], list) else cell["source"]
        cell["source"] = source + "\n# changed candidate\n"
        file = self.root / "changed.ipynb"
        cycle.save(file, nb)
        real = self.root / "changed-real"
        cycle.prepare("cpu-c8b", real, "changed", "source changed", notebook=file)
        with self.assertRaisesRegex(ValueError, "fresh public-smoke"):
            cycle.reuse_cpu_baseline_evidence(real)

    def test_status_identity_checked(self):
        self.started()
        cycle.submit(self.api, self.bundle)
        self.api.history[0].description = "other-submission"
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            cycle.observe_score(self.api, self.bundle)

    def test_notebook_hypothesis_changes_identity(self):
        other = self.root / "changed"
        cycle.prepare("cpu-c8b", other, "first", "different hypothesis", notebook=self.nb)
        self.assertNotEqual(cycle.verify(self.bundle)["candidate_id"], cycle.verify(other)["candidate_id"])

    def test_gpu_pair_uses_same_explicit_environment(self):
        config = cycle.profiles()["gpu-baseline"]
        env = self.root / "environment.json"
        cycle.save(env, {"reference": "dfranzen/arc-agi-3-milestone-2-solution/3", "docker_image": "fixed-image",
                         "dataset_sources": config["dataset_sources"], "model_sources": config["model_sources"],
                         "competition_sources": [cycle.COMPETITION]})
        left = self.make_bundle("baseline", "gpu-baseline", env)
        right = self.make_bundle("memory", "gpu-memory", env)
        self.score(left, "0.1", 1)
        self.score(right, "0.2", 2)
        self.assertTrue(cycle.compare(left, right)["improved_public_score"])
        api = FakeKaggle(right)
        cycle.start(api, right)
        api.image_changed = True
        with self.assertRaisesRegex(ValueError, "environment image"):
            cycle.submit(api, right)

    def environment_api(self, model_version="1"):
        config = cycle.profiles()["gpu-baseline"]
        def pull(kernel, path, metadata=False, quiet=True):
            self.assertEqual(kernel, "dfranzen/arc-agi-3-milestone-2-solution/3")
            models = [s.replace("/transformers/", "/Transformers/").rsplit("/", 1)[0] + "/" + model_version
                      for s in config["model_sources"]]
            cycle.save(Path(path) / "kernel-metadata.json", {"docker_image": "original-image",
                       "dataset_sources": [s + "/7" for s in config["dataset_sources"]],
                       "model_sources": models, "competition_sources": [cycle.COMPETITION]})
        return Obj(kernels_pull=pull)

    def test_original_environment_accepts_framework_enum_casing(self):
        value = cycle.environment(self.environment_api(), self.root / "gpu-env.json")
        self.assertTrue(all("/Transformers/" in s for s in value["model_sources"]))
        self.assertEqual(value["competition_sources"], [cycle.COMPETITION])

    def test_original_environment_keeps_dataset_versions(self):
        value = cycle.environment(self.environment_api(), self.root / "gpu-env.json")
        self.assertTrue(all(s.endswith("/7") for s in value["dataset_sources"]))

    def test_model_version_change_is_rejected_and_observed_metadata_retained(self):
        out = self.root / "gpu-env.json"
        with self.assertRaisesRegex(ValueError, "model_sources differ"):
            cycle.environment(self.environment_api("2"), out)
        self.assertFalse(out.exists())
        self.assertTrue(out.with_suffix(".observed.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
