from flask import Blueprint, jsonify, send_file
from app.models import Reparacion, MovimientoFinanciero
from app.pdf_generator import generar_pdf_recibo

recibos_bp = Blueprint("recibos", __name__)


@recibos_bp.get("/reparacion/<int:rep_id>/pdf")
def recibo_de_reparacion(rep_id):
    """Recibo con todos los cobros hechos por esta reparación (histórico
    completo). No hace falta generarlo antes — se construye al momento
    con los movimientos ya registrados."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    ingresos = MovimientoFinanciero.query.filter_by(reparacion_id=rep_id, tipo="ingreso").order_by(
        MovimientoFinanciero.fecha
    ).all()
    if not ingresos:
        return jsonify({"error": "Todavía no hay ningún cobro registrado en esta reparación"}), 400

    buffer = generar_pdf_recibo(reparacion, ingresos)
    return send_file(buffer, mimetype="application/pdf", download_name=f"{reparacion.numero_orden}_recibo.pdf")


@recibos_bp.get("/movimiento/<int:movimiento_id>/pdf")
def recibo_de_un_pago(movimiento_id):
    """Recibo provisional de UN solo cobro (ej. una seña/anticipo),
    sin mezclarlo con otros pagos anteriores de la misma reparación —
    útil para dárselo al cliente al instante, justo tras cobrarle."""
    movimiento = MovimientoFinanciero.query.get_or_404(movimiento_id)
    if movimiento.tipo != "ingreso":
        return jsonify({"error": "Ese movimiento no es un cobro"}), 400
    reparacion = Reparacion.query.get_or_404(movimiento.reparacion_id)

    buffer = generar_pdf_recibo(reparacion, [movimiento])
    return send_file(buffer, mimetype="application/pdf", download_name=f"{reparacion.numero_orden}_seña.pdf")
