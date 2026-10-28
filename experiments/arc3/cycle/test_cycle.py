"""Offline tests for mutations, receipts, identity and comparison boundaries."""
import copy
import io
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace as Obj
import unittest
from unittest.mock import patch

import cycle
import gpu_validation
import runner


class GpuValidationTests(unittest.TestCase):
    def test_official_queue_deferral_is_observed_without_forcing_submission(self):
        values = [{"action": "deferred_without_submitting", "active_submissions": [11]}, {"ref": 72}]
        with patch.object(cycle, "submit", side_effect=values) as submit, patch("runner.time.sleep"):
            self.assertEqual(runner.submit_when_idle(Obj(), Path("unused"))["ref"], 72)
        self.assertEqual(submit.call_count, 2)

    def test_official_queue_timeout_does_not_force_a_submission(self):
        with patch.object(cycle, "submit", return_value={"action": "deferred_without_submitting"}) as submit:
            with patch("runner.time.monotonic", side_effect=[0, 10]):
                with self.assertRaises(TimeoutError):
                    runner.submit_when_idle(Obj(), Path("unused"), timeout_s=1)
        self.assertEqual(submit.call_count, 1)

    def test_gpu_score_pair_does_not_submit_after_failed_inference_validation(self):
        request = {"label": "ready-v2"}
        manifest = {"identity": {"line": "gpu", "runtime": {}, "session_timeout_seconds": 10}}
        with patch.object(cycle, "api_client"), patch.object(cycle, "verify", return_value=manifest):
            with patch.object(cycle, "require_comparable_execution"), patch.object(cycle, "require_connection_check"):
                with patch.object(cycle, "collect_output"), patch.object(cycle, "require_gpu_validation", side_effect=ValueError("bad inference")):
                    with patch.object(cycle, "submit") as submit:
                        with self.assertRaisesRegex(ValueError, "bad inference"):
                            runner.run_gpu_score_pair(request, Path("unused"))
        submit.assert_not_called()

    def test_cpu_baseline_error_prevents_candidate_submission(self):
        request = {"label": "baseline", "candidate_label": "probe64"}
        manifest = {"identity": {"line": "cpu", "runtime": {}, "session_timeout_seconds": 10}}
        with patch.object(cycle, "api_client"), patch.object(cycle, "verify", return_value=manifest):
            with patch.object(cycle, "require_comparable_execution"), patch.object(cycle, "require_connection_check"):
                with patch.object(runner, "wait_official_score", side_effect=ValueError("failed baseline")):
                    with patch.object(cycle, "submit") as submit:
                        with self.assertRaisesRegex(ValueError, "failed baseline"):
                            runner.run_cpu_pair(request, Path("unused"))
        submit.assert_not_called()

    def test_official_score_wait_accepts_zero_score(self):
        with patch.object(cycle, "observe_score", return_value={"status": "COMPLETE", "public_score": "0"}):
            self.assertEqual(runner.wait_official_score(Obj(), Path("unused"))["public_score"], "0")

    def test_official_score_error_stops_instead_of_submitting_candidate(self):
        with patch.object(cycle, "observe_score", return_value={"status": "ERROR", "public_score": ""}):
            with self.assertRaisesRegex(ValueError, "without a usable"):
                runner.wait_official_score(Obj(), Path("unused"))

    def test_official_score_timeout_keeps_existing_ref(self):
        with patch.object(cycle, "observe_score", return_value={"status": "PENDING", "public_score": ""}):
            with patch("runner.time.monotonic", side_effect=[0, 10]):
                with self.assertRaises(TimeoutError):
                    runner.wait_official_score(Obj(), Path("unused"), timeout_s=1)

    def test_failed_baseline_stops_pair_before_memory_start(self):
        request = {"stage": "gpu-pair", "profile": "gpu-baseline", "label": "ready-v2"}
        with patch.object(cycle, "api_client"), patch.object(runner, "run") as start:
            with patch.object(runner, "wait_gpu_terminal", side_effect=ValueError("failed baseline")):
                with self.assertRaisesRegex(ValueError, "failed baseline"):
                    runner.run_gpu_pair(request, Path("unused"))
        self.assertEqual(start.call_count, 1)
        self.assertEqual(start.call_args.args[0]["profile"], "gpu-baseline")

    def test_pair_retains_baseline_label_and_waits_for_both(self):
        request = {"stage": "gpu-pair", "profile": "gpu-baseline", "label": "ready-v2"}
        with patch.object(cycle, "api_client"), patch.object(runner, "run") as start:
            with patch.object(runner, "wait_gpu_terminal") as wait, patch.object(runner, "summary"):
                runner.run_gpu_pair(request, Path("unused"))
        self.assertEqual(wait.call_count, 2)
        self.assertEqual(start.call_args.args[0]["profile"], "gpu-memory")
        self.assertEqual(start.call_args.args[0]["label"], "ready-v2-memory")
        self.assertEqual(start.call_args.args[0]["baseline_label"], "ready-v2")

    def test_gpu_observation_timeout_does_not_relaunch(self):
        with patch.object(cycle, "observe_kernel", return_value={"status": "RUNNING"}):
            with patch("runner.time.monotonic", side_effect=[0, 10]):
                with self.assertRaises(TimeoutError):
                    runner.wait_gpu_terminal(Obj(), Path("unused"), timeout_s=1)

    def test_dead_model_cannot_pass_notebook_validation(self):
        with self.assertRaisesRegex(RuntimeError, "exited"):
            gpu_validation.validate_model_backend(Obj(poll=lambda: 1), "http://local/v1", "model", "unused")

    def test_model_readiness_timeout_is_not_success(self):
        with patch("time.monotonic", side_effect=[0, 20]):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                gpu_validation.validate_model_backend(Obj(poll=lambda: None), "http://local/v1", "model", "unused", timeout_s=10)

    def test_model_health_without_generation_is_rejected(self):
        health = Obj(status=200, __enter__=lambda s:s, __exit__=lambda *a:None)
        from contextlib import nullcontext
        with patch("urllib.request.urlopen", side_effect=[nullcontext(health), io.StringIO('{"choices":[{}],"usage":{"completion_tokens":0}}')]):
            with self.assertRaisesRegex(RuntimeError, "no completion"):
                gpu_validation.validate_model_backend(Obj(poll=lambda: None), "http://local/v1", "model", "unused")

    def test_ready_backend_and_real_game_action_are_required(self):
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "model-diagnostics.json"
            with patch("urllib.request.urlopen", side_effect=[nullcontext(Obj(status=200)), io.StringIO('{"choices":[{}],"usage":{"completion_tokens":3}}')]):
                gpu_validation.validate_model_backend(Obj(poll=lambda: None), "http://local/v1", "model", path)
            reset = Obj(action=Obj(id=Obj(name="RESET")), generated_tokens=0)
            action = Obj(action=Obj(id=Obj(name="ACTION1")), generated_tokens=20)
            with self.assertRaisesRegex(RuntimeError, "non-RESET"):
                gpu_validation.validate_game_inference([Obj(history=[reset], final_generated_tokens=0)], path)
            report = gpu_validation.validate_game_inference([Obj(history=[reset, action], final_generated_tokens=0)], path)
            self.assertTrue(report["passed"])
            self.assertEqual(report["non_reset_game_actions"], 1)
            self.assertEqual(report["game_generated_tokens"], 20)

    def test_cycle_rejects_missing_or_zero_token_gpu_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp)
            with self.assertRaisesRegex(ValueError, "Collect"):
                cycle.require_gpu_validation(bundle)
            cycle.save(bundle / "evidence/output.json", {})
            with self.assertRaisesRegex(ValueError, "lacks"):
                cycle.require_gpu_validation(bundle)
            cycle.save(bundle / "evidence/notebook-output/model-diagnostics.json", {"passed": True})
            with self.assertRaisesRegex(ValueError, "tokens"):
                cycle.require_gpu_validation(bundle)


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
            cycle.event(path, "public-smoke.json", passed=True, errors=[], official_zip_sha256=cycle.OFFICIAL_ZIP_SHA256, results=[
                {"candidate_id": cycle.verify(path)["candidate_id"], "official_loop_unchanged": True}])
        report = self.root / (name + "-connection.json")
        manifest = cycle.verify(path)
        cycle.save(report, {"passed": True, "checks": [{"passed": True, "name": "test fixture, not real verification"}],
                   "competition_zip_sha256": cycle.OFFICIAL_ZIP_SHA256, "gpu_source_zip_sha256": "fixture-source",
                   "cpu_profile_tested": profile, "notebook_code_sha256": {profile: manifest["identity"]["code_sha256"]}})
        cycle.attach_connection_check(path, report)
        return path

    def started(self):
        cycle.start(self.api, self.bundle)

    def baseline_import_fixture(self):
        self.started()
        cycle.event(self.bundle, "submission-receipt.json", ref=72)
        incoming = self.root / "incoming"
        root = self.root / "combined"
        source = incoming / "cpu-c8b/first"
        target = root / "cpu-c8b/first"
        shutil.copytree(self.bundle, source)
        shutil.copytree(self.bundle, target)
        return incoming, root, source, target

    def test_pair_baseline_import_retains_previous_copy_and_exact_receipts(self):
        incoming, root, source, target = self.baseline_import_fixture()
        (target / "evidence/submission-receipt.json").unlink()
        (target / "evidence/connection-check.json").unlink()
        (target / "evidence/prior-history.txt").write_text("retain this", encoding="utf-8")
        expected = cycle.verify(source)["candidate_id"]
        value = cycle.import_pair_baseline(root, incoming, "cpu-c8b", "first", expected, "100")
        archived = root / value["retained_prior_copy"]
        self.assertEqual((archived / "evidence/prior-history.txt").read_text(encoding="utf-8"), "retain this")
        self.assertEqual(cycle.receipt(target, "submission-receipt.json")["ref"], 72)
        cycle.require_connection_check(target)
        self.assertEqual(cycle.import_pair_baseline(root, incoming, "cpu-c8b", "first", expected, "100"), value)

    def test_pair_baseline_import_rejects_another_candidate_before_moving(self):
        incoming, root, source, target = self.baseline_import_fixture()
        with self.assertRaisesRegex(ValueError, "another candidate"):
            cycle.import_pair_baseline(root, incoming, "cpu-c8b", "first", "0" * 64, "100")
        self.assertTrue((target / "manifest.json").exists())
        self.assertFalse((root / "prior-imports").exists())

    def test_pair_baseline_import_rejects_conflicting_submission_refs(self):
        incoming, root, source, target = self.baseline_import_fixture()
        cycle.event(source, "submission-receipt.json", ref=73)
        with self.assertRaisesRegex(ValueError, "Conflicting"):
            cycle.import_pair_baseline(root, incoming, "cpu-c8b", "first", cycle.verify(source)["candidate_id"], "100")
        self.assertEqual(cycle.receipt(target, "submission-receipt.json")["ref"], 72)

    def rejected_submit_proof(self, status=400):
        self.started()
        value = cycle.receipt(self.bundle, "kernel-receipt.json")
        cycle.intent(self.bundle, "submission-intent.json", kernel=value["kernel"], version=value["version"], maximum_submit_calls=1)
        proof = self.root / "reviewed-rejection.json"
        cycle.save(proof, {"candidate_id": cycle.verify(self.bundle)["candidate_id"], "kernel": value["kernel"],
                          "version": value["version"], "status_code": status, "confirmed_http_rejection": True})
        return proof

    def test_reviewed_http400_allows_only_one_additional_submit(self):
        proof = self.rejected_submit_proof()
        old_intent = (self.bundle / "evidence/submission-intent.json").read_bytes()
        cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        result = cycle.submit(self.api, self.bundle)
        self.assertEqual(result["action"], "submitted_once_after_reviewed_rejection")
        self.assertEqual(old_intent, (self.bundle / "evidence/submission-intent.json").read_bytes())
        self.assertTrue((self.bundle / "evidence/submission-retry-intent.json").exists())
        cycle.submit(self.api, self.bundle)
        self.assertEqual(self.api.submits, 1)

    def test_unknown_or_wrong_candidate_rejection_cannot_be_authorized(self):
        proof = self.rejected_submit_proof(status=503)
        with self.assertRaisesRegex(ValueError, "reviewed HTTP 400"):
            cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        value = cycle.read(proof); value.update(status_code=400, candidate_id="other")
        cycle.save(proof, value)
        with self.assertRaisesRegex(ValueError, "reviewed HTTP 400"):
            cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        self.assertEqual(self.api.submits, 0)

    def test_pending_evaluation_prevents_rejection_recovery(self):
        proof = self.rejected_submit_proof()
        self.api.history.append(Obj(ref=11, description="other", status="PENDING"))
        with self.assertRaisesRegex(ValueError, "active official"):
            cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        self.assertEqual(self.api.submits, 0)

    def test_existing_marker_is_reconciled_without_retry(self):
        proof = self.rejected_submit_proof()
        self.api.history.append(Obj(ref=12, description=cycle.marker(self.bundle), status="PENDING"))
        result = cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        self.assertEqual(result["ref"], 12)
        self.assertEqual(self.api.submits, 0)
        self.assertFalse((self.bundle / "evidence/submission-retry-authorization.json").exists())

    def test_ambiguous_retry_never_sends_a_third_request(self):
        proof = self.rejected_submit_proof()
        cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        self.api.submit_timeout = True
        with self.assertRaises(TimeoutError):
            cycle.submit(self.api, self.bundle)
        self.api.history.clear()
        with self.assertRaisesRegex(ValueError, "Previous retry"):
            cycle.submit(self.api, self.bundle)
        with self.assertRaisesRegex(ValueError, "already attempted"):
            cycle.authorize_rejected_submission_retry(self.api, self.bundle, proof)
        self.assertEqual(self.api.submits, 1)

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

    def test_missing_connection_check_blocks_a_new_notebook(self):
        (self.bundle / "evidence/connection-check.json").unlink()
        with self.assertRaises(FileNotFoundError):
            self.started()
        self.assertEqual(self.api.pushes, 0)

    def test_connection_report_for_another_code_is_rejected(self):
        report = self.root / "first-connection.json"
        value = cycle.read(report)
        value["notebook_code_sha256"]["cpu-c8b"] = "different"
        cycle.save(report, value)
        with self.assertRaisesRegex(ValueError, "different notebook code"):
            cycle.attach_connection_check(self.bundle, report)

    def test_old_sdk_smoke_cannot_start_a_new_candidate(self):
        value = cycle.receipt(self.bundle, "public-smoke.json")
        value.pop("official_zip_sha256")
        cycle.save(self.bundle / "evidence/public-smoke.json", value)
        with self.assertRaisesRegex(ValueError, "official ZIP"):
            self.started()
        self.assertEqual(self.api.pushes, 0)

    def test_completed_official_zip_smoke_can_follow_identical_code(self):
        other = self.make_bundle("other")
        imported = cycle.import_cpu_smoke(other, self.bundle)
        self.assertEqual(imported["source_candidate_id"], cycle.verify(self.bundle)["candidate_id"])
        self.assertEqual(imported["results"][0]["candidate_id"], cycle.verify(other)["candidate_id"])

    def test_measured_smoke_cannot_follow_changed_code(self):
        nb = cycle.read(self.nb)
        nb["cells"][0]["source"] = "print('new policy')"
        cycle.save(self.nb, nb)
        other = self.make_bundle("other")
        with self.assertRaisesRegex(ValueError, "different notebook/config"):
            cycle.import_cpu_smoke(other, self.bundle)

    def test_source_bundle_drift_prevents_score_comparison(self):
        other = self.make_bundle("other")
        self.score(self.bundle, "0.01", 1)
        self.score(other, "0.02", 2)
        value = cycle.receipt(other, "connection-check.json")
        value["report"]["gpu_source_zip_sha256"] = "different-source"
        cycle.save(other / "evidence/connection-check.json", value)
        with self.assertRaisesRegex(ValueError, "input contents differ"):
            cycle.compare(self.bundle, other)

    def test_existing_output_directory_not_overwritten(self):
        with self.assertRaises(FileExistsError):
            self.make_bundle()

    def test_long_labels_keep_unique_compact_remote_names(self):
        path = self.make_bundle("a" * 36)
        value = cycle.verify(path)
        slug = value["kernel"].split("/", 1)[1]
        self.assertLessEqual(len(slug), 50)
        self.assertTrue(slug.endswith(value["candidate_id"][:12]))

    def test_http_push_error_retains_diagnostic_without_automatic_retry(self):
        def reject(*args, **kwargs):
            self.api.pushes += 1
            error = RuntimeError("rejected request")
            error.response = Obj(status_code=400, text='{"message":"fixture rejection"}')
            raise error
        self.api.kernels_push = reject
        with self.assertRaisesRegex(RuntimeError, "rejected request"):
            self.started()
        self.assertEqual(cycle.receipt(self.bundle, "push-http-error.json")["status_code"], 400)
        with self.assertRaisesRegex(ValueError, "Previous push"):
            self.started()
        self.assertEqual(self.api.pushes, 1)

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

    def test_another_pending_evaluation_defers_without_spending_a_submission(self):
        self.started()
        self.api.history.append(Obj(ref=99, description="another-candidate", status="PENDING"))
        value = cycle.submit(self.api, self.bundle)
        self.assertEqual(value["action"], "deferred_without_submitting")
        self.assertEqual(self.api.submits, 0)
        self.assertFalse((self.bundle / "evidence/submission-intent.json").exists())

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
