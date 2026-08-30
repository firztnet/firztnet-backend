from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import RMA, Proveedor

rma_bp = Blueprint("rma", __name__)


@rma_bp.get("")
def listar_rmas():
    """Por defecto todos, o filtrado por ?estado=enviado|en_proceso|resuelto|rechazado."""
    query = RMA.query
    estado = request.args.get("estado")
    if estado:
        query = query.filter_by(estado=estado)
    rmas = query.order_by(RMA.fecha_envio.desc()).all()
    return jsonify([r.to_dict() for r in rmas])


@rma_bp.post("")
def crear_rma():
    data = request.get_json() or {}
    if not data.get("proveedor_id") or not data.get("motivo"):
        return jsonify({"error": "Proveedor y motivo son obligatorios"}), 400

    Proveedor.query.get_or_404(data["proveedor_id"])

    rma = RMA(
        repuesto_id=data.get("repuesto_id"),
        proveedor_id=data["proveedor_id"],
        reparacion_id=data.get("reparacion_id"),
        numero_serie=data.get("numero_serie"),
        motivo=data["motivo"],
    )
    db.session.add(rma)
    db.session.commit()
    return jsonify(rma.to_dict()), 201


@rma_bp.patch("/<int:rma_id>")
def actualizar_rma(rma_id):
    rma = RMA.query.get_or_404(rma_id)
    data = request.get_json() or {}

    if "estado" in data:
        rma.estado = data["estado"]
        if data["estado"] in ("resuelto", "rechazado") and not rma.fecha_resolucion:
            rma.fecha_resolucion = datetime.utcnow()
    if "resultado" in data:
        rma.resultado = data["resultado"]
    if "importe_recuperado" in data:
        rma.importe_recuperado = data["importe_recuperado"]

    db.session.commit()
    return jsonify(rma.to_dict())


@rma_bp.delete("/<int:rma_id>")
def borrar_rma(rma_id):
    rma = RMA.query.get_or_404(rma_id)
    db.session.delete(rma)
    db.session.commit()
    return jsonify({"eliminado": True})
