from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import SesionTrabajo, Reparacion, ConfiguracionNegocio

sesiones_bp = Blueprint("sesiones", __name__)


def _minutos_trabajados(sesiones):
    total_segundos = 0
    for s in sesiones:
        fin = s.fin or datetime.utcnow()  # si sigue abierta, cuenta hasta ahora
        total_segundos += (fin - s.inicio).total_seconds()
    return total_segundos / 60


@sesiones_bp.get("/reparaciones/<int:rep_id>/sesiones")
def listar_sesiones(rep_id):
    Reparacion.query.get_or_404(rep_id)
    sesiones = SesionTrabajo.query.filter_by(reparacion_id=rep_id).order_by(SesionTrabajo.inicio).all()
    negocio = ConfiguracionNegocio.obtener()
    minutos = _minutos_trabajados(sesiones)
    return jsonify({
        "sesiones": [s.to_dict() for s in sesiones],
        "minutos_totales": round(minutos, 1),
        "coste_mano_obra": round((minutos / 60) * float(negocio.tarifa_hora or 25), 2),
        "tarifa_hora": float(negocio.tarifa_hora or 25),
        "hay_sesion_abierta": any(s.fin is None for s in sesiones),
    })


@sesiones_bp.post("/reparaciones/<int:rep_id>/sesiones/iniciar")
def iniciar_sesion(rep_id):
    Reparacion.query.get_or_404(rep_id)
    abierta = SesionTrabajo.query.filter_by(reparacion_id=rep_id, fin=None).first()
    if abierta:
        return jsonify({"error": "Ya hay una sesión en marcha para esta reparación"}), 400

    sesion = SesionTrabajo(reparacion_id=rep_id)
    db.session.add(sesion)
    db.session.commit()
    return jsonify(sesion.to_dict()), 201


@sesiones_bp.post("/reparaciones/<int:rep_id>/sesiones/finalizar")
def finalizar_sesion(rep_id):
    abierta = SesionTrabajo.query.filter_by(reparacion_id=rep_id, fin=None).first()
    if not abierta:
        return jsonify({"error": "No hay ninguna sesión en marcha"}), 400

    abierta.fin = datetime.utcnow()
    db.session.commit()
    return jsonify(abierta.to_dict())
