"""Genera una copia de seguridad completa: la base de datos (copiada de
forma segura, sin riesgo de capturarla a medio escribir) más las fotos
y firmas guardadas en disco — todo junto en un único ZIP en memoria."""
import io
import os
import sqlite3
import zipfile
from datetime import datetime
from urllib.parse import urlparse

from flask import current_app


def _ruta_sqlite():
    """Extrae la ruta del archivo .db a partir de la URL de conexión.
    Si algún día pasas a PostgreSQL, esta función deja de aplicar —
    habría que hacer el backup con pg_dump en su lugar."""
    uri = current_app.config["SQLALCHEMY_DATABASE_URI"]
    if not uri.startswith("sqlite"):
        return None
    return urlparse(uri).path or uri.replace("sqlite:///", "/")


def _copia_segura_sqlite(ruta_origen):
    """Usa la API de backup de SQLite (no una copia de archivo normal):
    así, aunque el servidor esté escribiendo en la base de datos en ese
    mismo instante, la copia sale consistente y sin corromper."""
    origen = sqlite3.connect(ruta_origen)
    destino = sqlite3.connect(":memory:")
    origen.backup(destino)
    origen.close()

    buffer = io.BytesIO()
    for linea in destino.iterdump():
        buffer.write((linea + "\n").encode("utf-8"))
    destino.close()
    buffer.seek(0)
    return buffer


def _volcado_json():
    """Todas las tablas de la base de datos, fila a fila, en un JSON."""
    import json
    from app import db
    datos = {}
    for tabla in db.metadata.sorted_tables:
        filas = db.session.execute(tabla.select()).mappings().all()
        datos[tabla.name] = [dict(f) for f in filas]
    return json.dumps(datos, ensure_ascii=False, default=str, indent=1)


def crear_backup_zip():
    """Devuelve (nombre_archivo, BytesIO) con todo: base de datos (como
    volcado .sql, más portable que el binario) + fotos + firmas."""
    ruta_db = _ruta_sqlite()
    from app.horario import ahora_madrid
    fecha = ahora_madrid().strftime("%Y-%m-%d_%H%M")

    buffer_zip = io.BytesIO()
    with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        if ruta_db and os.path.exists(ruta_db):
            volcado_sql = _copia_segura_sqlite(ruta_db)
            zf.writestr("base_de_datos.sql", volcado_sql.read())
        elif ruta_db is None:
            # No es SQLite (por ejemplo, PostgreSQL): antes la base de datos se quedaba
            # FUERA del backup sin avisar. Ahora se guardan todas las tablas en JSON.
            zf.writestr("base_de_datos.json", _volcado_json())
        else:
            raise RuntimeError(f"No se encuentra el archivo de la base de datos ({ruta_db})")

        # Se usan las mismas carpetas que usan las fotos y las firmas (aunque no
        # tengas puestas las variables FOTOS_DIR / FIRMAS_DIR, que antes las dejaba fuera).
        from app.routes.fotos import FOTOS_DIR
        from app.firmas import FIRMAS_DIR
        for ruta_carpeta, nombre_en_zip in [(FOTOS_DIR, "fotos"), (FIRMAS_DIR, "firmas")]:
            if ruta_carpeta and os.path.isdir(ruta_carpeta):
                for archivo in os.listdir(ruta_carpeta):
                    ruta_completa = os.path.join(ruta_carpeta, archivo)
                    if os.path.isfile(ruta_completa):
                        zf.write(ruta_completa, arcname=f"{nombre_en_zip}/{archivo}")

    buffer_zip.seek(0)
    return f"firztnet_backup_{fecha}.zip", buffer_zip
