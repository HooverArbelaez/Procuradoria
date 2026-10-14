# Extractor de convocatorias de la Procuraduría

Convierte el PDF de convocatorias de 2026 en datos JSON y JSONL, conservando el texto extraído y las páginas de origen de cada empleo. Incluye un validador para comprobar los cuatro entregables.

## El problema y cómo se resolvió

La extracción debe separar fichas con encabezados variables y funcionar fuera del equipo Windows donde se desarrolló originalmente. El código y su historial muestran estas correcciones, ya presentes antes de configurar este entorno:

- **Rutas dependientes del equipo:** las rutas de Windows no sirven en Linux. Los scripts ahora aceptan `--pdf` y `--out`, además de `PROCURADURIA_PDF` y `PROCURADURIA_OUT`. En Linux, el extractor puede detectar el único PDF de la carpeta actual. Se recomienda indicar ambas rutas explícitamente para evitar preguntas interactivas y sobrescribir entregables por accidente.
- **Compatibilidad con copias de PyCharm Scratch:** una copia editada podía tener un objeto `Path` donde se esperaba una función de rutas predeterminadas. El extractor comprueba si esos nombres son invocables y restaura las funciones cuando hace falta.
- **Encabezados de convocatoria variables:** el reconocimiento acepta el punto opcional en `No.`, variantes de separadores y la palabra `de`. Cuando falta el número pero aparece el marcador de primera página de una nueva ficha, infiere el número siguiente. Esto es una heurística que debe revisarse contra el PDF.
- **Bloques generales repetidos:** reglas de inscripción, reclamaciones, pruebas y notas se separan de las fichas y se guardan en `bloque_general_convocatoria`.

Para el entorno en la nube faltaban instrucciones reproducibles de instalación y ejecución. Se creó un entorno virtual fuera del repositorio, se instaló una versión concreta de PyMuPDF y se ejecutó el flujo completo con una carpeta de salida independiente. No fue necesario modificar los scripts ni los datos originales.

## Instalación en Linux

Configuración comprobada: Python 3.12.14 y PyMuPDF 1.26.7. El módulo `fitz` utilizado por el extractor lo proporciona **PyMuPDF**; no instale el paquete independiente llamado `fitz`.

Desde el entorno en la nube:

```bash
cd /workspace/Procuradoria
python -m venv /workspace/procuradoria-env
/workspace/procuradoria-env/bin/python -m pip install 'PyMuPDF==1.26.7'
/workspace/procuradoria-env/bin/python -m pip check
```

La instalación necesita acceso a `pypi.org` y `files.pythonhosted.org`. El procesamiento posterior es local; no requiere credenciales, base de datos ni servidor. En otro equipo, adapte las rutas del entorno virtual y del repositorio.

## Extraer y validar

```bash
cd /workspace/Procuradoria
/workspace/procuradoria-env/bin/python extractor_procuraduria.py \
  --pdf 'COMPILADO DE CONVOCATORIAS VR03_28042026 (1).pdf' \
  --out /workspace/procuradoria-output
/workspace/procuradoria-env/bin/python validador.py \
  --out /workspace/procuradoria-output
```

El extractor sobrescribe los cuatro entregables de la carpeta indicada. Use una carpeta separada del repositorio para conservar los archivos versionados. Para generar una muestra reducida puede agregar `--limit 10`; la lectura del PDF sigue siendo completa.

| Archivo | Contenido |
| --- | --- |
| `procuraduria_empleos.json` | Bloques generales y lista estructurada de empleos. |
| `procuraduria_empleos.jsonl` | Un empleo por línea, para procesamiento incremental. |
| `errores_extraccion.csv` | Errores registrados por el extractor; puede contener solo encabezados. |
| `muestra_auditoria_10_empleos.json` | Los primeros diez empleos para revisión manual. |

El validador comprueba archivos, campos requeridos, números duplicados, orden y cantidad de registros entre JSON y JSONL, muestra inicial y consistencia de rangos de páginas. Devuelve `0` cuando no hay errores críticos y `1` cuando los detecta. Las advertencias se informan por separado.

## Resultado comprobado en la nube

Validación realizada el 14 de octubre de 2026 sobre el PDF incluido:

- Extracción completa: **269 empleos**.
- Validación de la nueva salida: **269 filas JSONL, 10 elementos de muestra, 0 filas de errores, 0 errores críticos y 0 advertencias**.
- Los registros JSON y JSONL generados son idénticos entre sí. El contenido JSON deserializado coincide con los entregables versionados, aunque la representación de los archivos difiere.
- Los entregables originales también pasan el validador y `pip check` no detecta dependencias incompatibles.

Estos resultados verifican la ejecución y la consistencia estructural, pero no certifican la exactitud de todos los campos respecto al PDF. El extractor usa texto de PyMuPDF y no ejecuta OCR; las páginas escaneadas y los campos vacíos requieren auditoría manual. El validador tampoco exige que todos los valores estén completos ni considera crítica toda discrepancia en el número de páginas declarado. Las reglas actuales están dirigidas a convocatorias de **2026**.

## Uso en futuras tareas de nube

Use el checkout existente en `/workspace/Procuradoria`: cada tarea ya está aislada y no necesita un Git worktree adicional. Compruebe el entorno virtual con `pip check` y ejecute los comandos anteriores cuando necesite regenerar los datos. No hay procesos persistentes que arrancar. Las instrucciones de instalación y uso se guardan también en el borrador de configuración del entorno; su publicación se realiza desde la interfaz del producto.
