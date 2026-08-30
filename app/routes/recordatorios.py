from datetime import date, timedelta
from flask import Blueprint, request, jsonify
from app import db
from app.models import Recordatorio, Cliente

recordatorios_bp = Blueprint("recordatorios", __name__)


@recordatorios_bp.get("")
def listar_recordatorios():
    """Por defecto, solo los pendientes, ordenados por fecha (los más
    próximos o ya vencidos primero). Usa ?todos=true para verlos todos."""
    query = Recordatorio.query
    if request.args.get("todos") != "true":
        query = query.filter_by(cumplido=False)
    recordatorios = query.order_by(Recordatorio.fecha_programada).all()
    return jsonify([r.to_dict() for r in recordatorios])


@recordatorios_bp.post("")
def crear_recordatorio():
    data = request.get_json() or {}
    if not data.get("cliente_id") or not data.get("texto"):
        return jsonify({"error": "Cliente y texto son obligatorios"}), 400

    Cliente.query.get_or_404(data["cliente_id"])

    if data.get("meses"):
        fecha_programada = date.today() + timedelta(days=30 * int(data["meses"]))
    elif data.get("fecha_programada"):
        fecha_programada = date.fromisoformat(data["fecha_programada"])
    else:
        return jsonify({"error": "Indica 'meses' (6 o 12) o una fecha concreta"}), 400

    recordatorio = Recordatorio(
        reparacion_id=data.get("reparacion_id"),
        cliente_id=data["cliente_id"],
        texto=data["texto"],
        fecha_programada=fecha_programada,
    )
    db.session.add(recordatorio)
    db.session.commit()
    return jsonify(recordatorio.to_dict()), 201


@recordatorios_bp.patch("/<int:recordatorio_id>")
def marcar_recordatorio(recordatorio_id):
    recordatorio = Recordatorio.query.get_or_404(recordatorio_id)
    data = request.get_json() or {}
    if "cumplido" in data:
        recordatorio.cumplido = bool(data["cumplido"])
    db.session.commit()
    return jsonify(recordatorio.to_dict())


@recordatorios_bp.delete("/<int:recordatorio_id>")
def borrar_recordatorio(recordatorio_id):
    recordatorio = Recordatorio.query.get_or_404(recordatorio_id)
    db.session.delete(recordatorio)
    db.session.commit()
    return jsonify({"eliminado": True})
