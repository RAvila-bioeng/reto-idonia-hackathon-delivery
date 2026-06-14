# Demo Evidence Template

Use this file as a checklist when recording the final demo evidence. Do not add
API keys, JWTs, PINs, secrets, medical identifiers beyond the demo case, or raw
medical documents.

## Execution

- Execution date:
- Operator:
- Command used:

```powershell
python run_full_flow_minimal.py --report ... --study ...
```

## Results

- Original report upload status:
- Original report UUID:
- Recog output generated:
- Recog output path:
- Humanized report upload status:
- Humanized report UUID:
- Study upload status:
- Study UUID:
- Magic Link manually verified: yes/no

## Screenshots To Capture Later

- Terminal final summary with secrets redacted.
- Idonia viewer opening the Magic Link.
- Original report visible in Idonia.
- Humanized report visible in Idonia.
- RM study visible in Idonia.
- Patient-friendly Recog PDF preview.

## Notes

- Keep screenshots free of API keys, JWTs, secrets, and unnecessary personal
  data.
- Redact Magic Link URL/code and PIN in any screenshots used for public
  delivery if they are visible.
- Do not attach generated PDFs or medical data to the repository.
