import uuid
from flask import Blueprint, request, jsonify, send_file
from app import db
from app.models import Comprobante, Reparacion
from app.pdf_generator import generar_pdf_comprobante
from app.notificaciones import enviar_email_comprobante, generar_enlace_whatsapp

comprobantes_bp = Blueprint("comprobantes", __name__)


@comprobantes_bp.post("")
def generar_comprobante():
    """Registra el comprobante (tipo + enlace de seguimiento). El PDF NO
    se guarda en disco — se regenera al vuelo cada vez que se pide
    (ver /comprobantes/<id>/pdf), porque el almacenamiento en Railway
    es efímero y un archivo guardado podría desaparecer entre peticiones."""
    data = request.get_json() or {}
    reparacion = Reparacion.query.get_or_404(data.get("reparacion_id"))
    tipo = data.get("tipo", "recepcion")

    enlace = f"https://firztnet.example/seguimiento/{reparacion.numero_orden}-{uuid.uuid4().hex[:6]}"

    comprobante = Comprobante(
        reparacion_id=reparacion.id,
        tipo=tipo,
        enlace_seguimiento=enlace,
    )
    db.session.add(comprobante)
    db.session.commit()

    respuesta = comprobante.to_dict()
    respuesta["enlace_whatsapp"] = generar_enlace_whatsapp(reparacion, tipo)
    return jsonify(respuesta), 201


@comprobantes_bp.get("/<int:comprobante_id>/pdf")
def descargar_pdf(comprobante_id):
    """Genera el PDF en el momento (en memoria) a partir de los datos
    actuales de la reparación, y lo sirve directamente — no depende de
    ningún archivo guardado previamente."""
    comprobante = Comprobante.query.get_or_404(comprobante_id)
    reparacion = Reparacion.query.get_or_404(comprobante.reparacion_id)

    buffer = generar_pdf_comprobante(reparacion, comprobante.tipo, comprobante.enlace_seguimiento)
    nombre_archivo = f"{reparacion.numero_orden}_{comprobante.tipo}.pdf"
    return send_file(buffer, mimetype="application/pdf", download_name=nombre_archivo)


@comprobantes_bp.post("/<int:comprobante_id>/enviar-email")
def enviar_email(comprobante_id):
    """Regenera el PDF en memoria y lo envía por email al cliente.
    Requiere EMAIL_REMITENTE y EMAIL_PASSWORD configurados como
    variables de entorno."""
    comprobante = Comprobante.query.get_or_404(comprobante_id)
    reparacion = Reparacion.query.get_or_404(comprobante.reparacion_id)

    try:
        buffer = generar_pdf_comprobante(reparacion, comprobante.tipo, comprobante.enlace_seguimiento)
        nombre_archivo = f"{reparacion.numero_orden}_{comprobante.tipo}.pdf"
        resultado = enviar_email_comprobante(reparacion, comprobante.tipo, buffer, nombre_archivo)
    except Exception as e:
        return jsonify({"enviado": False, "motivo": str(e)}), 500

    return jsonify(resultado)


@comprobantes_bp.get("/reparacion/<int:rep_id>")
def comprobantes_de_reparacion(rep_id):
    reparacion = Reparacion.query.get_or_404(rep_id)
    return jsonify([c.to_dict() for c in reparacion.comprobantes])
