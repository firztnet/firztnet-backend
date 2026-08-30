from flask import Blueprint, request, jsonify
from app import db
from app.models import ChecklistItem

checklist_bp = Blueprint("checklist", __name__)


@checklist_bp.patch("/<int:item_id>")
def marcar_checklist(item_id):
    """Marca o desmarca un punto de la hoja de trabajo."""
    item = ChecklistItem.query.get_or_404(item_id)
    data = request.get_json() or {}
    if "completado" in data:
        item.completado = bool(data["completado"])
    if "texto" in data:
        item.texto = data["texto"]
    db.session.commit()
    return jsonify(item.to_dict())


@checklist_bp.delete("/<int:item_id>")
def borrar_checklist(item_id):
    item = ChecklistItem.query.get_or_404(item_id)
    db.session.delete(item)
    db.session.commit()
    return jsonify({"eliminado": True})
