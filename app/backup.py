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


def crear_backup_zip():
    """Devuelve (nombre_archivo, BytesIO) con todo: base de datos (como
    volcado .sql, más portable que el binario) + fotos + firmas."""
    ruta_db = _ruta_sqlite()
    fecha = datetime.utcnow().strftime("%Y-%m-%d_%H%M")

    buffer_zip = io.BytesIO()
    with zipfile.ZipFile(buffer_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        if ruta_db and os.path.exists(ruta_db):
            volcado_sql = _copia_segura_sqlite(ruta_db)
            zf.writestr("base_de_datos.sql", volcado_sql.read())

        for carpeta_env, nombre_en_zip in [("FOTOS_DIR", "fotos"), ("FIRMAS_DIR", "firmas")]:
            ruta_carpeta = os.environ.get(carpeta_env)
            if ruta_carpeta and os.path.isdir(ruta_carpeta):
                for archivo in os.listdir(ruta_carpeta):
                    ruta_completa = os.path.join(ruta_carpeta, archivo)
                    if os.path.isfile(ruta_completa):
                        zf.write(ruta_completa, arcname=f"{nombre_en_zip}/{archivo}")

    buffer_zip.seek(0)
    return f"firztnet_backup_{fecha}.zip", buffer_zip
