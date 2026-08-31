from flask import Blueprint, jsonify, send_file
from app.backup import crear_backup_zip
from app.notificaciones import enviar_documento_telegram

backup_bp = Blueprint("backup", __name__)


@backup_bp.get("/descargar")
def descargar_backup():
    """Descarga inmediata del backup completo (base de datos + fotos +
    firmas) en un ZIP. Guárdalo en tu Google Drive, Dropbox o donde
    prefieras — fuera de Railway, para que valga como copia real."""
    nombre_archivo, buffer = crear_backup_zip()
    return send_file(buffer, mimetype="application/zip", download_name=nombre_archivo)


@backup_bp.post("/enviar-telegram")
def enviar_backup_telegram():
    """Genera el backup y te lo manda como archivo a tu Telegram —
    útil para tenerlo guardado fuera de Railway sin descargarlo tú
    mismo cada vez."""
    nombre_archivo, buffer = crear_backup_zip()
    ok, detalle = enviar_documento_telegram(nombre_archivo, buffer.read(), caption=f"📦 Backup de Firztnet — {nombre_archivo}")
    return jsonify({"ok": ok, "detalle": detalle}), (200 if ok else 400)
