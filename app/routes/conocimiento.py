from flask import Blueprint, request, jsonify
from app import db
from app.models import ArticuloConocimiento

conocimiento_bp = Blueprint("conocimiento", __name__)


@conocimiento_bp.get("")
def buscar_articulos():
    """Búsqueda simple por texto (título o contenido) y/o categoría."""
    q = request.args.get("q", "").strip()
    categoria = request.args.get("categoria", "").strip()

    query = ArticuloConocimiento.query
    if q:
        like = f"%{q}%"
        query = query.filter(db.or_(ArticuloConocimiento.titulo.ilike(like), ArticuloConocimiento.contenido.ilike(like)))
    if categoria:
        query = query.filter_by(categoria=categoria)

    articulos = query.order_by(ArticuloConocimiento.titulo).all()
    return jsonify([a.to_dict() for a in articulos])


@conocimiento_bp.post("")
def crear_articulo():
    data = request.get_json() or {}
    if not data.get("titulo") or not data.get("contenido"):
        return jsonify({"error": "Título y contenido son obligatorios"}), 400

    articulo = ArticuloConocimiento(titulo=data["titulo"], contenido=data["contenido"], categoria=data.get("categoria"))
    db.session.add(articulo)
    db.session.commit()
    return jsonify(articulo.to_dict()), 201


@conocimiento_bp.put("/<int:articulo_id>")
def editar_articulo(articulo_id):
    articulo = ArticuloConocimiento.query.get_or_404(articulo_id)
    data = request.get_json() or {}
    articulo.titulo = data.get("titulo", articulo.titulo)
    articulo.contenido = data.get("contenido", articulo.contenido)
    articulo.categoria = data.get("categoria", articulo.categoria)
    db.session.commit()
    return jsonify(articulo.to_dict())


@conocimiento_bp.delete("/<int:articulo_id>")
def borrar_articulo(articulo_id):
    articulo = ArticuloConocimiento.query.get_or_404(articulo_id)
    db.session.delete(articulo)
    db.session.commit()
    return jsonify({"eliminado": True})
