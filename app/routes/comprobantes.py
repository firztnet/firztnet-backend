import uuid
from flask import Blueprint, request, jsonify
from app import db
from app.models import Comprobante, Reparacion

comprobantes_bp = Blueprint("comprobantes", __name__)


@comprobantes_bp.post("")
def generar_comprobante():
    """Genera un comprobante para una reparación (recepción, entrega o
    no_reparable). La generación real del PDF (con reportlab o WeasyPrint)
    se conecta aquí más adelante — de momento se deja el registro y el
    enlace de seguimiento listos para usar."""
    data = request.get_json() or {}
    reparacion = Reparacion.query.get_or_404(data.get("reparacion_id"))
    tipo = data.get("tipo", "recepcion")

    enlace = f"https://firztnet.example/seguimiento/{reparacion.numero_orden}-{uuid.uuid4().hex[:6]}"

    comprobante = Comprobante(reparacion_id=reparacion.id, tipo=tipo, enlace_seguimiento=enlace)
    db.session.add(comprobante)
    db.session.commit()
    return jsonify(comprobante.to_dict()), 201


@comprobantes_bp.get("/reparacion/<int:rep_id>")
def comprobantes_de_reparacion(rep_id):
    reparacion = Reparacion.query.get_or_404(rep_id)
    return jsonify([c.to_dict() for c in reparacion.comprobantes])
