import argparse
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_full_flow_minimal as flow


class DeliveryHardeningTests(unittest.TestCase):
    def test_log_sanitizer_redacts_keys_and_known_values(self):
        secret = "private-test-value"
        source = {
            "api_key": secret,
            "nested": {
                "pin": "1234",
                "message": f"token={secret}",
            },
            "magic_link_generated": True,
        }

        sanitized = flow.sanitize_log_data(source, secrets=(secret,))
        serialized = json.dumps(sanitized)

        self.assertNotIn(secret, serialized)
        self.assertNotIn("1234", serialized)
        self.assertEqual(sanitized["api_key"], "[REDACTED]")
        self.assertEqual(sanitized["nested"]["pin"], "[REDACTED]")
        self.assertTrue(sanitized["magic_link_generated"])

    def test_validation_detects_new_high_risk_terms(self):
        original = "Resonancia de rodilla sin hallazgos de alarma."
        humanized = (
            "La resonancia de rodilla muestra un tumor maligno. "
            + flow.DISCLAIMER_TEXT
        )

        result = flow.validate_humanized_report(original, humanized)

        self.assertEqual(result["status"], "requires_review")
        self.assertIn("tumor", result["new_clinical_terms"])
        self.assertIn("maligno", result["new_clinical_terms"])
        self.assertTrue(result["has_disclaimer"])

    def test_requires_review_is_blocked_by_default(self):
        validation = {
            "status": "requires_review",
            "missing_concepts": [],
            "new_clinical_terms": ["tumor"],
            "has_disclaimer": True,
        }

        self.assertFalse(flow.should_upload_humanized_report(validation))
        self.assertTrue(
            flow.should_upload_humanized_report(
                validation,
                allow_requires_review=True,
            )
        )

    def test_mock_mode_needs_no_config_or_network(self):
        args = argparse.Namespace(
            report="report.pdf",
            study="study.zip",
            mode="mock",
            recog_cache=None,
            confirm_external_calls=False,
            confirm_recog_call=False,
            allow_requires_review_upload=False,
            show_access_details=False,
        )
        output = Path(flow.HUMANIZED_REPORT_FILENAME)
        original = "RM de rodilla sin hallazgos."
        humanized = original + " " + flow.DISCLAIMER_TEXT

        with patch.object(flow, "parse_args", return_value=args), patch.object(
            Path,
            "is_file",
            return_value=True,
        ), patch.object(
            Path,
            "stat",
            return_value=SimpleNamespace(st_size=123),
        ), patch.object(
            flow,
            "extract_text_from_pdf",
            side_effect=(original, humanized),
        ), patch.object(
            flow,
            "prepare_patient_report",
            return_value=output,
        ), patch.object(
            flow,
            "save_run_log",
            return_value=Path("safe-log.json"),
        ), patch.object(
            flow,
            "load_config",
            side_effect=AssertionError("mock must not load credentials"),
        ), patch.object(
            flow.requests,
            "post",
            side_effect=AssertionError("mock must not call the network"),
        ), patch.object(
            flow.requests,
            "get",
            side_effect=AssertionError("mock must not call the network"),
        ), patch.object(
            flow.requests,
            "put",
            side_effect=AssertionError("mock must not call the network"),
        ), patch("builtins.print"):
            flow.main()

    def test_real_mode_requires_both_confirmations(self):
        args = argparse.Namespace(
            mode="real",
            recog_cache=None,
            confirm_external_calls=True,
            confirm_recog_call=False,
            show_access_details=False,
        )

        with self.assertRaisesRegex(RuntimeError, "shared generative-AI"):
            flow.validate_execution_request(args)


if __name__ == "__main__":
    unittest.main()
