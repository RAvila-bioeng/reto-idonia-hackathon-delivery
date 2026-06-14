# Reto Idonia - Interoperabilidad y humanización de información médica

Prototipo del I Hackathon IA en Biomedicina para compartir un estudio médico,
el informe original y una explicación comprensible para el paciente mediante
Idonia y Recog.

El entry point principal es `run_full_flow_minimal.py`.

## Flujo

1. Recibir un informe PDF y un estudio DICOM/ZIP de prueba.
2. Subir o simular la subida del informe original a Idonia.
3. Extraer el texto con PyMuPDF.
4. Generar, reutilizar o simular el PDF humanizado de Recog.
5. Añadir una portada no clínica con el disclaimer para paciente.
6. Validar conceptos conservados, términos clínicos nuevos y disclaimer.
7. Subir el archivo como `Informe_para_paciente_Recog.pdf` solo si pasa la
   validación, salvo autorización explícita tras revisión.
8. Subir o simular el estudio y generar o simular el Magic Link.

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

## Modos de ejecución

### Mock seguro, por defecto

No carga credenciales ni realiza llamadas a Idonia o Recog. Usa el informe
original como contenido simulado, añade la portada de disclaimer, ejecuta la
validación y genera un log de evidencia offline.

```powershell
python run_full_flow_minimal.py `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

### Cache de Recog

Reutiliza un PDF ya generado. Tampoco carga credenciales ni realiza llamadas
externas.

```powershell
python run_full_flow_minimal.py `
  --mode cache `
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
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

### Idonia real con Recog cacheado

Para una verificación final sin consumir de nuevo recursos de Recog, el modo
real puede reutilizar un PDF humanizado. Se mantiene la confirmación de llamadas
externas porque las operaciones con Idonia siguen siendo reales:

```powershell
python run_full_flow_minimal.py `
  --mode real `
  --confirm-external-calls `
  --recog-cache "data\cache\recog_real_patient_report.pdf" `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

Esta combinación no llama a Recog ni requiere `--confirm-recog-call`. El PDF
cacheado pasa por la misma validación clínica y el bloqueo por
`requires_review` antes de cualquier subida del informe humanizado.

### Diagnóstico de ruta DICOM sin red

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

Para la ejecución final con Idonia real y Recog cacheado:

```powershell
python run_full_flow_minimal.py `
  --mode real `
  --confirm-external-calls `
  --recog-cache "data\cache\recog_real_patient_report.pdf" `
  --derive-idonia-context-from-dicom `
  --report "data\input\Informe_RM_RODILLA.pdf" `
  --study "data\input\estudio_rm\Imágenes RM Rodilla.zip"
```

No debe ejecutarse repetidamente para preparar el vídeo. Usa mock o cache.

Si la validación devuelve `requires_review`, el informe humanizado no se sube.
Después de una revisión clínica explícita puede habilitarse excepcionalmente
con `--allow-requires-review-upload`.

## Variables de entorno

Solo son necesarias en `--mode real`. Crea `.env` a partir de `.env.example`
sin publicar valores reales:

```env
IDONIA_BASE_URL=https://connect-staging.idonia.com
IDONIA_API_KEY=<your_idonia_api_key>
IDONIA_API_SECRET=<your_idonia_api_secret>
IDONIA_REPORT_ENDPOINT=report_hak_numX
IDONIA_STUDY_ENDPOINT=dicom_hak_numX
RECOG_BASE_URL=https://api.recog.es
RECOG_API_KEY=<your_recog_api_key>
```

El modo real falla antes de llamar a la red si falta una variable.

## Validación clínica

La validación es una barrera de seguridad conceptual, no un producto sanitario
ni un sistema diagnóstico. Comprueba:

- Conservación de conceptos críticos del caso de demostración.
- Aparición de términos nuevos de alto riesgo como tumor, cáncer, metástasis,
  fractura, infección, trombosis, embolia, cirugía urgente o amputación.
- Presencia del disclaimer:

> Este informe es una explicación para facilitar la comprensión del paciente.
> No sustituye la valoración de un profesional sanitario ni modifica el informe
> médico original.

El contenido clínico devuelto por Recog no se modifica. Si el PDF no contiene
ya el aviso, se añade una única portada separada; los PDFs cacheados que ya lo
incluyen no reciben otra portada.

## Outputs

- `data/output/Informe_para_paciente_Recog.pdf`
- `data/logs/<timestamp>_full_flow_log.json`

Los logs incluyen `run_id`, modo, estados y validación. No incluyen API keys,
JWT, Magic Link completo, PIN ni códigos privados. `--show-access-details` está
desactivado por defecto y solo existe para comprobación local en modo real. No
debe usarse en vídeos, capturas ni repositorios públicos.

## Verificación local

```powershell
python -m compileall run_full_flow_minimal.py tests
python -m unittest discover -s tests -v
```

## Seguridad

- `.env`, `.venv/`, `data/` y evidencias privadas están ignorados por Git.
- No publicar credenciales, JWT, Magic Link, QR, PIN, UUID privados, informes
  médicos, datos DICOM ni logs antiguos con detalles de acceso.
- No mostrar `.env` ni ejecutar probes de diagnóstico durante la grabación.
- Usar exclusivamente datos ficticios o autorizados para demostración.
- Revisar `git diff` y buscar secretos antes de empaquetar la entrega.

## Final delivery checklist

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

La entrega oficial debe incluir código fuente, memoria técnica PDF y vídeo de
evidencia de máximo 5 minutos.
