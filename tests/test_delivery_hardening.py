import argparse
import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import run_full_flow_minimal as flow


class DeliveryHardeningTests(unittest.TestCase):
    @staticmethod
    def pdf_document_mock(*page_texts):
        document = MagicMock()
        document.page_count = len(page_texts)
        pages = []
        for text in page_texts:
            page = Mock()
            page.get_text.return_value = text
            pages.append(page)
        document.__iter__.return_value = iter(pages)
        document.__enter__.return_value = document
        document.__exit__.return_value = False
        return document

    def test_dicom_tags_build_common_idonia_route(self):
        context = flow.build_idonia_context(
            {
                "PatientID": "REAL_PATIENT",
                "AccessionNumber": "REAL_ACCESSION",
                "StudyDescription": "REAL_STUDY",
            }
        )

        self.assertEqual(context["idonia_patient_id"], "REAL_PATIENT")
        self.assertEqual(context["idonia_accession_number"], "REAL_ACCESSION")
        self.assertEqual(context["idonia_study_description"], "REAL_STUDY")
        self.assertEqual(
            context["magic_link_route"],
            "REAL_PATIENT/REAL_ACCESSION",
        )
        self.assertEqual(context["fallback_fields"], [])

    def test_missing_dicom_tags_use_configured_fallbacks(self):
        context = flow.build_idonia_context(
            {
                "PatientID": "REAL_PATIENT",
                "AccessionNumber": "",
                "StudyDescription": None,
            }
        )

        self.assertEqual(context["idonia_patient_id"], "REAL_PATIENT")
        self.assertEqual(
            context["idonia_accession_number"],
            flow.DICOM_ACCESSION_NUMBER,
        )
        self.assertEqual(
            context["idonia_study_description"],
            flow.DICOM_STUDY_DESCRIPTION,
        )
        self.assertEqual(
            context["magic_link_route"],
            f"REAL_PATIENT/{flow.DICOM_ACCESSION_NUMBER}",
        )
        self.assertEqual(
            context["fallback_fields"],
            ["idonia_accession_number", "idonia_study_description"],
        )

    def test_dicom_derived_context_summary_does_not_expose_phi(self):
        context = flow.build_idonia_context(
            {
                "PatientID": "PRIVATE_PATIENT",
                "AccessionNumber": "PRIVATE_ACCESSION",
                "StudyDescription": "PRIVATE_STUDY",
            }
        )

        serialized = json.dumps(flow.build_safe_idonia_context_summary(context))

        self.assertNotIn("PRIVATE_PATIENT", serialized)
        self.assertNotIn("PRIVATE_ACCESSION", serialized)
        self.assertNotIn("PRIVATE_STUDY", serialized)
        self.assertIn("[derived patient]/[derived accession]", serialized)

    def test_extract_dicom_tags_reads_required_fields(self):
        dataset = SimpleNamespace(
            PatientID="REAL_PATIENT",
            AccessionNumber="REAL_ACCESSION",
            StudyDescription="REAL_STUDY",
        )
        fake_pydicom = SimpleNamespace(dcmread=Mock(return_value=dataset))

        with patch.dict(sys.modules, {"pydicom": fake_pydicom}), patch.object(
            flow.zipfile,
            "is_zipfile",
            return_value=False,
        ):
            tags = flow.extract_dicom_tags(Path("study.dcm"))

        self.assertEqual(
            tags,
            {
                "PatientID": "REAL_PATIENT",
                "AccessionNumber": "REAL_ACCESSION",
                "StudyDescription": "REAL_STUDY",
            },
        )
        fake_pydicom.dcmread.assert_called_once_with(
            Path("study.dcm"),
            stop_before_pixels=True,
            specific_tags=["PatientID", "AccessionNumber", "StudyDescription"],
        )

    def test_extract_dicom_tags_uses_first_valid_dicom_in_zip(self):
        invalid_member = Mock()
        invalid_member.is_dir.return_value = False
        valid_member = Mock()
        valid_member.is_dir.return_value = False
        archive = Mock()
        archive.__enter__ = Mock(return_value=archive)
        archive.__exit__ = Mock(return_value=False)
        archive.infolist.return_value = [invalid_member, valid_member]
        archive.open.side_effect = [io.BytesIO(b"invalid"), io.BytesIO(b"dicom")]
        dataset = SimpleNamespace(
            PatientID="ZIP_PATIENT",
            AccessionNumber="ZIP_ACCESSION",
            StudyDescription="ZIP_STUDY",
        )
        fake_pydicom = SimpleNamespace(
            dcmread=Mock(side_effect=(ValueError("invalid"), dataset))
        )

        with patch.dict(sys.modules, {"pydicom": fake_pydicom}), patch.object(
            flow.zipfile,
            "is_zipfile",
            return_value=True,
        ), patch.object(
            flow.zipfile,
            "ZipFile",
            return_value=archive,
        ):
            tags = flow.extract_dicom_tags(Path("study.zip"))

        self.assertEqual(tags["PatientID"], "ZIP_PATIENT")
        self.assertEqual(tags["AccessionNumber"], "ZIP_ACCESSION")
        self.assertEqual(tags["StudyDescription"], "ZIP_STUDY")
        self.assertEqual(fake_pydicom.dcmread.call_count, 2)

    def test_context_only_mode_uses_no_credentials_pdf_or_network(self):
        args = argparse.Namespace(
            report=None,
            study="study.dcm",
            mode="real",
            recog_cache=None,
            confirm_external_calls=False,
            confirm_recog_call=False,
            allow_requires_review_upload=False,
            derive_idonia_context_from_dicom=True,
            print_idonia_context_only=True,
            show_access_details=False,
        )
        tags = {
            "PatientID": "PRIVATE_PATIENT",
            "AccessionNumber": "PRIVATE_ACCESSION",
            "StudyDescription": "PRIVATE_STUDY",
        }

        with patch.object(flow, "parse_args", return_value=args), patch.object(
            Path,
            "is_file",
            return_value=True,
        ), patch.object(
            flow,
            "extract_dicom_tags",
            return_value=tags,
        ), patch.object(
            flow,
            "load_config",
            side_effect=AssertionError("context-only must not load credentials"),
        ), patch.object(
            flow,
            "extract_text_from_pdf",
            side_effect=AssertionError("context-only must not process PDFs"),
        ), patch.object(
            flow.requests,
            "post",
            side_effect=AssertionError("context-only must not call network"),
        ), patch.object(
            flow.requests,
            "get",
            side_effect=AssertionError("context-only must not call network"),
        ), patch.object(
            flow.requests,
            "put",
            side_effect=AssertionError("context-only must not call network"),
        ), patch("builtins.print") as print_mock:
            flow.main()

        printed = " ".join(
            str(call.args[0]) for call in print_mock.call_args_list if call.args
        )
        self.assertNotIn("PRIVATE_PATIENT", printed)
        self.assertNotIn("PRIVATE_ACCESSION", printed)
        self.assertNotIn("PRIVATE_STUDY", printed)
        self.assertIn("[derived from DICOM]", printed)

    def test_disclaimer_presence_controls_whether_cover_is_needed(self):
        self.assertFalse(
            flow.needs_patient_disclaimer(
                "INFORME PARA PACIENTE\n" + flow.DISCLAIMER_TEXT
            )
        )
        self.assertFalse(
            flow.needs_patient_disclaimer(
                "Aviso importante\n" + flow.PATIENT_NOTICE_TEXT
            )
        )
        self.assertTrue(
            flow.needs_patient_disclaimer("Explicación clínica sin aviso.")
        )

    def test_has_patient_disclaimer_recognizes_new_wording(self):
        self.assertTrue(
            flow.has_patient_disclaimer(
                "Aviso importante\n" + flow.PATIENT_NOTICE_TEXT
            )
        )

    def test_prepare_patient_report_does_not_duplicate_new_final_notice(self):
        source = Path("cached.pdf")
        output = Path("final.pdf")
        source_document = self.pdf_document_mock(
            "Contenido clínico.",
            "Aviso importante\n" + flow.PATIENT_NOTICE_TEXT,
        )

        with patch.object(
            Path,
            "is_file",
            return_value=True,
        ), patch.object(
            flow.shutil,
            "copyfile",
        ) as copy_mock, patch.object(
            flow.fitz,
            "open",
            return_value=source_document,
        ):
            result = flow.prepare_patient_report(source, output)

        self.assertEqual(result, output)
        copy_mock.assert_called_once_with(source, output)

    def test_prepare_patient_report_appends_notice_after_clinical_content(self):
        source = Path("cached.pdf")
        output = Path("final.pdf")
        inspected_document = self.pdf_document_mock(
            "Resonancia de rodilla sin hallazgos."
        )
        final_document = MagicMock()
        final_document.__enter__.return_value = final_document
        final_document.tobytes.return_value = b"%PDF-final"
        notice_page = final_document.new_page.return_value
        source_document = self.pdf_document_mock("Contenido clínico.")

        with patch.object(
            Path,
            "is_file",
            return_value=True,
        ), patch.object(
            Path,
            "exists",
            return_value=False,
        ), patch.object(
            Path,
            "write_bytes",
        ) as write_mock, patch.object(
            flow.fitz,
            "open",
            side_effect=(inspected_document, final_document, source_document),
        ):
            result = flow.prepare_patient_report(source, output)

        self.assertEqual(result, output)
        final_document.insert_pdf.assert_called_once_with(
            source_document,
            from_page=0,
        )
        final_document.new_page.assert_called_once_with()
        notice_page.draw_rect.assert_called_once()
        self.assertEqual(notice_page.insert_textbox.call_count, 2)
        inserted_text = " ".join(
            call.args[1] for call in notice_page.insert_textbox.call_args_list
        )
        self.assertIn("Aviso importante", inserted_text)
        self.assertIn(flow.PATIENT_NOTICE_TEXT, inserted_text)
        write_mock.assert_called_once_with(b"%PDF-final")

        method_order = [
            call[0]
            for call in final_document.method_calls
            if call[0] in {"insert_pdf", "new_page"}
        ]
        self.assertEqual(method_order, ["insert_pdf", "new_page"])

    def test_prepare_patient_report_replaces_legacy_cover_with_final_notice(self):
        source = Path("cached.pdf")
        output = Path("final.pdf")
        legacy_cover = "INFORME PARA PACIENTE\n" + flow.DISCLAIMER_TEXT
        inspected_document = self.pdf_document_mock(
            legacy_cover,
            "Informe de resultados. Resonancia de rodilla.",
        )
        final_document = MagicMock()
        final_document.__enter__.return_value = final_document
        final_document.tobytes.return_value = b"%PDF-final"
        source_document = self.pdf_document_mock(
            legacy_cover,
            "Informe de resultados. Resonancia de rodilla.",
        )

        with patch.object(
            Path,
            "is_file",
            return_value=True,
        ), patch.object(
            Path,
            "exists",
            return_value=False,
        ), patch.object(
            Path,
            "write_bytes",
        ), patch.object(
            flow.fitz,
            "open",
            side_effect=(inspected_document, final_document, source_document),
        ):
            flow.prepare_patient_report(source, output)

        final_document.insert_pdf.assert_called_once_with(
            source_document,
            from_page=1,
        )
        final_document.new_page.assert_called_once_with()

    def test_prepare_patient_report_keeps_clinical_first_page(self):
        source = Path("cached.pdf")
        output = Path("final.pdf")
        clinical_first_page = (
            "INFORME PARA PACIENTE\n"
            + flow.DISCLAIMER_TEXT
            + "\nInforme de resultados. Resonancia de rodilla."
        )
        inspected_document = self.pdf_document_mock(clinical_first_page)

        with patch.object(
            Path,
            "is_file",
            return_value=True,
        ), patch.object(
            flow.shutil,
            "copyfile",
        ) as copy_mock, patch.object(
            flow.fitz,
            "open",
            return_value=inspected_document,
        ):
            flow.prepare_patient_report(source, output)

        copy_mock.assert_called_once_with(source, output)

    def test_validation_preserves_meniscus_across_plural(self):
        original = "La resonancia de rodilla muestra el menisco conservado."
        humanized = (
            "La resonancia de rodilla muestra los meniscos conservados. "
            + flow.DISCLAIMER_TEXT
        )

        result = flow.validate_humanized_report(original, humanized)

        self.assertNotIn("menisco", result["missing_concepts"])
        self.assertIn("menisco", result["preserved_concepts"])

    def test_validation_preserves_effusion_as_fluid_accumulation(self):
        original = "Resonancia de rodilla sin derrame."
        humanized = (
            "La resonancia de rodilla indica que no hay acumulación de líquido "
            "en la articulación. "
            + flow.DISCLAIMER_TEXT
        )

        result = flow.validate_humanized_report(original, humanized)

        concept = "derrame / liquido articular"
        self.assertNotIn(concept, result["missing_concepts"])
        self.assertIn(concept, result["preserved_concepts"])

    def test_validation_preserves_crack_as_fissure(self):
        original = "La resonancia de rodilla muestra una grieta pequeña."
        humanized = (
            "La resonancia de rodilla muestra fisuras pequeñas. "
            + flow.DISCLAIMER_TEXT
        )

        result = flow.validate_humanized_report(original, humanized)

        self.assertNotIn("fisura / grieta", result["missing_concepts"])
        self.assertIn("fisura / grieta", result["preserved_concepts"])

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
            derive_idonia_context_from_dicom=False,
            print_idonia_context_only=False,
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
            report="report.pdf",
            mode="real",
            recog_cache=None,
            confirm_external_calls=True,
            confirm_recog_call=False,
            show_access_details=False,
        )

        with self.assertRaisesRegex(RuntimeError, "shared generative-AI"):
            flow.validate_execution_request(args)

    def test_real_mode_without_cache_requires_external_confirmation(self):
        args = argparse.Namespace(
            report="report.pdf",
            mode="real",
            recog_cache=None,
            confirm_external_calls=False,
            confirm_recog_call=True,
            show_access_details=False,
        )

        with self.assertRaisesRegex(RuntimeError, "external APIs"):
            flow.validate_execution_request(args)

    def test_real_mode_with_recog_cache_does_not_require_recog_confirmation(self):
        args = argparse.Namespace(
            report="report.pdf",
            mode="real",
            recog_cache="cached.pdf",
            confirm_external_calls=True,
            confirm_recog_call=False,
            show_access_details=False,
        )

        flow.validate_execution_request(args)

    def test_real_mode_with_recog_cache_requires_external_confirmation(self):
        args = argparse.Namespace(
            report="report.pdf",
            mode="real",
            recog_cache="cached.pdf",
            confirm_external_calls=False,
            confirm_recog_call=False,
            show_access_details=False,
        )

        with self.assertRaisesRegex(RuntimeError, "external APIs"):
            flow.validate_execution_request(args)

    def test_real_mode_with_recog_cache_skips_recog_call(self):
        args = argparse.Namespace(
            report="report.pdf",
            study="study.zip",
            mode="real",
            recog_cache="cached.pdf",
            confirm_external_calls=True,
            confirm_recog_call=False,
            allow_requires_review_upload=False,
            derive_idonia_context_from_dicom=False,
            print_idonia_context_only=False,
            show_access_details=False,
        )
        output = Path(flow.HUMANIZED_REPORT_FILENAME)
        original = "RM de rodilla sin hallazgos."
        humanized = original + " " + flow.DISCLAIMER_TEXT
        config = {
            "idonia_api_key": "key",
            "idonia_api_secret": "secret",
            "idonia_report_endpoint": "/report",
            "idonia_study_endpoint": "/study",
        }

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
            "load_config",
            return_value=config,
        ) as load_config, patch.object(
            flow,
            "build_idonia_jwt",
            return_value="token",
        ), patch.object(
            flow,
            "upload_to_idonia",
            return_value=("uploaded", "uuid"),
        ) as upload_mock, patch.object(
            flow,
            "prepare_patient_report",
            return_value=output,
        ) as prepare_report, patch.object(
            flow,
            "call_recog",
            side_effect=AssertionError("cached real mode must not call Recog"),
        ), patch.object(
            flow,
            "get_or_create_magic_link",
            return_value=("", ""),
        ) as magic_link_mock, patch.object(
            flow,
            "save_run_log",
            return_value=Path("safe-log.json"),
        ) as save_log_mock, patch("builtins.print"):
            flow.main()

        load_config.assert_called_once_with(require_recog=False)
        prepare_report.assert_called_once_with(Path("cached.pdf"))
        self.assertEqual(upload_mock.call_count, 3)

        upload_contexts = [call.args[5] for call in upload_mock.call_args_list]
        self.assertTrue(
            all(context == upload_contexts[0] for context in upload_contexts)
        )
        self.assertEqual(
            upload_contexts[0]["magic_link_route"],
            (
                upload_contexts[0]["idonia_patient_id"]
                + "/"
                + upload_contexts[0]["idonia_accession_number"]
            ),
        )
        self.assertEqual(
            upload_mock.call_args_list[1].kwargs["visible_filename"],
            flow.HUMANIZED_REPORT_FILENAME,
        )
        magic_link_mock.assert_called_once_with(
            config,
            "token",
            upload_contexts[0],
        )

        run_log = save_log_mock.call_args.args[0]
        serialized_log = json.dumps(run_log)
        self.assertEqual(run_log["case"], upload_contexts[0])
        self.assertNotIn("pin", serialized_log.lower())
        self.assertNotIn("url", serialized_log.lower())
        self.assertNotIn("code", serialized_log.lower())

    def test_magic_link_uses_shared_container_route(self):
        context = flow.build_idonia_context()
        response = Mock(status_code=200)
        response.json.return_value = [{}]
        config = {
            "idonia_base_url": "https://idonia.invalid",
            "idonia_api_key": "key",
            "idonia_api_secret": "secret",
        }

        with patch.object(
            flow.requests,
            "get",
            return_value=response,
        ) as get_mock, patch.object(
            flow.requests,
            "put",
            side_effect=AssertionError("existing link must not be recreated"),
        ):
            flow.get_or_create_magic_link(config, "token", context)

        self.assertEqual(
            get_mock.call_args.kwargs["params"],
            {"route": context["magic_link_route"]},
        )
        self.assertNotIn(flow.HUMANIZED_REPORT_FILENAME, context["magic_link_route"])


if __name__ == "__main__":
    unittest.main()
