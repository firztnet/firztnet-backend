import os
import uuid
from flask import Blueprint, request, jsonify, send_from_directory, current_app
from werkzeug.utils import secure_filename
from app import db
from app.models import FotoReparacion, Reparacion

fotos_bp = Blueprint("fotos", __name__)

# En Railway, configura FOTOS_DIR=/data/fotos (el mismo volumen donde
# vive la base de datos) para que las fotos no se pierdan al
# redesplegar. En local, se guardan en una carpeta junto al proyecto.
FOTOS_DIR = os.environ.get("FOTOS_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "fotos_reparacion"))
os.makedirs(FOTOS_DIR, exist_ok=True)

EXTENSIONES_PERMITIDAS = {"jpg", "jpeg", "png", "webp", "heic"}
TAMANO_MAXIMO_POR_FOTO = 10 * 1024 * 1024  # 10 MB — de sobra para una foto de móvil


def _extension_valida(nombre):
    return "." in nombre and nombre.rsplit(".", 1)[1].lower() in EXTENSIONES_PERMITIDAS


def _tamano_archivo(archivo):
    archivo.seek(0, os.SEEK_END)
    tamano = archivo.tell()
    archivo.seek(0)  # importante: hay que rebobinarlo, o luego .save() guardaría un archivo vacío
    return tamano


@fotos_bp.post("/reparaciones/<int:rep_id>/fotos")
def subir_fotos(rep_id):
    """Sube una o varias fotos del estado del equipo al recibirlo.
    Espera un form-data con uno o varios campos 'foto'."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    archivos = request.files.getlist("foto")
    if not archivos:
        return jsonify({"error": "No se recibió ninguna foto"}), 400

    guardadas = []
    demasiado_grandes = []
    for archivo in archivos:
        if not archivo.filename or not _extension_valida(archivo.filename):
            continue
        if _tamano_archivo(archivo) > TAMANO_MAXIMO_POR_FOTO:
            demasiado_grandes.append(archivo.filename)
            continue
        extension = archivo.filename.rsplit(".", 1)[1].lower()
        nombre_unico = f"{rep_id}_{uuid.uuid4().hex[:10]}.{extension}"
        archivo.save(os.path.join(FOTOS_DIR, secure_filename(nombre_unico)))

        foto = FotoReparacion(reparacion_id=rep_id, nombre_archivo=nombre_unico)
        db.session.add(foto)
        guardadas.append(foto)

    if not guardadas:
        if demasiado_grandes:
            return jsonify({"error": f"'{demasiado_grandes[0]}' pesa más de 10 MB — comprime la foto o hazla con menos resolución."}), 400
        return jsonify({"error": "Ningún archivo tenía un formato válido (jpg, png, webp, heic)"}), 400

    db.session.commit()
    # Se devuelve SIEMPRE un array plano (igual que antes) — si alguna foto
    # se descartó por peso, el frontend lo detecta comparando cuántas
    # mandó contra cuántas llegaron guardadas, y avisa sin romper nada.
    return jsonify([f.to_dict() for f in guardadas]), 201


@fotos_bp.get("/reparaciones/<int:rep_id>/fotos")
def listar_fotos(rep_id):
    fotos = FotoReparacion.query.filter_by(reparacion_id=rep_id).order_by(FotoReparacion.fecha_subida).all()
    return jsonify([f.to_dict() for f in fotos])


@fotos_bp.get("/fotos/<int:foto_id>/archivo")
def ver_foto(foto_id):
    foto = FotoReparacion.query.get_or_404(foto_id)
    return send_from_directory(FOTOS_DIR, foto.nombre_archivo)


@fotos_bp.delete("/fotos/<int:foto_id>")
def borrar_foto(foto_id):
    foto = FotoReparacion.query.get_or_404(foto_id)
    ruta = os.path.join(FOTOS_DIR, foto.nombre_archivo)
    if os.path.exists(ruta):
        os.remove(ruta)
    db.session.delete(foto)
    db.session.commit()
    return jsonify({"eliminado": True})
