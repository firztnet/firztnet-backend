from datetime import datetime
from flask import Blueprint, request, jsonify, send_file
from app import db
from app.models import Reparacion, ConfiguracionNegocio, Firma
from app.pdf_generator import generar_pdf_presupuesto
from app.firmas import ruta_completa

presupuestos_bp = Blueprint("presupuestos", __name__)


@presupuestos_bp.post("/reparaciones/<int:rep_id>/presupuesto")
def crear_o_editar_presupuesto(rep_id):
    """Crea o actualiza el presupuesto de una reparación. Si ya estaba
    aceptado/rechazado y lo cambias, vuelve a quedar pendiente (hay que
    pedir que lo acepte de nuevo)."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    if "importe" not in data:
        return jsonify({"error": "Falta el importe"}), 400

    reparacion.presupuesto_importe = data["importe"]
    reparacion.presupuesto_descripcion = data.get("descripcion")
    reparacion.presupuesto_estado = "pendiente"
    reparacion.presupuesto_fecha = datetime.utcnow()
    db.session.commit()
    return jsonify(reparacion.to_dict())


@presupuestos_bp.get("/reparaciones/<int:rep_id>/presupuesto/pdf")
def descargar_presupuesto(rep_id):
    """Para que tú (el técnico) lo veas o imprimas — regenerado al
    vuelo, incluye la firma si el cliente ya lo aceptó."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    if reparacion.presupuesto_importe is None:
        return jsonify({"error": "Esta reparación todavía no tiene presupuesto"}), 400

    negocio = ConfiguracionNegocio.obtener()
    firma = (
        Firma.query.filter_by(reparacion_id=rep_id, tipo="presupuesto")
        .order_by(Firma.id.desc())
        .first()
    )
    firma_ruta = ruta_completa(firma.nombre_archivo) if firma else None

    buffer = generar_pdf_presupuesto(reparacion, negocio, firma_ruta)
    return send_file(buffer, mimetype="application/pdf", download_name=f"presupuesto_{reparacion.numero_orden}.pdf")
