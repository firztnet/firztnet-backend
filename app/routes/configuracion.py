from flask import Blueprint, request, jsonify
from app import db
from app.models import ConfiguracionNegocio

configuracion_bp = Blueprint("configuracion", __name__)


@configuracion_bp.get("")
def obtener_configuracion():
    return jsonify(ConfiguracionNegocio.obtener().to_dict())


@configuracion_bp.put("")
def actualizar_configuracion():
    config = ConfiguracionNegocio.obtener()
    data = request.get_json() or {}
    config.nombre_negocio = data.get("nombre_negocio", config.nombre_negocio)
    config.eslogan = data.get("eslogan", config.eslogan)
    config.direccion = data.get("direccion", config.direccion)
    config.telefono = data.get("telefono", config.telefono)
    config.email = data.get("email", config.email)
    config.nif = data.get("nif", config.nif)
    if "iva_pct" in data:
        try:
            config.iva_pct = float(data["iva_pct"])
        except (TypeError, ValueError):
            pass
    if "suplemento_desplazamiento" in data:
        try:
            config.suplemento_desplazamiento = float(data["suplemento_desplazamiento"])
        except (TypeError, ValueError):
            pass
    db.session.commit()
    return jsonify(config.to_dict())
