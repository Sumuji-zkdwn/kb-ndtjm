import importlib.util
import hashlib
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("bounded_runner", HERE / "runner.py")
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
REQUEST = json.loads((HERE / "request.json").read_text(encoding="utf-8"))


class DispatcherTests(unittest.TestCase):
    def test_valid_payload_is_private_and_has_no_competition(self):
        path, entry = r.validate(REQUEST)
        self.assertTrue(path.is_file())
        meta = r.metadata(REQUEST, entry)
        self.assertTrue(meta["is_private"])
        self.assertFalse(meta["enable_internet"])
        self.assertFalse(meta["enable_gpu"])
        self.assertEqual(meta["competition_sources"], [])

    def test_rejects_unknown_input_and_modified_source_hash(self):
        for changed in ({**REQUEST, "kind": "arbitrary"},
                        {**REQUEST, "id": "../oops"},
                        {**REQUEST, "source_sha256": "0" * 64},
                        {**REQUEST, "competition_sources": ["x"]}):
            with self.assertRaises(r.DispatchError):
                r.validate(changed)

    def test_preflight_does_not_treat_403_or_errors_as_absence(self):
        self.assertEqual(r.classify(1, "", "HTTP 403"), "unknown")
        self.assertEqual(r.classify(1, "", "network error"), "unknown")
        self.assertEqual(r.classify(1, "", "HTTP 404"), "absent")
        self.assertEqual(r.classify(0, 'status "KernelWorkerStatus.COMPLETE"', ""), "complete")

    def test_redacted_diagnostic_does_not_echo_error(self):
        raw = "Permission 'kernels.get' was denied TEST_ONLY_SECRET"
        self.assertEqual(r.diagnostic(1, "", raw),
                         {"return_code": 1, "category": "permission_or_missing_ambiguous"})
        self.assertNotIn("TEST_ONLY_SECRET", str(r.diagnostic(1, "", raw)))

    def test_diagnostic_mode_never_uploads_even_on_404(self):
        responses = [(0, 'status "COMPLETE"', ""), (1, "", "HTTP 404")]
        with patch.dict(os.environ, {"KAGGLE_API_TOKEN": "TEST_ONLY", "KAGGLE_DIAGNOSTIC_ONLY": "1"}), \
             patch.object(r, "call", side_effect=responses) as fake:
            r.main()
            self.assertEqual([c.args[0][1] for c in fake.call_args_list], ["status", "status"])

    def test_ambiguous_or_existing_status_never_pushes(self):
        for response in ((1, "", "HTTP 403"), (0, 'status "COMPLETE"', "")):
            with self.subTest(response=response), patch.dict(os.environ, {"KAGGLE_API_TOKEN": "TEST_ONLY"}), \
                 patch.object(r, "call", side_effect=[(0, 'status "COMPLETE"', ""), response]) as fake:
                with self.assertRaises(r.DispatchError):
                    r.main()
                self.assertEqual(fake.call_count, 2)
                self.assertTrue(all(c.args[0][0:2] == ["kernels", "status"] for c in fake.call_args_list))

    def test_inaccessible_control_never_pushes_even_if_target_404(self):
        with patch.dict(os.environ, {"KAGGLE_API_TOKEN": "TEST_ONLY"}), \
             patch.object(r, "call", side_effect=[(1, "", "HTTP 403"), (1, "", "HTTP 404")]) as fake:
            with self.assertRaises(r.DispatchError):
                r.main()
            self.assertEqual(fake.call_count, 2)

    def test_positive_synthetic_control_pushes_once_and_polls_complete(self):
        replies = [(0, 'status "COMPLETE"', ""), (1, "", "HTTP 404"),
                   (0, "pushed", ""), (0, 'status "COMPLETE"', "")]
        with patch.dict(os.environ, {"KAGGLE_API_TOKEN": "TEST_ONLY"}), \
             patch.object(r, "call", side_effect=replies) as fake, patch.object(r.time, "sleep"):
            r.main()
        self.assertEqual([c.args[0][1] for c in fake.call_args_list], ["status", "status", "push", "status"])

    def test_failed_push_is_not_retried(self):
        replies = [(0, 'status "COMPLETE"', ""), (1, "", "HTTP 404"), (1, "", "connection lost")]
        with patch.dict(os.environ, {"KAGGLE_API_TOKEN": "TEST_ONLY"}), \
             patch.object(r, "call", side_effect=replies) as fake:
            with self.assertRaisesRegex(r.DispatchError, "uncertain"):
                r.main()
        self.assertEqual(fake.call_count, 3)


if __name__ == "__main__":
    unittest.main()
