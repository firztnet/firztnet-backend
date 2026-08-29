from urllib.parse import quote
from flask import Blueprint, jsonify, request
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

MENSAJE_NO_ENCONTRADO = "No se encontró ninguna reparación con esos datos"


def _enlace_whatsapp_negocio(telefono, numero_orden):
    if not telefono:
        return None
    solo_digitos = "".join(ch for ch in telefono if ch.isdigit())
    if not solo_digitos.startswith("34") and len(solo_digitos) == 9:
        solo_digitos = "34" + solo_digitos  # prefijo España si no lo trae
    mensaje = quote(f"Hola, quería preguntar por mi reparación nº {numero_orden}")
    return f"https://wa.me/{solo_digitos}?text={mensaje}"


def _respuesta_seguimiento(reparacion):
    """Solo información no sensible — nada de precios, datos de otros
    clientes, ni nada del negocio en general."""
    negocio = ConfiguracionNegocio.obtener()
    return {
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
    }


@seguimiento_bp.get("/<token>")
def consultar_seguimiento(token):
    """Ruta pública (sin login) para el enlace que le mandamos al
    cliente por email/WhatsApp — el token ya identifica su reparación,
    sin más comprobación."""
    reparacion = Reparacion.query.filter_by(token_seguimiento=token).first()
    if not reparacion:
        return jsonify({"error": "No se encontró ninguna reparación con ese enlace"}), 404
    return jsonify(_respuesta_seguimiento(reparacion))


@seguimiento_bp.post("/buscar")
def buscar_por_numero_y_dato():
    """Segunda vía de acceso: si el cliente perdió el enlace pero
    recuerda su nº de orden, puede consultarlo con su DNI o teléfono
    como comprobación (para que no sea tan simple mirar reparaciones
    ajenas solo probando números de orden, que son correlativos)."""
    data = request.get_json() or {}
    numero_orden = (data.get("numero_orden") or "").strip()
    identificador = (data.get("identificador") or "").strip()

    if not numero_orden or not identificador:
        return jsonify({"error": "Indica el nº de orden y tu DNI o teléfono"}), 400

    reparacion = Reparacion.query.filter_by(numero_orden=numero_orden).first()
    if not reparacion or not reparacion.cliente:
        return jsonify({"error": MENSAJE_NO_ENCONTRADO}), 404

    cliente = reparacion.cliente
    id_normalizado = identificador.upper().replace(" ", "").replace("-", "")
    coincide_nif = bool(cliente.nif) and cliente.nif.upper().replace(" ", "").replace("-", "") == id_normalizado

    solo_digitos_input = "".join(ch for ch in identificador if ch.isdigit())
    solo_digitos_telefono = "".join(ch for ch in (cliente.telefono or "") if ch.isdigit())
    coincide_telefono = bool(solo_digitos_input) and solo_digitos_input in solo_digitos_telefono

    if not (coincide_nif or coincide_telefono):
        return jsonify({"error": MENSAJE_NO_ENCONTRADO}), 404

    return jsonify(_respuesta_seguimiento(reparacion))
