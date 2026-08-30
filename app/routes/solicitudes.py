from flask import Blueprint, request, jsonify
from app import db
from app.models import SolicitudServicio

solicitudes_bp = Blueprint("solicitudes", __name__)


@solicitudes_bp.get("")
def listar_solicitudes():
    query = SolicitudServicio.query
    if request.args.get("todas") != "true":
        query = query.filter_by(atendida=False)
    solicitudes = query.order_by(SolicitudServicio.fecha.desc()).all()
    return jsonify([s.to_dict() for s in solicitudes])


@solicitudes_bp.patch("/<int:solicitud_id>")
def marcar_solicitud(solicitud_id):
    solicitud = SolicitudServicio.query.get_or_404(solicitud_id)
    data = request.get_json() or {}
    if "atendida" in data:
        solicitud.atendida = bool(data["atendida"])
    db.session.commit()
    return jsonify(solicitud.to_dict())
