#!/usr/bin/env python3
"""
Validador de entregables generados por extractor_procuraduria.py.

Uso con ruta incorporada:
    python validador.py

Uso alternativo sobrescribiendo la ruta de salida:
    python validador.py --out ./salida

Valida la estructura y reglas comprobables sin volver a leer el PDF original.
Devuelve código 0 si no hay errores críticos; devuelve 1 si encuentra errores.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from typing import Any

REQUIRED_FILES = (
    "procuraduria_empleos.json",
    "procuraduria_empleos.jsonl",
    "errores_extraccion.csv",
    "muestra_auditoria_10_empleos.json",
)
OUT_DIR_PREDETERMINADO: Path | None = Path(r"C:\Users\Hoover\Downloads\Json")

GENERAL_FORBIDDEN_IN_EMPLOYMENT = (
    "REGLAS DE INSCRIPCIÓN",
    "RECLAMACIONES",
    "TABLA GENERAL DE PRUEBAS",
    "NOTAS GENERALES",
)
IDENTIFICACION_FIELDS = (
    "numero_convocatoria",
    "denominacion",
    "codigo",
    "grado",
    "nivel_jerarquico",
    "asignacion_basica",
    "vigencia_salarial",
    "numero_cargos",
)
UBICACION_FIELDS = (
    "planta",
    "dependencias_iniciales",
    "procesos",
    "grupos_unidades_organizacionales",
    "lugares_cantidad_cargos",
    "texto_original_completo_ubicaciones",
)
REQUISITOS_FIELDS = (
    "texto_original_estudios",
    "nivel_formacion",
    "disciplinas_academicas",
    "posgrado",
    "tarjeta_profesional",
    "texto_original_experiencia",
    "duracion_meses",
    "tipos_experiencia",
    "operadores_y_o",
    "texto_equivalencias",
)
CONTENIDO_FIELDS = (
    "proposito",
    "funciones_generales",
    "funciones_especificas_por_dependencia_area",
    "conocimientos_especificos_por_grupo_funcional",
    "conocimientos_comunes",
    "competencias_comportamentales_y_nivel",
)
TRAZABILIDAD_FIELDS = (
    "pagina_inicial_pdf",
    "pagina_final_pdf",
    "numero_paginas_ficha",
    "paginas_ficha_declaradas",
    "alertas_errores_extraccion",
)


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as fh:
        for line_number, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"JSONL inválido en línea {line_number}: {exc}") from exc
    return rows


def add_missing_fields(errors: list[str], prefix: str, obj: dict[str, Any], fields: tuple[str, ...]) -> None:
    for field in fields:
        if field not in obj:
            errors.append(f"{prefix}: falta el campo `{field}`")


def iter_numbered_items(groups: Any) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    if not isinstance(groups, list):
        return items
    for group in groups:
        if isinstance(group, dict) and isinstance(group.get("items"), list):
            for item in group["items"]:
                if isinstance(item, dict):
                    items.append(item)
    return items


def parse_int(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = re.sub(r"\D+", "", value)
        return int(digits) if digits else None
    return None


def validate_empleo(index: int, empleo: dict[str, Any]) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    prefix = f"empleo[{index}] {empleo.get('numero_convocatoria', '<sin número>')}"

    add_missing_fields(errors, prefix, empleo, ("numero_convocatoria", "identificacion", "ubicacion", "requisitos", "contenido_empleo", "trazabilidad", "texto_oficial_completo"))
    numero = empleo.get("numero_convocatoria")
    if not isinstance(numero, str) or not re.fullmatch(r"\d+-2026", numero):
        errors.append(f"{prefix}: `numero_convocatoria` vacío o con formato distinto a NN-2026")

    identificacion = empleo.get("identificacion", {})
    ubicacion = empleo.get("ubicacion", {})
    requisitos = empleo.get("requisitos", {})
    contenido = empleo.get("contenido_empleo", {})
    trazabilidad = empleo.get("trazabilidad", {})
    if isinstance(identificacion, dict):
        add_missing_fields(errors, f"{prefix}.identificacion", identificacion, IDENTIFICACION_FIELDS)
        if identificacion.get("numero_convocatoria") != numero:
            errors.append(f"{prefix}: número de convocatoria no coincide entre raíz e identificación")
    else:
        errors.append(f"{prefix}: `identificacion` no es objeto")

    if isinstance(ubicacion, dict):
        add_missing_fields(errors, f"{prefix}.ubicacion", ubicacion, UBICACION_FIELDS)
        declared = parse_int(identificacion.get("numero_cargos")) if isinstance(identificacion, dict) else None
        lugares = ubicacion.get("lugares_cantidad_cargos", [])
        if isinstance(lugares, list):
            located = sum(parse_int(x.get("cantidad_cargos")) or 0 for x in lugares if isinstance(x, dict))
            if declared is not None and located and declared != located:
                warnings.append(f"{prefix}: suma de cargos por ubicación ({located}) no coincide con numero_cargos ({declared})")
    else:
        errors.append(f"{prefix}: `ubicacion` no es objeto")

    if isinstance(requisitos, dict):
        add_missing_fields(errors, f"{prefix}.requisitos", requisitos, REQUISITOS_FIELDS)
    else:
        errors.append(f"{prefix}: `requisitos` no es objeto")

    if isinstance(contenido, dict):
        add_missing_fields(errors, f"{prefix}.contenido_empleo", contenido, CONTENIDO_FIELDS)
        funciones = iter_numbered_items(contenido.get("funciones_especificas_por_dependencia_area"))
        if not funciones:
            warnings.append(f"{prefix}: no se detectaron funciones específicas numeradas")
        for item in funciones:
            if not item.get("numero") or not item.get("texto"):
                errors.append(f"{prefix}: función sin número o texto completo")
        conocimientos = contenido.get("conocimientos_especificos_por_grupo_funcional")
        if conocimientos is not None and not isinstance(conocimientos, list):
            errors.append(f"{prefix}: conocimientos específicos no están agrupados en lista")
    else:
        errors.append(f"{prefix}: `contenido_empleo` no es objeto")

    if isinstance(trazabilidad, dict):
        add_missing_fields(errors, f"{prefix}.trazabilidad", trazabilidad, TRAZABILIDAD_FIELDS)
        start = parse_int(trazabilidad.get("pagina_inicial_pdf"))
        end = parse_int(trazabilidad.get("pagina_final_pdf"))
        pages = parse_int(trazabilidad.get("numero_paginas_ficha"))
        declared_pages = parse_int(trazabilidad.get("paginas_ficha_declaradas"))
        if start is None or end is None or pages is None:
            errors.append(f"{prefix}: trazabilidad de páginas incompleta")
        elif end < start or pages != end - start + 1:
            errors.append(f"{prefix}: rango de páginas PDF inconsistente")
        if pages is not None and declared_pages is not None and pages != declared_pages:
            warnings.append(f"{prefix}: páginas detectadas ({pages}) no coinciden con Página 1 de N declarada ({declared_pages})")
    else:
        errors.append(f"{prefix}: `trazabilidad` no es objeto")

    text = empleo.get("texto_oficial_completo", "")
    if isinstance(text, str):
        upper = text.upper()
        for forbidden in GENERAL_FORBIDDEN_IN_EMPLOYMENT:
            if forbidden in upper:
                warnings.append(f"{prefix}: contiene bloque general repetido `{forbidden}`")
    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida entregables del extractor de Procuraduría.")
    parser.add_argument(
        "--out",
        type=Path,
        default=OUT_DIR_PREDETERMINADO,
        help=r"Carpeta con los cuatro entregables generados. Por defecto usa C:\\Users\\Hoover\\Downloads\\Json.",
    )
    args = parser.parse_args()
    if args.out is None:
        raise SystemExit("Configure OUT_DIR_PREDETERMINADO o ejecute con --out.")
    out_dir = args.out.expanduser().resolve()

    errors: list[str] = []
    warnings: list[str] = []
    for filename in REQUIRED_FILES:
        path = out_dir / filename
        if not path.exists():
            errors.append(f"Falta archivo requerido: {path}")
        elif path.stat().st_size == 0:
            errors.append(f"Archivo vacío: {path}")
    if errors:
        print("ERRORES CRÍTICOS")
        print("\n".join(f"- {e}" for e in errors))
        return 1

    payload = load_json(out_dir / "procuraduria_empleos.json")
    jsonl_rows = load_jsonl(out_dir / "procuraduria_empleos.jsonl")
    sample_rows = load_json(out_dir / "muestra_auditoria_10_empleos.json")
    with (out_dir / "errores_extraccion.csv").open(encoding="utf-8", newline="") as fh:
        csv_rows = list(csv.DictReader(fh))
        csv_headers = fh.seek(0) or next(csv.reader(fh))

    if not isinstance(payload, dict):
        errors.append("procuraduria_empleos.json debe ser un objeto raíz")
        empleos = []
    else:
        if "bloque_general_convocatoria" not in payload:
            errors.append("procuraduria_empleos.json no tiene `bloque_general_convocatoria`")
        empleos = payload.get("empleos", [])
        if not isinstance(empleos, list):
            errors.append("procuraduria_empleos.json: `empleos` no es una lista")
            empleos = []

    if len(jsonl_rows) != len(empleos):
        errors.append(f"JSONL tiene {len(jsonl_rows)} filas, pero JSON tiene {len(empleos)} empleos")
    if [row.get("numero_convocatoria") for row in jsonl_rows] != [row.get("numero_convocatoria") for row in empleos]:
        errors.append("JSONL y JSON no conservan el mismo orden/número de convocatorias")
    if not isinstance(sample_rows, list):
        errors.append("muestra_auditoria_10_empleos.json debe ser una lista")
    elif sample_rows != empleos[:10]:
        errors.append("La muestra auditada no coincide con los primeros 10 empleos del JSON")
    expected_csv = ["numero_convocatoria", "pagina_pdf", "tipo", "detalle"]
    if csv_headers != expected_csv:
        errors.append(f"errores_extraccion.csv tiene encabezados {csv_headers}; se esperaban {expected_csv}")

    seen: set[str] = set()
    for index, empleo in enumerate(empleos):
        if not isinstance(empleo, dict):
            errors.append(f"empleo[{index}] no es objeto")
            continue
        numero = empleo.get("numero_convocatoria")
        if numero in seen:
            errors.append(f"Convocatoria duplicada: {numero}")
        seen.add(str(numero))
        emp_errors, emp_warnings = validate_empleo(index, empleo)
        errors.extend(emp_errors)
        warnings.extend(emp_warnings)

    print(f"Carpeta validada: {out_dir}")
    print(f"Empleos en JSON: {len(empleos)}")
    print(f"Filas en JSONL: {len(jsonl_rows)}")
    print(f"Filas en errores_extraccion.csv: {len(csv_rows)}")
    print(f"Elementos en muestra auditada: {len(sample_rows) if isinstance(sample_rows, list) else 'N/A'}")
    print(f"Errores críticos: {len(errors)}")
    print(f"Advertencias: {len(warnings)}")

    if warnings:
        print("\nADVERTENCIAS")
        for warning in warnings[:100]:
            print(f"- {warning}")
        if len(warnings) > 100:
            print(f"- ... {len(warnings) - 100} advertencias adicionales")
    if errors:
        print("\nERRORES CRÍTICOS")
        for error in errors[:100]:
            print(f"- {error}")
        if len(errors) > 100:
            print(f"- ... {len(errors) - 100} errores adicionales")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
