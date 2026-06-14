# Reto Idonia - Interoperabilidad y humanización de información médica

Prototipo del I Hackathon IA en Biomedicina para compartir un estudio médico,
el informe original y una explicación comprensible para el paciente mediante
Idonia y Recog.

El entry point principal es `run_full_flow_minimal.py`.

## Flujo

1. Recibir un informe PDF y un estudio DICOM/ZIP de prueba.
2. Derivar de los tags DICOM el contexto común de Idonia.
3. Subir o simular la subida del informe original a Idonia.
4. Extraer el texto con PyMuPDF.
5. Generar, reutilizar o simular el PDF humanizado de Recog.
6. Garantizar que el disclaimer aparezca una sola vez.
7. Validar conceptos críticos, términos clínicos nuevos y disclaimer.
8. Subir el archivo como `Informe_para_paciente_Recog.pdf` solo si pasa la
   validación, salvo autorización explícita tras revisión.
9. Subir o simular el estudio y generar el Magic Link sobre la ruta común
   `<PatientID>/<AccessionNumber>`.

Cuando la API no ofrece una categoría específica para "Informe para paciente",
la identificación se garantiza mediante el nombre visible
`Informe_para_paciente_Recog.pdf`.

## Instalación

Requiere Python 3.11 o superior.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip check
```

Dependencias principales:

- `pydicom`: lectura de `PatientID`, `AccessionNumber` y `StudyDescription`.
- `PyMuPDF` (`pymupdf`): lectura y composición de PDFs.
- `reportlab`: soporte de generación documental.
- `requests`: llamadas HTTP a Idonia y Recog.
- `python-dotenv`: carga local y controlada de configuración.
- `PyJWT`: soporte relacionado con autenticación JWT.

## Modos de ejecución

### Mock seguro, por defecto

No carga credenciales ni realiza llamadas a Idonia o Recog. Usa el informe
original como contenido simulado, garantiza un único disclaimer, ejecuta la
validación y genera un log de evidencia offline.

```powershell
python run_full_flow_minimal.py `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

### Cache de Recog

Reutiliza un PDF ya generado. Tampoco carga credenciales ni realiza llamadas
externas. Es el modo recomendado para la demostración segura:

```powershell
python run_full_flow_minimal.py `
  --mode cache `
  --derive-idonia-context-from-dicom `
  --recog-cache "data\cache\recog_humanizado.pdf" `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

### Ejecución real protegida

El modo real conserva la integración existente, pero exige confirmar tanto las
llamadas externas como el consumo de recursos compartidos de Recog:

```powershell
python run_full_flow_minimal.py `
  --mode real `
  --confirm-external-calls `
  --confirm-recog-call `
  --derive-idonia-context-from-dicom `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

### Diagnóstico de contexto sin red

Lee `PatientID`, `AccessionNumber` y `StudyDescription` del primer DICOM válido
del archivo o ZIP. No carga credenciales, genera PDFs ni realiza llamadas:

```powershell
python run_full_flow_minimal.py `
  --print-idonia-context-only `
  --derive-idonia-context-from-dicom `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

Los identificadores derivados se enmascaran en consola para no exponer PHI. Si
falta un tag se indica el fallback utilizado sin imprimir el valor clínico.

### Verificación real final recomendada

Usa Idonia real y reutiliza el PDF ya generado por Recog:

```powershell
python run_full_flow_minimal.py `
  --mode real `
  --confirm-external-calls `
  --recog-cache "data\cache\recog_real_patient_report.pdf" `
  --derive-idonia-context-from-dicom `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

Esta ejecución requiere `--confirm-external-calls` porque llama a Idonia, pero
no llama a Recog ni requiere `--confirm-recog-call`. Los tres elementos usan el
contexto derivado del DICOM y el PDF cacheado mantiene la validación clínica.

No debe repetirse para preparar el vídeo. Para la grabación usa `mock` o
`cache`.

Si la validación devuelve `requires_review`, el informe humanizado no se sube.
Después de una revisión clínica explícita puede habilitarse excepcionalmente
con `--allow-requires-review-upload`.

## Variables de entorno

Solo se cargan en `--mode real`. Crea `.env` a partir de `.env.example` sin
publicar valores reales:

```env
IDONIA_BASE_URL=https://connect-staging.idonia.com
IDONIA_API_KEY=<your_idonia_api_key>
IDONIA_API_SECRET=<your_idonia_api_secret>
IDONIA_REPORT_ENDPOINT=report_hak_numX
IDONIA_STUDY_ENDPOINT=dicom_hak_numX
RECOG_BASE_URL=https://api.recog.es
RECOG_API_KEY=<your_recog_api_key>
```

Idonia siempre requiere sus variables en modo real. Las variables de Recog solo
son obligatorias cuando no se proporciona `--recog-cache`. El programa falla
antes de llamar a la red si falta una variable necesaria para la ejecución
solicitada.

## Validación clínica

La validación es una barrera de seguridad conceptual, no un producto sanitario
ni un sistema diagnóstico. Comprueba:

- Conservación de conceptos críticos mediante grupos semánticos, sinónimos y
  plurales explícitos.
- Aparición de términos nuevos de alto riesgo como tumor, cáncer, metástasis,
  fractura, infección, trombosis, embolia, cirugía urgente o amputación.
- Presencia idempotente del disclaimer:

> Este informe es una explicación para facilitar la comprensión del paciente.
> No sustituye la valoración de un profesional sanitario ni modifica el informe
> médico original.

El contenido clínico devuelto por Recog no se modifica. Si el PDF no contiene
ya el aviso, se añade una única portada separada; los PDFs cacheados que ya lo
incluyen no reciben otra portada.

Si el resultado es `requires_review`, la subida del informe humanizado queda
bloqueada por defecto. `--allow-requires-review-upload` solo debe utilizarse
después de una revisión clínica explícita.

## Outputs

- `data/output/Informe_para_paciente_Recog.pdf`
- `data/logs/<timestamp>_full_flow_log.json`

Los logs incluyen `run_id`, modo, estados y validación. Los identificadores
derivados del DICOM se enmascaran. Los logs públicos deben revisarse y estar
saneados: nunca deben incluir API keys, JWT, URL/código de Magic Link, PIN ni
otros datos privados.

`--show-access-details` está desactivado por defecto y solo existe para una
comprobación local controlada en modo real. No debe usarse en vídeos, capturas
ni repositorios públicos.

## Verificación local

```powershell
python -m compileall run_full_flow_minimal.py tests
python -m unittest discover -s tests -v
```

## Seguridad

- No publicar `.env`, `.venv/`, `data/` ni evidencias privadas.
- No publicar credenciales, JWT, Magic Link, QR, PIN, UUID privados, informes
  médicos, datos DICOM ni logs antiguos con detalles de acceso.
- No grabar ni compartir la URL/código del Magic Link ni su PIN.
- No usar `--show-access-details` durante la grabación.
- Usar exclusivamente datos ficticios o autorizados para demostración.
- Revisar `git diff` y buscar secretos antes de empaquetar la entrega.

## Estado verificado

- Tests locales: 22/22 correctos.
- Contexto Idonia derivado desde los tags DICOM.
- Informe original, estudio DICOM e informe humanizado aceptados por Idonia con
  HTTP 201.
- Magic Link verificado manualmente con los tres elementos.
- Recog no se consumió de nuevo: se utilizó `--recog-cache`.
- El informe para paciente contiene un único disclaimer.
- El repositorio entregable no incluye `.env`, `data/`, claves, PIN ni Magic
  Links reales.

## Entrega

- [ ] Código fuente sin `.env`, datos privados ni outputs sensibles.
- [ ] Ejecución mock/cache validada sin credenciales y sin red.
- [ ] Evidencia real existente revisada y redaccionada.
- [ ] `Informe_para_paciente_Recog.pdf` visible en Idonia.
- [ ] Validación clínica mostrada y disclaimer visible.
- [ ] Magic Link/visor comprobado sin publicar URL, QR o PIN.
- [ ] Memoria técnica breve exportada a PDF.
- [ ] Memoria con problema, objetivo, justificación biomédica, arquitectura,
      metodología, IA utilizada, fuentes de datos, resultados, limitaciones y
      consideraciones éticas.
- [ ] Vídeo de evidencia de máximo 5 minutos.
- [ ] Vídeo sin credenciales, datos privados ni detalles de acceso reutilizables.
- [ ] Vídeo basado en ejecución mock/cacheada, no en accesos reales.

La entrega oficial debe incluir código fuente, memoria técnica PDF y vídeo de
evidencia de máximo 5 minutos.
