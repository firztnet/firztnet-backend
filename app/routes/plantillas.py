from flask import Blueprint, request, jsonify
from app import db
from app.models import PlantillaMensaje

plantillas_bp = Blueprint("plantillas", __name__)


@plantillas_bp.get("")
def listar_plantillas():
    plantillas = PlantillaMensaje.query.order_by(PlantillaMensaje.id).all()
    return jsonify([p.to_dict() for p in plantillas])


@plantillas_bp.post("")
def crear_plantilla():
    data = request.get_json() or {}
    if not data.get("nombre") or not data.get("texto"):
        return jsonify({"error": "Nombre y texto son obligatorios"}), 400

    plantilla = PlantillaMensaje(nombre=data["nombre"], texto=data["texto"], estado_disparador=data.get("estado_disparador") or None)
    db.session.add(plantilla)
    db.session.commit()
    return jsonify(plantilla.to_dict()), 201


@plantillas_bp.put("/<int:plantilla_id>")
def editar_plantilla(plantilla_id):
    plantilla = PlantillaMensaje.query.get_or_404(plantilla_id)
    data = request.get_json() or {}

    if "estado_disparador" in data:
        plantilla.estado_disparador = data["estado_disparador"] or None

    plantilla.nombre = data.get("nombre", plantilla.nombre)
    plantilla.texto = data.get("texto", plantilla.texto)
    db.session.commit()
    return jsonify(plantilla.to_dict())


@plantillas_bp.delete("/<int:plantilla_id>")
def borrar_plantilla(plantilla_id):
    plantilla = PlantillaMensaje.query.get_or_404(plantilla_id)
    db.session.delete(plantilla)
    db.session.commit()
    return jsonify({"eliminado": True})
