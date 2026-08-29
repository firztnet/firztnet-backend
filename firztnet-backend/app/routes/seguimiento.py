from urllib.parse import quote
from datetime import datetime
from flask import Blueprint, jsonify, request
from app import db
from app.models import Reparacion, ConfiguracionNegocio, Firma
from app.firmas import guardar_firma_png

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
    clientes, ni nada del negocio en general. Sí incluye el propio
    token: si el cliente llegó aquí por token o tras identificarse con
    nº de orden + DNI/teléfono, ya ha demostrado que es su reparación,
    y lo necesita para poder firmar el presupuesto después."""
    negocio = ConfiguracionNegocio.obtener()
    return {
        "token_seguimiento": reparacion.token_seguimiento,
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
        "presupuesto": {
            "importe": float(reparacion.presupuesto_importe),
            "descripcion": reparacion.presupuesto_descripcion,
            "estado": reparacion.presupuesto_estado,
        } if reparacion.presupuesto_importe is not None else None,
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


@seguimiento_bp.post("/<token>/presupuesto/firmar")
def firmar_presupuesto(token):
    """El cliente acepta o rechaza el presupuesto, con firma dibujada
    en pantalla (o solo un clic de rechazo, que no necesita firma)."""
    reparacion = Reparacion.query.filter_by(token_seguimiento=token).first()
    if not reparacion:
        return jsonify({"error": "No se encontró ninguna reparación con ese enlace"}), 404
    if reparacion.presupuesto_importe is None:
        return jsonify({"error": "Esta reparación no tiene ningún presupuesto pendiente"}), 400

    data = request.get_json() or {}
    aceptado = data.get("aceptado")
    if aceptado is None:
        return jsonify({"error": "Falta indicar si se acepta o rechaza"}), 400

    reparacion.presupuesto_estado = "aceptado" if aceptado else "rechazado"

    if aceptado:
        firma_png = data.get("firma_png")
        if not firma_png:
            return jsonify({"error": "Falta la firma para aceptar el presupuesto"}), 400
        nombre_archivo, _ = guardar_firma_png(firma_png, reparacion.id, "presupuesto")
        firma = Firma(
            reparacion_id=reparacion.id,
            tipo="presupuesto",
            nombre_firmante=data.get("nombre_firmante") or (reparacion.cliente.nombre if reparacion.cliente else None),
            nombre_archivo=nombre_archivo,
        )
        db.session.add(firma)

        # Al aceptar el presupuesto mientras el equipo está en diagnóstico,
        # avanza sola a "En reparación" — el cliente ya dio luz verde para
        # empezar a trabajar en ello.
        if reparacion.estado_actual == "diagnostico":
            reparacion.estado_actual = "reparacion"

    db.session.commit()
    return jsonify(_respuesta_seguimiento(reparacion))
