# Architecture Diagram

Minimal current flow for the Reto Idonia hackathon delivery.

```mermaid
flowchart LR
    A[Original radiology report PDF] --> B[run_full_flow_minimal.py]
    C[RM study ZIP or DICOM file] --> B

    B --> D[Generate Idonia JWT]
    D --> E[Upload original report to Idonia reports endpoint]

    B --> F[Extract PDF text with PyMuPDF]
    F --> G[Send report text to Recog]
    G --> H[Save humanized PDF in data/output]

    H --> I[Upload humanized report to Idonia reports endpoint]
    C --> J[Upload RM study to Idonia DICOM endpoint]

    E --> K[Get or create Idonia Magic Link]
    I --> K
    J --> K
    K --> L[Demo access URL and PIN]
```

Notes:

- Idonia calls use JWT Bearer authentication.
- Recog calls use `X-API-Key`.
- Generated PDFs and medical data stay under ignored local folders.
