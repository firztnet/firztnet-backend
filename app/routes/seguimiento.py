from urllib.parse import quote
from flask import Blueprint, jsonify
from app.models import Reparacion, ConfiguracionNegocio

seguimiento_bp = Blueprint("seguimiento", __name__)

ETIQUETAS_ESTADO = {
    "recibido": "Recibido",
    "diagnostico": "En diagnóstico",
    "reparacion": "En reparación",
    "listo": "Listo para recoger",
    "entregado": "Entregado",
    "no_reparable": "No reparable",
}


def _enlace_whatsapp_negocio(telefono, numero_orden):
    if not telefono:
        return None
    solo_digitos = "".join(ch for ch in telefono if ch.isdigit())
    if not solo_digitos.startswith("34") and len(solo_digitos) == 9:
        solo_digitos = "34" + solo_digitos  # prefijo España si no lo trae
    mensaje = quote(f"Hola, quería preguntar por mi reparación nº {numero_orden}")
    return f"https://wa.me/{solo_digitos}?text={mensaje}"


@seguimiento_bp.get("/<token>")
def consultar_seguimiento(token):
    """Ruta pública (sin login) para que el cliente vea el estado de su
    reparación con el enlace que le mandamos. Solo devuelve información
    no sensible — nada de precios, datos de contacto de otros clientes,
    ni nada del negocio en general."""
    reparacion = Reparacion.query.filter_by(token_seguimiento=token).first()
    if not reparacion:
        return jsonify({"error": "No se encontró ninguna reparación con ese enlace"}), 404

    negocio = ConfiguracionNegocio.obtener()

    return jsonify({
        "numero_orden": reparacion.numero_orden,
        "equipo": reparacion.equipo,
        "estado_actual": reparacion.estado_actual,
        "estado_label": ETIQUETAS_ESTADO.get(reparacion.estado_actual, reparacion.estado_actual),
        "fecha_recepcion": reparacion.fecha_recepcion.isoformat() if reparacion.fecha_recepcion else None,
        "fecha_estimada": reparacion.fecha_estimada.isoformat() if reparacion.fecha_estimada else None,
        "fecha_entrega": reparacion.fecha_entrega.isoformat() if reparacion.fecha_entrega else None,
        "fecha_fin_garantia": reparacion.fecha_fin_garantia.isoformat() if reparacion.fecha_fin_garantia else None,
        "motivo_no_reparable": reparacion.motivo_no_reparable if reparacion.estado_actual == "no_reparable" else None,
        "enlace_whatsapp_negocio": _enlace_whatsapp_negocio(negocio.telefono, reparacion.numero_orden),
    })
