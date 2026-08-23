from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import MovimientoFinanciero

finanzas_bp = Blueprint("finanzas", __name__)


@finanzas_bp.get("")
def listar_movimientos():
    """Soporta ?desde=2026-08-01&hasta=2026-08-31 para filtrar por rango."""
    query = MovimientoFinanciero.query
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        query = query.filter(MovimientoFinanciero.fecha >= datetime.fromisoformat(desde))
    if hasta:
        query = query.filter(MovimientoFinanciero.fecha <= datetime.fromisoformat(hasta))
    movimientos = query.order_by(MovimientoFinanciero.fecha.desc()).all()
    return jsonify([m.to_dict() for m in movimientos])


@finanzas_bp.post("")
def crear_movimiento():
    data = request.get_json() or {}
    if data.get("tipo") not in ("ingreso", "gasto"):
        return jsonify({"error": "El tipo debe ser 'ingreso' o 'gasto'"}), 400
    if not data.get("monto"):
        return jsonify({"error": "El monto es obligatorio"}), 400

    movimiento = MovimientoFinanciero(
        reparacion_id=data.get("reparacion_id"),
        tipo=data["tipo"],
        concepto=data.get("concepto"),
        monto=data["monto"],
        metodo_pago=data.get("metodo_pago"),
    )
    db.session.add(movimiento)
    db.session.commit()
    return jsonify(movimiento.to_dict()), 201
