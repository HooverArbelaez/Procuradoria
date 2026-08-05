#!/usr/bin/env python3
"""
Extractor reproducible para convertir el PDF de convocatorias de la Procuraduría a JSON/JSONL.

Uso interactivo:
    python extractor_procuraduria.py

Uso no interactivo:
    python extractor_procuraduria.py --pdf "COMPILADO DE CONVOCATORIAS VR03_28042026 (1).pdf" --out ./salida

Dependencia recomendada:
    pip install pymupdf
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def fatal(message: str) -> int:
    print(f"ERROR: {message}", file=sys.stderr)
    return 1

try:
    import fitz  # PyMuPDF
except ImportError:  # pragma: no cover
    fitz = None  # type: ignore[assignment]

CONVOCATORIA_RE = re.compile(r"CONVOCATORIA\s+No\.?\s*([0-9]+\s*-\s*2026)", re.IGNORECASE)
PAGINA_FICHA_RE = re.compile(r"P[aá]gina\s+(\d+)\s+de\s+(\d+)", re.IGNORECASE)
SECTION_RE = re.compile(r"^\s*(\d+)\.\s+([A-ZÁÉÍÓÚÜÑ\s,]+)\s*$", re.MULTILINE)
MONEY_RE = re.compile(r"\$\s*[0-9][0-9\.,]*")
GENERAL_BLOCK_TITLES = (
    "REGLAS DE INSCRIPCIÓN",
    "RECLAMACIONES",
    "TABLA GENERAL DE PRUEBAS",
    "NOTAS GENERALES",
)

DEFAULT_PDF_PATH = Path(r"C:\Users\Hoover\Downloads\COMPILADO DE CONVOCATORIAS VR03_28042026 (1).pdf")
DEFAULT_OUT_DIR = Path(r"C:\Users\Hoover\Downloads\Json")

FIELD_ALIASES = {
    "denominacion": ("DENOMINACIÓN", "DENOMINACION"),
    "codigo": ("CÓDIGO", "CODIGO"),
    "grado": ("GRADO",),
    "nivel_jerarquico": ("NIVEL JERÁRQUICO", "NIVEL JERARQUICO"),
    "asignacion_basica": ("ASIGNACIÓN BÁSICA", "ASIGNACION BASICA"),
    "vigencia_salarial": ("VIGENCIA SALARIAL",),
    "numero_cargos": ("NÚMERO DE CARGOS", "NUMERO DE CARGOS", "No. DE CARGOS"),
    "planta": ("PLANTA",),
    "dependencias_iniciales": ("DEPENDENCIA", "DEPENDENCIAS"),
    "procesos": ("PROCESO", "PROCESOS"),
    "grupos_unidades_organizacionales": ("GRUPO", "GRUPOS", "UNIDAD ORGANIZACIONAL", "UNIDADES ORGANIZACIONALES"),
}

@dataclass
class ErrorExtraccion:
    numero_convocatoria: str
    pagina_pdf: int | None
    tipo: str
    detalle: str

@dataclass
class Empleo:
    numero_convocatoria: str
    identificacion: dict[str, Any]
    ubicacion: dict[str, Any]
    requisitos: dict[str, Any]
    contenido_empleo: dict[str, Any]
    trazabilidad: dict[str, Any]
    texto_oficial_completo: str


def norm(text: str) -> str:
    return re.sub(r"[ \t]+", " ", text.replace("\r", "")).strip()


def ask_path(prompt: str) -> Path:
    value = input(prompt).strip().strip('"').strip("'")
    if not value:
        raise ValueError("La ruta no puede estar vacía.")
    return Path(value).expanduser().resolve()


def default_pdf_path() -> Path | None:
    env_value = os.environ.get("PROCURADURIA_PDF")
    if env_value:
        return Path(env_value).expanduser()
    if os.name == "nt":
        return DEFAULT_PDF_PATH
    pdfs = sorted(Path.cwd().glob("*.pdf"))
    return pdfs[0] if len(pdfs) == 1 else None


def default_out_dir() -> Path:
    env_value = os.environ.get("PROCURADURIA_OUT")
    if env_value:
        return Path(env_value).expanduser()
    if os.name == "nt":
        return DEFAULT_OUT_DIR
    return Path.cwd()


def extract_pages(pdf_path: Path) -> list[dict[str, Any]]:
    if fitz is None:
        raise RuntimeError("Falta PyMuPDF. Instálelo con: python -m pip install --upgrade pymupdf")
    doc = fitz.open(pdf_path)
    pages: list[dict[str, Any]] = []
    for idx, page in enumerate(doc, start=1):
        # "text" conserva el orden de lectura mejor que unir bloques manualmente para este caso.
        text = page.get_text("text", sort=True)
        pages.append({"pdf_page": idx, "text": norm(text)})
    return pages


def split_general_blocks(full_text: str) -> tuple[str, dict[str, str]]:
    general: dict[str, str] = {}
    cleaned = full_text
    for title in GENERAL_BLOCK_TITLES:
        pattern = re.compile(
            rf"(?is)({re.escape(title)}.*?)(?="
            rf"{'|'.join(re.escape(t) for t in GENERAL_BLOCK_TITLES if t != title)}|CONVOCATORIA\s+No\.|\Z)"
        )
        matches = list(pattern.finditer(cleaned))
        if matches:
            general[title.lower().replace(" ", "_")] = norm("\n\n".join(m.group(1) for m in matches))
            cleaned = pattern.sub("\n", cleaned)
    return cleaned, general


def split_empleos(pages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[ErrorExtraccion]]:
    empleos: list[dict[str, Any]] = []
    errors: list[ErrorExtraccion] = []
    current: dict[str, Any] | None = None

    for page in pages:
        text = page["text"]
        conv = CONVOCATORIA_RE.search(text)
        ficha_page = PAGINA_FICHA_RE.search(text)
        # Algunas fichas del PDF no exponen el marcador "Página 1 de N" en el texto
        # extraído, pero sí inician con "CONVOCATORIA No.". En esos casos también
        # se debe partir una nueva ficha para no unir varios empleos en uno solo.
        is_start = bool(conv and (not ficha_page or ficha_page.group(1) == "1"))
        if is_start:
            if current:
                empleos.append(current)
            current = {
                "numero_convocatoria": conv.group(1).replace(" ", ""),
                "start_pdf_page": page["pdf_page"],
                "end_pdf_page": page["pdf_page"],
                "expected_pages": int(ficha_page.group(2)) if ficha_page else None,
                "pages": [page],
            }
        elif current:
            current["pages"].append(page)
            current["end_pdf_page"] = page["pdf_page"]
        elif text.strip():
            errors.append(ErrorExtraccion("", page["pdf_page"], "pagina_fuera_de_ficha", "Página con texto antes de la primera ficha detectada."))
    if current:
        empleos.append(current)
    return empleos, errors


def section_map(text: str) -> dict[str, str]:
    matches = list(SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        key = f"{m.group(1)}. {norm(m.group(2)).upper()}"
        sections[key] = norm(text[start:end])
    return sections


def find_section(sections: dict[str, str], *needles: str) -> str:
    for key, value in sections.items():
        upper = key.upper()
        if any(needle.upper() in upper for needle in needles):
            return value
    return ""


def extract_field(text: str, aliases: tuple[str, ...]) -> str:
    alias_re = "|".join(re.escape(a) for a in aliases)
    # Captura el valor hasta el siguiente rótulo típico en mayúsculas o salto doble.
    m = re.search(rf"(?is)(?:{alias_re})\s*:?\s*(.+?)(?=\n\s*[A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ .º°]+\s*:?|\n\n|$)", text)
    return norm(m.group(1)) if m else ""


def parse_locations(text: str) -> list[dict[str, Any]]:
    lugares: list[dict[str, Any]] = []
    for line in [norm(x) for x in text.splitlines() if norm(x)]:
        qty = re.search(r"(?:CARGOS?|VACANTES?)\s*:?\s*(\d+)|\b(\d+)\s+(?:CARGOS?|VACANTES?)\b", line, re.IGNORECASE)
        if qty:
            cantidad = int(qty.group(1) or qty.group(2))
            lugares.append({"lugar": line, "cantidad_cargos": cantidad})
    return lugares


def parse_requirements(text: str) -> dict[str, Any]:
    exp_match = re.search(r"(?is)(EXPERIENCIA.*)", text)
    estudios = norm(text[: exp_match.start()]) if exp_match else text
    experiencia = norm(exp_match.group(1)) if exp_match else ""
    meses = [int(x) for x in re.findall(r"(\d+)\s+mes(?:es)?", experiencia, flags=re.IGNORECASE)]
    return {
        "texto_original_estudios": estudios,
        "nivel_formacion": extract_field(estudios, ("NIVEL DE FORMACIÓN", "NIVEL DE FORMACION")),
        "disciplinas_academicas": extract_field(estudios, ("DISCIPLINAS ACADÉMICAS", "DISCIPLINAS ACADEMICAS", "DISCIPLINA ACADÉMICA")),
        "posgrado": extract_field(estudios, ("POSGRADO", "POSTGRADO")),
        "tarjeta_profesional": "SI" if re.search(r"tarjeta\s+profesional", estudios, re.IGNORECASE) else "",
        "texto_original_experiencia": experiencia,
        "duracion_meses": meses,
        "tipos_experiencia": sorted(set(re.findall(r"experiencia\s+([a-záéíóúñ ]+)", experiencia, flags=re.IGNORECASE))),
        "operadores_y_o": sorted(set(re.findall(r"\b[YO]\b", text, flags=re.IGNORECASE))),
        "texto_equivalencias": extract_field(text, ("EQUIVALENCIAS", "ALTERNATIVAS")),
    }


def parse_grouped_numbered(text: str) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    current = {"grupo_funcional": "GENERAL", "items": []}
    for raw in text.splitlines():
        line = norm(raw)
        if not line:
            continue
        item = re.match(r"^(\d{1,3})[\).\-]\s+(.+)$", line)
        if item:
            current["items"].append({"numero": item.group(1), "texto": item.group(2)})
        elif line.isupper() and len(line) > 6:
            if current["items"]:
                groups.append(current)
            current = {"grupo_funcional": line, "items": []}
        elif current["items"]:
            current["items"][-1]["texto"] = norm(current["items"][-1]["texto"] + " " + line)
    if current["items"] or current["grupo_funcional"] != "GENERAL":
        groups.append(current)
    return groups


def build_empleo(raw: dict[str, Any]) -> tuple[Empleo, list[ErrorExtraccion]]:
    numero = raw["numero_convocatoria"]
    text = norm("\n\n".join(p["text"] for p in raw["pages"]))
    # Evita repetir reglas de inscripción, reclamaciones, pruebas y notas dentro de cada empleo.
    text, _general_in_ficha = split_general_blocks(text)
    text = norm(text)
    sections = section_map(text)
    ident_text = find_section(sections, "IDENTIFICACIÓN DEL EMPLEO", "IDENTIFICACION DEL EMPLEO") or text[:4000]
    ubic_text = find_section(sections, "UBICACIÓN", "UBICACION")
    req_text = find_section(sections, "REQUISITOS")
    proposito_text = find_section(sections, "PROPÓSITO", "PROPOSITO")
    funciones_text = find_section(sections, "FUNCIONES")
    conocimientos_text = find_section(sections, "CONOCIMIENTOS")
    competencias_text = find_section(sections, "COMPETENCIAS")

    identificacion = {k: extract_field(ident_text, aliases) for k, aliases in FIELD_ALIASES.items() if k not in {"planta", "dependencias_iniciales", "procesos", "grupos_unidades_organizacionales"}}
    identificacion["numero_convocatoria"] = numero
    if not identificacion.get("asignacion_basica"):
        money = MONEY_RE.search(ident_text)
        identificacion["asignacion_basica"] = money.group(0) if money else ""
    if not identificacion.get("numero_cargos"):
        cargos = re.search(r"(?:NÚMERO|NUMERO|No\.)\s+DE\s+CARGOS\D+(\d+)", ident_text, re.IGNORECASE)
        identificacion["numero_cargos"] = cargos.group(1) if cargos else ""

    ubicacion = {k: extract_field(ubic_text, aliases) for k, aliases in FIELD_ALIASES.items() if k in {"planta", "dependencias_iniciales", "procesos", "grupos_unidades_organizacionales"}}
    ubicacion["lugares_cantidad_cargos"] = parse_locations(ubic_text)
    ubicacion["texto_original_completo_ubicaciones"] = ubic_text

    contenido = {
        "proposito": proposito_text,
        "funciones_generales": parse_grouped_numbered(funciones_text),
        "funciones_especificas_por_dependencia_area": parse_grouped_numbered(funciones_text),
        "conocimientos_especificos_por_grupo_funcional": parse_grouped_numbered(conocimientos_text),
        "conocimientos_comunes": find_section(sections, "CONOCIMIENTOS COMUNES"),
        "competencias_comportamentales_y_nivel": competencias_text,
    }

    errors: list[ErrorExtraccion] = []
    ficha_markers = [PAGINA_FICHA_RE.search(p["text"]) for p in raw["pages"]]
    if not numero:
        errors.append(ErrorExtraccion(numero, raw["start_pdf_page"], "validacion", "La ficha no tiene número de convocatoria."))
    if raw["expected_pages"] and len(raw["pages"]) != raw["expected_pages"]:
        errors.append(ErrorExtraccion(numero, raw["start_pdf_page"], "validacion", f"La ficha tiene {len(raw['pages'])} páginas detectadas, pero declara {raw['expected_pages']}."))
    if raw["expected_pages"] and (not ficha_markers or not ficha_markers[0] or ficha_markers[0].group(1) != "1"):
        errors.append(ErrorExtraccion(numero, raw["start_pdf_page"], "validacion", "La ficha no inicia en Página 1 de N."))
    if raw["expected_pages"] and ficha_markers and ficha_markers[-1] and ficha_markers[-1].group(1) != ficha_markers[-1].group(2):
        errors.append(ErrorExtraccion(numero, raw["end_pdf_page"], "validacion", "La ficha no termina en Página N de N."))
    declared = int(identificacion["numero_cargos"]) if str(identificacion.get("numero_cargos", "")).isdigit() else None
    located = sum(x["cantidad_cargos"] for x in ubicacion["lugares_cantidad_cargos"])
    if declared is not None and located and declared != located:
        errors.append(ErrorExtraccion(numero, raw["start_pdf_page"], "validacion", f"Suma de cargos por ubicación ({located}) no coincide con número de cargos ({declared})."))
    if not contenido["funciones_especificas_por_dependencia_area"]:
        errors.append(ErrorExtraccion(numero, raw["start_pdf_page"], "validacion", "No se detectaron funciones numeradas."))

    empleo = Empleo(
        numero_convocatoria=numero,
        identificacion=identificacion,
        ubicacion=ubicacion,
        requisitos=parse_requirements(req_text),
        contenido_empleo=contenido,
        trazabilidad={
            "pagina_inicial_pdf": raw["start_pdf_page"],
            "pagina_final_pdf": raw["end_pdf_page"],
            "numero_paginas_ficha": len(raw["pages"]),
            "paginas_ficha_declaradas": raw["expected_pages"],
            "alertas_errores_extraccion": [asdict(e) for e in errors],
        },
        texto_oficial_completo=text,
    )
    return empleo, errors


def write_outputs(out_dir: Path, empleos: list[Empleo], general: dict[str, str], errors: list[ErrorExtraccion]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {"bloque_general_convocatoria": general, "empleos": [asdict(e) for e in empleos]}
    (out_dir / "procuraduria_empleos.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    with (out_dir / "procuraduria_empleos.jsonl").open("w", encoding="utf-8") as fh:
        for empleo in empleos:
            fh.write(json.dumps(asdict(empleo), ensure_ascii=False) + "\n")
    with (out_dir / "errores_extraccion.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["numero_convocatoria", "pagina_pdf", "tipo", "detalle"])
        writer.writeheader()
        for error in errors:
            writer.writerow(asdict(error))
    sample = [asdict(e) for e in empleos[:10]]
    (out_dir / "muestra_auditoria_10_empleos.json").write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Convierte el PDF de convocatorias de Procuraduría en JSON estructurado.")
    parser.add_argument("--pdf", type=Path, default=default_pdf_path(), help="Path del PDF a leer. Por defecto usa PROCURADURIA_PDF, la ruta de Hoover en Windows o el único PDF en la carpeta actual.")
    parser.add_argument("--out", type=Path, default=default_out_dir(), help="Carpeta donde se depositan los entregables. Por defecto usa PROCURADURIA_OUT, la carpeta Json de Hoover en Windows o la carpeta actual.")
    parser.add_argument("--limit", type=int, default=0, help="Procesa solo los primeros N empleos; útil para auditar la muestra inicial.")
    args = parser.parse_args()

    try:
        pdf_path = (args.pdf or ask_path("Path del PDF a leer: ")).expanduser().resolve()
        out_dir = args.out.expanduser().resolve()
    except (EOFError, KeyboardInterrupt, ValueError) as exc:
        return fatal(str(exc) or "Ejecución cancelada.")
    if not pdf_path.exists():
        return fatal(f"No existe el PDF: {pdf_path}")
    if not pdf_path.is_file():
        return fatal(f"La ruta del PDF no es un archivo: {pdf_path}")

    try:
        pages = extract_pages(pdf_path)
    except Exception as exc:
        return fatal(str(exc))
    full_text = "\n\n".join(p["text"] for p in pages)
    _, general = split_general_blocks(full_text)
    raw_empleos, errors = split_empleos(pages)
    if args.limit > 0:
        raw_empleos = raw_empleos[: args.limit]

    empleos: list[Empleo] = []
    for raw in raw_empleos:
        empleo, empleo_errors = build_empleo(raw)
        empleos.append(empleo)
        errors.extend(empleo_errors)

    try:
        write_outputs(out_dir, empleos, general, errors)
    except OSError as exc:
        return fatal(f"No se pudieron escribir los entregables en {out_dir}: {exc}")
    print(f"OK: {len(empleos)} empleos procesados.")
    print(f"Entregables escritos en: {out_dir}")
    print("Archivos: procuraduria_empleos.json, procuraduria_empleos.jsonl, errores_extraccion.csv, muestra_auditoria_10_empleos.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
