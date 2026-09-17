from flask import Blueprint, request, jsonify
from app import db
from app.models import Repuesto, MovimientoFinanciero

repuestos_bp = Blueprint("repuestos", __name__)


@repuestos_bp.get("")
def listar_repuestos():
    solo_stock_bajo = request.args.get("stock_bajo") == "true"
    incluir_inactivos = request.args.get("incluir_inactivos") == "true"

    query = Repuesto.query
    if not incluir_inactivos:
        query = query.filter(Repuesto.activo.isnot(False))  # incluye también los que tengan NULL (repuestos antiguos, antes de este campo)
    repuestos = query.order_by(Repuesto.nombre).all()
    resultado = [r.to_dict() for r in repuestos]
    if solo_stock_bajo:
        resultado = [r for r in resultado if r["stock_bajo"]]
    return jsonify(resultado)


@repuestos_bp.post("")
def crear_repuesto():
    data = request.get_json() or {}
    if not data.get("nombre"):
        return jsonify({"error": "El nombre es obligatorio"}), 400

    repuesto = Repuesto(
        nombre=data["nombre"],
        categoria=data.get("categoria"),
        proveedor_id=data.get("proveedor_id"),
        stock_actual=data.get("stock_actual", 0),
        stock_minimo=data.get("stock_minimo", 1),
        precio_compra=data.get("precio_compra", 0),
        precio_venta=data.get("precio_venta", 0),
    )
    db.session.add(repuesto)
    db.session.commit()
    return jsonify(repuesto.to_dict()), 201


@repuestos_bp.patch("/<int:repuesto_id>/stock")
def actualizar_stock(repuesto_id):
    """Para registrar una compra de reposición de stock."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    data = request.get_json() or {}
    cantidad = int(data.get("cantidad", 0))
    repuesto.stock_actual += cantidad
    db.session.commit()
    return jsonify(repuesto.to_dict())


@repuestos_bp.patch("/<int:repuesto_id>")
def editar_repuesto(repuesto_id):
    """Corregir los datos generales de un repuesto (nombre, categoría,
    precios, stock mínimo) — por ejemplo, si te equivocaste al darlo de
    alta. El stock ACTUAL no se toca aquí a propósito: para eso ya
    existen /stock (reponer) y /vender (venta directa), que además
    dejan constancia en Caja — cambiarlo aquí directamente rompería
    ese rastro."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    data = request.get_json() or {}

    if "nombre" in data:
        if not data["nombre"].strip():
            return jsonify({"error": "El nombre no puede quedar vacío"}), 400
        repuesto.nombre = data["nombre"].strip()
    if "categoria" in data:
        repuesto.categoria = data["categoria"]
    if "proveedor_id" in data:
        repuesto.proveedor_id = data["proveedor_id"]
    if "stock_minimo" in data:
        try:
            nuevo_min = int(data["stock_minimo"])
            if nuevo_min < 0:
                return jsonify({"error": "El stock mínimo no puede ser negativo"}), 400
            repuesto.stock_minimo = nuevo_min
        except (TypeError, ValueError):
            return jsonify({"error": "El stock mínimo no es válido"}), 400
    if "precio_compra" in data:
        try:
            nuevo_compra = float(data["precio_compra"])
            if nuevo_compra < 0:
                return jsonify({"error": "El precio de compra no puede ser negativo"}), 400
            repuesto.precio_compra = nuevo_compra
        except (TypeError, ValueError):
            return jsonify({"error": "El precio de compra no es válido"}), 400
    if "precio_venta" in data:
        try:
            nuevo_venta = float(data["precio_venta"])
            if nuevo_venta < 0:
                return jsonify({"error": "El precio de venta no puede ser negativo"}), 400
            repuesto.precio_venta = nuevo_venta
        except (TypeError, ValueError):
            return jsonify({"error": "El precio de venta no es válido"}), 400

    db.session.commit()
    return jsonify(repuesto.to_dict())


@repuestos_bp.post("/<int:repuesto_id>/vender")
def vender_directo(repuesto_id):
    """Vender un repuesto/accesorio suelto (SSD, RAM, cable...) sin
    necesitar ninguna reparación de por medio — descuenta el stock y
    registra el ingreso en Caja en un solo paso."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    data = request.get_json() or {}

    try:
        cantidad = int(data.get("cantidad", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "La cantidad no es válida"}), 400
    if cantidad <= 0:
        return jsonify({"error": "La cantidad debe ser mayor que 0"}), 400
    if cantidad > repuesto.stock_actual:
        return jsonify({"error": f"Solo quedan {repuesto.stock_actual} unidades en stock"}), 400

    precio_unitario = data.get("precio_unitario")
    if precio_unitario is None:
        precio_unitario = float(repuesto.precio_venta or 0)
    else:
        try:
            precio_unitario = float(precio_unitario)
        except (TypeError, ValueError):
            return jsonify({"error": "El precio no es válido"}), 400
    if precio_unitario < 0:
        return jsonify({"error": "El precio no puede ser negativo"}), 400

    repuesto.stock_actual -= cantidad

    monto_total = round(precio_unitario * cantidad, 2)
    movimiento = MovimientoFinanciero(
        reparacion_id=None,  # venta suelta, sin reparación asociada
        tipo="ingreso",
        concepto=f"Venta directa: {repuesto.nombre} x{cantidad}",
        monto=monto_total,
        metodo_pago=data.get("metodo_pago", "efectivo"),
    )
    db.session.add(movimiento)
    db.session.commit()

    return jsonify({
        "repuesto": repuesto.to_dict(),
        "movimiento": movimiento.to_dict(),
    }), 201


@repuestos_bp.delete("/<int:repuesto_id>")
def dar_de_baja(repuesto_id):
    """Baja lógica — no se borra de la base de datos, solo deja de
    aparecer en el listado activo. Así no se rompe el historial de
    reparaciones o ventas antiguas que ya lo usaron."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    repuesto.activo = False
    db.session.commit()
    return jsonify({"ok": True})


@repuestos_bp.post("/<int:repuesto_id>/reactivar")
def reactivar(repuesto_id):
    """Por si te equivocaste dando de baja algo, o vuelves a tenerlo disponible."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    repuesto.activo = True
    db.session.commit()
    return jsonify(repuesto.to_dict())


@repuestos_bp.get("/resumen-capital")
def resumen_capital():
    """Cuánto dinero tienes invertido en el inventario ahora mismo (al
    precio de compra), y cuánto ganarías si vendieras todo el stock
    actual al precio de venta — solo cuenta lo activo."""
    activos = Repuesto.query.filter(Repuesto.activo.isnot(False)).all()

    capital_invertido = sum(r.stock_actual * float(r.precio_compra or 0) for r in activos)
    valor_venta_total = sum(r.stock_actual * float(r.precio_venta or 0) for r in activos)
    ganancia_potencial = valor_venta_total - capital_invertido

    return jsonify({
        "capital_invertido": round(capital_invertido, 2),
        "valor_venta_total": round(valor_venta_total, 2),
        "ganancia_potencial": round(ganancia_potencial, 2),
        "num_productos_activos": len(activos),
    })
