from datetime import datetime
from flask import Blueprint, jsonify, request
from app import db
from app.models import Venta

ventas_bp = Blueprint("ventas", __name__)

NEGOCIOS_VALIDOS = {"firztnet", "firztweb", "afiliados"}
TIPOS_VALIDOS = {"web", "app", "sistema", "afiliado", "otro"}


@ventas_bp.get("")
def listar_ventas():
    """Todas las ventas, más recientes primero. Filtrable por negocio
    con ?negocio=firztweb, y por cobradas/pendientes con ?cobrado=si|no."""
    query = Venta.query
    negocio = request.args.get("negocio")
    if negocio:
        query = query.filter_by(negocio=negocio)
    cobrado = request.args.get("cobrado")
    if cobrado == "si":
        query = query.filter_by(cobrado=True)
    elif cobrado == "no":
        query = query.filter_by(cobrado=False)

    ventas = query.order_by(Venta.fecha.desc(), Venta.id.desc()).all()
    return jsonify([v.to_dict() for v in ventas])


@ventas_bp.post("")
def crear_venta():
    data = request.get_json() or {}

    negocio = (data.get("negocio") or "firztweb").strip().lower()
    if negocio not in NEGOCIOS_VALIDOS:
        return jsonify({"error": "Negocio no reconocido"}), 400

    tipo = (data.get("tipo") or "").strip().lower()
    if tipo not in TIPOS_VALIDOS:
        return jsonify({"error": "Tipo de venta no reconocido"}), 400

    fecha = datetime.utcnow().date()
    if data.get("fecha"):
        try:
            fecha = datetime.strptime(data["fecha"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Fecha en formato incorrecto (usa AAAA-MM-DD)"}), 400

    producto = None
    importe_total_venta = None
    porcentaje_comision = None

    if tipo == "afiliado":
        # En afiliados no hay "cliente" propiamente — pides el producto, el
        # importe total de la venta y el % de comisión, y calculamos el resto.
        producto = (data.get("producto") or "").strip()
        if not producto:
            return jsonify({"error": "El producto es obligatorio en ventas de afiliados"}), 400

        try:
            importe_total_venta = float(data.get("importe_total_venta"))
        except (TypeError, ValueError):
            return jsonify({"error": "El importe total de la venta no es un número válido"}), 400
        if importe_total_venta < 0:
            return jsonify({"error": "El importe total no puede ser negativo"}), 400

        try:
            porcentaje_comision = float(data.get("porcentaje_comision"))
        except (TypeError, ValueError):
            return jsonify({"error": "El porcentaje de comisión no es un número válido"}), 400
        if not (0 <= porcentaje_comision <= 100):
            return jsonify({"error": "El porcentaje de comisión debe estar entre 0 y 100"}), 400

        importe = round(importe_total_venta * porcentaje_comision / 100, 2)
        cliente_nombre = (data.get("cliente_nombre") or "").strip()  # opcional aquí — vacío está bien

    else:
        cliente_nombre = (data.get("cliente_nombre") or "").strip()
        if not cliente_nombre:
            return jsonify({"error": "El nombre del cliente es obligatorio"}), 400

        try:
            importe = float(data.get("importe") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "El importe no es un número válido"}), 400
        if importe < 0:
            return jsonify({"error": "El importe no puede ser negativo"}), 400

    venta = Venta(
        negocio=negocio,
        tipo=tipo,
        producto=producto,
        importe_total_venta=importe_total_venta,
        porcentaje_comision=porcentaje_comision,
        cliente_nombre=cliente_nombre,
        descripcion=data.get("descripcion"),
        importe=importe,
        cobrado=bool(data.get("cobrado")),
        enlace_nota=data.get("enlace_nota"),
        fecha=fecha,
    )
    db.session.add(venta)
    db.session.commit()
    return jsonify(venta.to_dict()), 201


@ventas_bp.patch("/<int:venta_id>")
def actualizar_venta(venta_id):
    """Para marcar como cobrada (o al revés), o corregir cualquier dato.
    Si tocas el importe total o el % de comisión de una venta de
    afiliados, la comisión (el "importe" real) se recalcula sola."""
    venta = Venta.query.get(venta_id)
    if not venta:
        return jsonify({"error": "Venta no encontrada"}), 404

    data = request.get_json() or {}
    if "cobrado" in data:
        venta.cobrado = bool(data["cobrado"])
    if "cliente_nombre" in data and data["cliente_nombre"].strip():
        venta.cliente_nombre = data["cliente_nombre"].strip()
    if "descripcion" in data:
        venta.descripcion = data["descripcion"]
    if "enlace_nota" in data:
        venta.enlace_nota = data["enlace_nota"]
    if "producto" in data and data["producto"].strip():
        venta.producto = data["producto"].strip()

    recalcular_comision = False
    if "importe_total_venta" in data:
        try:
            nuevo_total = float(data["importe_total_venta"])
            if nuevo_total < 0:
                return jsonify({"error": "El importe total no puede ser negativo"}), 400
            venta.importe_total_venta = nuevo_total
            recalcular_comision = True
        except (TypeError, ValueError):
            return jsonify({"error": "El importe total no es un número válido"}), 400
    if "porcentaje_comision" in data:
        try:
            nuevo_pct = float(data["porcentaje_comision"])
            if not (0 <= nuevo_pct <= 100):
                return jsonify({"error": "El porcentaje de comisión debe estar entre 0 y 100"}), 400
            venta.porcentaje_comision = nuevo_pct
            recalcular_comision = True
        except (TypeError, ValueError):
            return jsonify({"error": "El porcentaje de comisión no es un número válido"}), 400

    if recalcular_comision and venta.importe_total_venta is not None and venta.porcentaje_comision is not None:
        venta.importe = round(venta.importe_total_venta * venta.porcentaje_comision / 100, 2)
    elif "importe" in data:
        try:
            nuevo_importe = float(data["importe"])
            if nuevo_importe < 0:
                return jsonify({"error": "El importe no puede ser negativo"}), 400
            venta.importe = nuevo_importe
        except (TypeError, ValueError):
            return jsonify({"error": "El importe no es un número válido"}), 400
    if "tipo" in data:
        if data["tipo"] not in TIPOS_VALIDOS:
            return jsonify({"error": "Tipo de venta no reconocido"}), 400
        venta.tipo = data["tipo"]
    if "negocio" in data:
        if data["negocio"] not in NEGOCIOS_VALIDOS:
            return jsonify({"error": "Negocio no reconocido"}), 400
        venta.negocio = data["negocio"]

    db.session.commit()
    return jsonify(venta.to_dict())


@ventas_bp.delete("/<int:venta_id>")
def borrar_venta(venta_id):
    venta = Venta.query.get(venta_id)
    if not venta:
        return jsonify({"error": "Venta no encontrada"}), 404
    db.session.delete(venta)
    db.session.commit()
    return jsonify({"ok": True})


@ventas_bp.get("/resumen")
def resumen_ventas():
    """Totales por negocio: cuánto se ha vendido, cuánto está cobrado
    y cuánto sigue pendiente."""
    resultado = {}
    for negocio in NEGOCIOS_VALIDOS:
        ventas = Venta.query.filter_by(negocio=negocio).all()
        total = sum(v.importe for v in ventas)
        cobrado = sum(v.importe for v in ventas if v.cobrado)
        pendiente = total - cobrado
        resultado[negocio] = {
            "num_ventas": len(ventas),
            "total": round(total, 2),
            "cobrado": round(cobrado, 2),
            "pendiente": round(pendiente, 2),
        }
    return jsonify(resultado)
