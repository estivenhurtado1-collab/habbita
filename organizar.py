#!/usr/bin/env python3
"""Organiza archivos de una carpeta en subcarpetas según su extensión."""

import argparse
import shutil
import sys
from pathlib import Path

CATEGORIAS = {
    "Imagenes": {".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp"},
    "Documentos": {".pdf", ".doc", ".docx", ".txt", ".xlsx", ".csv", ".pptx"},
    "Videos": {".mp4", ".mov", ".avi", ".mkv"},
    "Audio": {".mp3", ".wav", ".aac", ".flac"},
    "Codigo": {".py", ".js", ".html", ".css", ".json"},
    "Comprimidos": {".zip", ".rar", ".tar", ".gz"},
}

EXTENSION_A_CATEGORIA = {
    ext: categoria
    for categoria, extensiones in CATEGORIAS.items()
    for ext in extensiones
}


def obtener_categoria(archivo: Path) -> str:
    extension = archivo.suffix.lower()
    return EXTENSION_A_CATEGORIA.get(extension, "Otros")


def destino_sin_colision(destino: Path) -> Path:
    """Devuelve una ruta libre, añadiendo (1), (2), etc. si ya existe."""
    if not destino.exists():
        return destino

    stem = destino.stem
    suffix = destino.suffix
    parent = destino.parent
    contador = 1

    while True:
        candidato = parent / f"{stem}({contador}){suffix}"
        if not candidato.exists():
            return candidato
        contador += 1


def organizar(carpeta: Path) -> tuple[dict[str, int], list[str]]:
    if not carpeta.exists():
        raise FileNotFoundError(f"La carpeta no existe: {carpeta}")
    if not carpeta.is_dir():
        raise NotADirectoryError(f"La ruta no es una carpeta: {carpeta}")

    resumen: dict[str, int] = {categoria: 0 for categoria in CATEGORIAS}
    resumen["Otros"] = 0
    omitidos: list[str] = []

    for entrada in carpeta.iterdir():
        if not entrada.is_file():
            continue
        if entrada.name.startswith("."):
            continue

        categoria = obtener_categoria(entrada)
        subcarpeta = carpeta / categoria
        subcarpeta.mkdir(exist_ok=True)

        destino = destino_sin_colision(subcarpeta / entrada.name)
        try:
            shutil.move(str(entrada), str(destino))
        except OSError as error:
            omitidos.append(f"{entrada.name} ({error})")
            continue
        resumen[categoria] += 1

    return resumen, omitidos


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Organiza archivos de una carpeta en subcarpetas según su tipo."
    )
    parser.add_argument(
        "carpeta",
        help="Ruta de la carpeta a organizar",
    )
    args = parser.parse_args()

    carpeta = Path(args.carpeta).expanduser().resolve()

    try:
        resumen, omitidos = organizar(carpeta)
    except (FileNotFoundError, NotADirectoryError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    total = sum(resumen.values())
    print(f"\nOrganización completada en: {carpeta}")
    print(f"Total de archivos movidos: {total}\n")

    for categoria in (*CATEGORIAS.keys(), "Otros"):
        cantidad = resumen[categoria]
        if cantidad > 0:
            print(f"  {categoria}: {cantidad} archivo(s)")

    if total == 0:
        print("  No se encontraron archivos para organizar.")

    if omitidos:
        print(f"\nNo se pudieron mover {len(omitidos)} archivo(s) (en uso o sin permiso):")
        for nombre in omitidos:
            print(f"  - {nombre}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
