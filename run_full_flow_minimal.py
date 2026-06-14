import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import fitz
import requests
from dotenv import load_dotenv


RECOG_PATH = "/relisten/dictation/process/report-results"
PDF_TIMEOUT_SECONDS = 60
RECOG_TIMEOUT_SECONDS = 60
STUDY_TIMEOUT_SECONDS = 120
PREVIEW_CHARS = 500
DICOM_PATIENT_ID = "12345678A"
DICOM_ACCESSION_NUMBER = "TrasladoAsturias001"
DICOM_STUDY_DESCRIPTION = "RM_Rodilla_Derecha"
HUMANIZED_REPORT_FILENAME = "Informe_para_paciente_Recog.pdf"
DISCLAIMER_TEXT = (
    "Este informe es una explicación para facilitar la comprensión del paciente. "
    "No sustituye la valoración de un profesional sanitario ni modifica el "
    "informe médico original."
)
VALIDATION_NOTE = (
    "Case-specific consistency check for the provided knee MRI demo. "
    "Not a diagnostic validator."
)


CASE_CONCEPT_VARIANTS = {
    "rodilla": ["rodilla"],
    "menisco": ["menisco", "meniscal"],
    "ligamento": ["ligamento", "ligamentario", "ligamentaria"],
    "edema": ["edema"],
    "derrame": ["derrame", "liquido articular", "líquido articular"],
    "fisura / grieta": [
        "fisura",
        "grieta",
        "fractura fina",
        "pequena fractura",
        "pequeña fractura",
        "linea de fractura",
        "línea de fractura",
    ],
    "fractura": ["fractura"],
    "resonancia": ["resonancia", "rm", "mri"],
    "seguimiento / control": ["seguimiento", "control", "revision", "revisión"],
}

HIGH_RISK_CLINICAL_TERMS = {
    "tumor": ["tumor", "tumores"],
    "maligno": ["maligno", "maligna", "malignos", "malignas"],
    "cancer": ["cancer", "canceres"],
    "metastasis": ["metastasis"],
    "fractura": ["fractura", "fracturas"],
    "infeccion": ["infeccion", "infecciones"],
    "trombosis": ["trombosis"],
    "embolia": ["embolia", "embolias"],
    "cirugia urgente": ["cirugia urgente", "intervencion urgente"],
    "amputacion": ["amputacion", "amputaciones"],
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the minimal Reto Idonia end-to-end flow."
    )
    parser.add_argument(
        "--report",
        required=True,
        help="Path to the original report PDF.",
    )
    parser.add_argument(
        "--study",
        required=True,
        help="Path to the study ZIP or DICOM file.",
    )
    parser.add_argument(
        "--mode",
        choices=("mock", "cache", "real"),
        default="mock",
        help=(
            "Execution mode. Default: mock (no credentials and no network). "
            "Use cache with --recog-cache, or real with explicit confirmations."
        ),
    )
    parser.add_argument(
        "--recog-cache",
        help="Existing humanized PDF to reuse in cache mode without calling Recog.",
    )
    parser.add_argument(
        "--confirm-external-calls",
        action="store_true",
        help="Confirm that real mode may call external Idonia and Recog APIs.",
    )
    parser.add_argument(
        "--confirm-recog-call",
        action="store_true",
        help="Confirm the shared-resource Recog call. Required in real mode.",
    )
    parser.add_argument(
        "--allow-requires-review-upload",
        action="store_true",
        help=(
            "Allow uploading a report that failed the safety check. "
            "Use only after explicit clinical review."
        ),
    )
    parser.add_argument(
        "--show-access-details",
        action="store_true",
        help=(
            "Print Magic Link URL/code and PIN for local verification. "
            "Do not use this for public screenshots or videos."
        ),
    )
    return parser.parse_args()


def validate_execution_request(args):
    """Reject ambiguous or potentially costly execution requests."""
    if args.mode == "cache" and not args.recog_cache:
        raise RuntimeError("Cache mode requires --recog-cache <path>.")
    if args.mode != "cache" and args.recog_cache:
        raise RuntimeError("--recog-cache can only be used with --mode cache.")
    if args.mode == "real" and not args.confirm_external_calls:
        raise RuntimeError(
            "Real mode calls external APIs. Re-run with "
            "--confirm-external-calls after checking inputs and credentials."
        )
    if args.mode == "real" and not args.confirm_recog_call:
        raise RuntimeError(
            "Recog consumes shared generative-AI resources. Re-run real mode "
            "with --confirm-recog-call to authorize this single call."
        )
    if args.show_access_details and args.mode != "real":
        raise RuntimeError("--show-access-details is only available in real mode.")


def load_config():
    """Load the required Idonia and Recog settings from .env."""
    load_dotenv(override=True)

    config = {
        "idonia_base_url": os.getenv("IDONIA_BASE_URL"),
        "idonia_api_key": os.getenv("IDONIA_API_KEY"),
        "idonia_api_secret": os.getenv("IDONIA_API_SECRET"),
        "idonia_report_endpoint": os.getenv("IDONIA_REPORT_ENDPOINT"),
        "idonia_study_endpoint": os.getenv("IDONIA_STUDY_ENDPOINT"),
        "recog_base_url": os.getenv("RECOG_BASE_URL"),
        "recog_api_key": os.getenv("RECOG_API_KEY"),
    }

    missing = [
        name
        for name, value in (
            ("IDONIA_BASE_URL", config["idonia_base_url"]),
            ("IDONIA_API_KEY", config["idonia_api_key"]),
            ("IDONIA_API_SECRET", config["idonia_api_secret"]),
            ("IDONIA_REPORT_ENDPOINT", config["idonia_report_endpoint"]),
            ("IDONIA_STUDY_ENDPOINT", config["idonia_study_endpoint"]),
            ("RECOG_BASE_URL", config["recog_base_url"]),
            ("RECOG_API_KEY", config["recog_api_key"]),
        )
        if not value
    ]
    if missing:
        raise RuntimeError("Missing environment variables: " + ", ".join(missing))

    config["idonia_base_url"] = config["idonia_base_url"].rstrip("/")
    config["recog_base_url"] = config["recog_base_url"].rstrip("/")
    return config


def base64url_encode(data):
    """Encode JWT bytes with URL-safe base64 and no = padding."""
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def build_idonia_jwt(api_key, api_secret):
    """Generate the Idonia HS256 JWT using the manual's S2 secret handling."""
    if not api_secret.startswith("S2"):
        raise RuntimeError("IDONIA_API_SECRET must start with S2.")

    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": api_key,
        "iat": now - 300,
        "exp": now + 300,
    }

    encoded_header = base64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    encoded_payload = base64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{encoded_header}.{encoded_payload}".encode("ascii")

    encoded_secret = api_secret[2:]
    padding = "=" * (-len(encoded_secret) % 4)
    signing_key = base64.urlsafe_b64decode(encoded_secret + padding)

    signature = hmac.new(signing_key, signing_input, hashlib.sha256).digest()
    encoded_signature = base64url_encode(signature)
    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def redact(value, config, token=None):
    """Remove API keys, API secrets, and JWTs from printed or raised text."""
    text = str(value)
    replacements = [
        (config["idonia_api_key"], "[REDACTED_IDONIA_API_KEY]"),
        (config["idonia_api_secret"], "[REDACTED_IDONIA_API_SECRET]"),
        (config["recog_api_key"], "[REDACTED_RECOG_API_KEY]"),
        (token, "[REDACTED_JWT]"),
    ]
    for secret, label in replacements:
        if secret:
            text = text.replace(secret, label)
    return text


def extract_text_from_pdf(pdf_path):
    """Extract text from all pages of the original PDF report."""
    if not pdf_path.is_file():
        raise FileNotFoundError(f"Missing report PDF: {pdf_path}")

    text_parts = []
    with fitz.open(pdf_path) as document:
        for page in document:
            text_parts.append(page.get_text())

    extracted_text = "\n".join(text_parts).strip()
    if not extracted_text:
        raise RuntimeError(f"No text extracted from PDF: {pdf_path}")
    return extracted_text


def normalize_text(text):
    """Normalize case, accents, punctuation, and whitespace for safety checks."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    without_accents = "".join(
        character
        for character in decomposed
        if unicodedata.category(character) != "Mn"
    )
    words_only = re.sub(r"[^a-z0-9]+", " ", without_accents)
    return " ".join(words_only.split())


def contains_any_variant(text, variants):
    """Return True when any normalized variant appears in normalized text."""
    normalized_text = f" {normalize_text(text)} "
    return any(
        f" {normalize_text(variant)} " in normalized_text
        for variant in variants
    )


def has_patient_disclaimer(text):
    """Check for the three essential statements in the patient disclaimer."""
    normalized = normalize_text(text)
    return (
        "facilitar la comprension del paciente" in normalized
        and "no sustituye la valoracion de un profesional sanitario" in normalized
        and "ni modifica el informe medico original" in normalized
    )


def validate_humanized_report(original_text: str, humanized_text: str) -> dict:
    """Run a small case-specific consistency check for this knee MRI demo."""
    preserved_concepts = []
    missing_concepts = []
    new_clinical_terms = []

    for concept, variants in CASE_CONCEPT_VARIANTS.items():
        original_has_concept = contains_any_variant(original_text, variants)
        humanized_has_concept = contains_any_variant(humanized_text, variants)

        if original_has_concept and humanized_has_concept:
            preserved_concepts.append(concept)
        elif original_has_concept and not humanized_has_concept:
            missing_concepts.append(concept)

    for term, variants in HIGH_RISK_CLINICAL_TERMS.items():
        if (
            contains_any_variant(humanized_text, variants)
            and not contains_any_variant(original_text, variants)
        ):
            new_clinical_terms.append(term)

    disclaimer_present = has_patient_disclaimer(humanized_text)
    status = (
        "approved"
        if not missing_concepts and not new_clinical_terms and disclaimer_present
        else "requires_review"
    )
    return {
        "status": status,
        "missing_concepts": missing_concepts,
        "new_clinical_terms": new_clinical_terms,
        "has_disclaimer": disclaimer_present,
        "preserved_concepts": preserved_concepts,
        "original_text_chars": len(original_text),
        "humanized_text_chars": len(humanized_text),
        "note": VALIDATION_NOTE,
    }


def parse_returned_uuid(response):
    """Read Idonia's returned UUID from a JSON or text response."""
    try:
        body = response.json()
    except ValueError:
        body = response.text.strip()

    if isinstance(body, list) and body:
        return str(body[0])
    if isinstance(body, dict):
        for key in ("id", "uuid", "fileId"):
            if key in body:
                return str(body[key])
    return str(body)[:PREVIEW_CHARS]


def upload_to_idonia(config, token, file_path, endpoint, timeout_seconds):
    """Upload one report or study file to an Idonia /files endpoint."""
    if not file_path.is_file():
        raise FileNotFoundError(f"Missing upload file: {file_path}")

    url = f"{config['idonia_base_url']}/files/{endpoint}"
    headers = {"Authorization": "Bearer " + token}
    data = {
        "DICOMPatientID": DICOM_PATIENT_ID,
        "DICOMAccessionNumber": DICOM_ACCESSION_NUMBER,
        "DICOMStudyDescription": DICOM_STUDY_DESCRIPTION,
    }

    try:
        with file_path.open("rb") as upload_file:
            response = requests.post(
                url,
                headers=headers,
                data=data,
                files={"file": (file_path.name, upload_file)},
                timeout=timeout_seconds,
            )
    except requests.RequestException as error:
        raise RuntimeError(
            "Idonia upload request failed: " + redact(error, config, token)
        ) from error

    if response.status_code not in (200, 201):
        preview = redact(response.text[:PREVIEW_CHARS], config, token)
        raise RuntimeError(
            f"Idonia upload failed for {endpoint}. "
            f"HTTP {response.status_code}: {preview}"
        )

    return response.status_code, parse_returned_uuid(response)


def build_recog_output_path():
    """Build the stable, visible patient-report output path."""
    output_dir = Path("data") / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / HUMANIZED_REPORT_FILENAME


def build_raw_recog_output_path():
    """Build a temporary path for the unmodified Recog response."""
    output_dir = Path("data") / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir / "_recog_response_raw.pdf"


def prepare_patient_report(source_path, output_path=None):
    """Prepend a non-clinical disclaimer cover without editing generated content."""
    source_path = Path(source_path)
    if not source_path.is_file():
        raise FileNotFoundError(f"Missing humanized PDF: {source_path}")

    output_path = Path(output_path or build_recog_output_path())
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open() as final_document:
        cover = final_document.new_page()
        cover.insert_textbox(
            fitz.Rect(72, 90, 523, 300),
            "INFORME PARA PACIENTE\n\n" + DISCLAIMER_TEXT,
            fontsize=13,
            lineheight=1.4,
        )
        with fitz.open(source_path) as source_document:
            final_document.insert_pdf(source_document)
        if output_path.exists():
            output_path.unlink()
        final_document.save(output_path)

    return output_path


def call_recog(config, extracted_text):
    """Send report text to Recog and save the returned patient-friendly PDF."""
    endpoint = config["recog_base_url"] + RECOG_PATH
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": config["recog_api_key"],
    }
    body = {"dictationReport": extracted_text}

    try:
        response = requests.post(
            endpoint,
            headers=headers,
            json=body,
            timeout=RECOG_TIMEOUT_SECONDS,
        )
    except requests.RequestException as error:
        raise RuntimeError(
            "Recog request failed: " + redact(error, config)
        ) from error
    if not response.ok:
        preview = redact(response.text[:PREVIEW_CHARS], config)
        raise RuntimeError(f"Recog failed. HTTP {response.status_code}: {preview}")

    content_type = response.headers.get("content-type", "").lower()
    looks_like_pdf = response.content.startswith(b"%PDF")
    is_binary = "application/octet-stream" in content_type
    if "application/pdf" not in content_type and not looks_like_pdf and not is_binary:
        raise RuntimeError(
            "Recog did not return a PDF. "
            f"Content-Type was {content_type or 'missing'}."
        )

    output_path = build_raw_recog_output_path()
    output_path.write_bytes(response.content)
    return output_path


def parse_magic_link(response):
    """Extract Magic Link URL/code and PIN from the Idonia response."""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip(), ""

    # Idonia commonly returns a list with one Magic Link object.
    if isinstance(body, list) and body:
        first_item = body[0]
        if isinstance(first_item, dict):
            return first_item.get("URL", ""), first_item.get("PIN", "")
        return str(first_item)[:PREVIEW_CHARS], ""

    if isinstance(body, dict):
        return body.get("URL", ""), body.get("PIN", "")

    # Keep a short raw preview for unexpected response shapes.
    return str(body)[:PREVIEW_CHARS], ""


SENSITIVE_LOG_KEYS = {
    "api_key",
    "api_secret",
    "authorization",
    "jwt",
    "pin",
    "code",
    "url",
    "likely_final_url",
}


def sanitize_log_data(value, secrets=()):
    """Recursively redact forbidden keys and known secret values."""
    if isinstance(value, dict):
        sanitized = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_LOG_KEYS:
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = sanitize_log_data(item, secrets)
        return sanitized
    if isinstance(value, list):
        return [sanitize_log_data(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [sanitize_log_data(item, secrets) for item in value]
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(str(secret), "[REDACTED]")
        return redacted
    return value


def save_run_log(result: dict, secrets=()) -> Path:
    """Save a JSON trace of the run without API keys, JWTs, or secrets."""
    # Logs make it easier to audit which files and IDs belonged to a run.
    # Secrets are intentionally left out so the log can be shared more safely.
    log_dir = Path("data") / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = log_dir / f"{timestamp}_full_flow_log.json"
    log_path.write_text(
        json.dumps(
            sanitize_log_data(result, secrets),
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return log_path


def should_upload_humanized_report(validation_result, allow_requires_review=False):
    """Apply the default-deny clinical safety gate."""
    return (
        validation_result["status"] == "approved"
        or allow_requires_review
    )


def get_or_create_magic_link(config, token):
    """Retrieve an existing Magic Link, or create it when Idonia returns 204."""
    url = config["idonia_base_url"] + "/ml"
    route = f"{DICOM_PATIENT_ID}/{DICOM_ACCESSION_NUMBER}"
    headers = {"Authorization": "Bearer " + token}
    params = {"route": route}

    try:
        response = requests.get(
            url, headers=headers, params=params, timeout=PDF_TIMEOUT_SECONDS
        )
    except requests.RequestException as error:
        raise RuntimeError(
            "Magic Link GET request failed: " + redact(error, config, token)
        ) from error

    if response.status_code == 204:
        try:
            response = requests.put(
                url,
                headers=headers,
                params=params,
                timeout=PDF_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            raise RuntimeError(
                "Magic Link PUT request failed: " + redact(error, config, token)
            ) from error

    if response.status_code not in (200, 201):
        preview = redact(response.text[:PREVIEW_CHARS], config, token)
        raise RuntimeError(
            f"Magic Link failed. HTTP {response.status_code}: {preview}"
        )

    return parse_magic_link(response)


def main():
    print("Reto Idonia - Minimal End-to-End Flow")

    args = parse_args()
    validate_execution_request(args)
    report_path = Path(args.report)
    study_path = Path(args.study)
    if not report_path.is_file():
        raise FileNotFoundError(f"Missing report PDF: {report_path}")
    if not study_path.is_file():
        raise FileNotFoundError(f"Missing study file: {study_path}")

    extracted_text = extract_text_from_pdf(report_path)
    config = None
    token = None
    magic_url_or_code = ""
    magic_pin = ""

    if args.mode == "real":
        config = load_config()
        token = build_idonia_jwt(
            config["idonia_api_key"],
            config["idonia_api_secret"],
        )
        original_status, original_uuid = upload_to_idonia(
            config,
            token,
            report_path,
            config["idonia_report_endpoint"],
            PDF_TIMEOUT_SECONDS,
        )
        raw_recog_path = call_recog(config, extracted_text)
        try:
            recog_output_path = prepare_patient_report(raw_recog_path)
        finally:
            raw_recog_path.unlink(missing_ok=True)
    else:
        source_path = (
            Path(args.recog_cache)
            if args.mode == "cache"
            else report_path
        )
        recog_output_path = prepare_patient_report(source_path)
        original_status = "simulated"
        original_uuid = None

    humanized_text = extract_text_from_pdf(recog_output_path)

    validation_result = validate_humanized_report(extracted_text, humanized_text)

    print("\nClinical validation")
    print(f"status: {validation_result['status']}")
    print(
        "preserved concepts: "
        + (", ".join(validation_result["preserved_concepts"]) or "none")
    )
    print(
        "missing concepts: "
        + (", ".join(validation_result["missing_concepts"]) or "none")
    )
    print(
        "new clinical terms: "
        + (", ".join(validation_result["new_clinical_terms"]) or "none")
    )
    print(
        "patient disclaimer: "
        + ("present" if validation_result["has_disclaimer"] else "missing")
    )

    upload_allowed = should_upload_humanized_report(
        validation_result,
        args.allow_requires_review_upload,
    )
    if validation_result["status"] == "requires_review":
        print("[WARNING] Humanized report requires review before real clinical use.")
        if not upload_allowed:
            print("[BLOCKED] Humanized report upload blocked by the safety gate.")

    if args.mode == "real":
        if upload_allowed:
            humanized_status, humanized_uuid = upload_to_idonia(
                config,
                token,
                recog_output_path,
                config["idonia_report_endpoint"],
                PDF_TIMEOUT_SECONDS,
            )
        else:
            humanized_status = "blocked_requires_review"
            humanized_uuid = None

        study_status, study_uuid = upload_to_idonia(
            config,
            token,
            study_path,
            config["idonia_study_endpoint"],
            STUDY_TIMEOUT_SECONDS,
        )
        magic_url_or_code, magic_pin = get_or_create_magic_link(config, token)
    else:
        humanized_status = (
            "simulated"
            if upload_allowed
            else "blocked_requires_review"
        )
        humanized_uuid = None
        study_status = "simulated"
        study_uuid = None

    timestamp_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    run_log = {
        "run_id": run_id,
        "timestamp_utc": timestamp_utc,
        "mode": args.mode,
        "case": {
            "DICOMPatientID": DICOM_PATIENT_ID,
            "DICOMAccessionNumber": DICOM_ACCESSION_NUMBER,
            "DICOMStudyDescription": DICOM_STUDY_DESCRIPTION,
        },
        "original_report": {
            "path": str(report_path),
            "upload_status": original_status,
            "uuid": original_uuid,
        },
        "recog": {
            "api_called": args.mode == "real",
            "cache_used": args.mode == "cache",
            "output_path": str(recog_output_path),
            "output_pdf_size_bytes": recog_output_path.stat().st_size,
        },
        "humanized_report": {
            "visible_filename": HUMANIZED_REPORT_FILENAME,
            "upload_status": humanized_status,
            "uuid": humanized_uuid,
            "upload_blocked_by_safety_gate": not upload_allowed,
        },
        "study": {
            "path": str(study_path),
            "upload_status": study_status,
            "uuid": study_uuid,
        },
        "magic_link": {
            "magic_link_generated": bool(magic_url_or_code or magic_pin)
            if args.mode == "real"
            else True,
            "simulated": args.mode != "real",
            "magic_link_verified_manually": False,
            "access_details_redacted": True,
        },
        "validation": validation_result,
        "security_note": (
            "Secrets, JWTs, API keys, and Magic Link access details are "
            "intentionally excluded from this log."
        ),
    }
    secrets = ()
    if config:
        secrets = (
            config["idonia_api_key"],
            config["idonia_api_secret"],
            config["recog_api_key"],
            token,
            magic_url_or_code,
            magic_pin,
        )
    log_path = save_run_log(run_log, secrets)

    print("\nFinal summary")
    print(f"mode: {args.mode}")
    print(f"original report upload status: {original_status}")
    print(
        "original report UUID: "
        + (redact(original_uuid, config, token) if config else "not applicable")
    )
    print(f"Recog output path: {recog_output_path}")
    print(f"humanized report upload status: {humanized_status}")
    print(
        "humanized report UUID: "
        + (redact(humanized_uuid, config, token) if config else "not applicable")
    )
    print(f"study upload status: {study_status}")
    print(
        "study UUID: "
        + (redact(study_uuid, config, token) if config else "not applicable")
    )
    print(
        "Magic Link generated: "
        + (
            "yes"
            if args.mode != "real" or magic_url_or_code or magic_pin
            else "no"
        )
    )
    if args.show_access_details:
        print(
            "[WARNING] Access details are private. Do not record, publish, "
            "or commit this output."
        )
        print(f"Magic Link URL/code: {redact(magic_url_or_code, config, token)}")
        print(f"Magic Link PIN: {redact(magic_pin, config, token)}")
    else:
        print("Magic Link URL/code: [REDACTED]")
        print("Magic Link PIN: [REDACTED]")
    print(f"run log path: {log_path}")


if __name__ == "__main__":
    main()
