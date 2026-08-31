from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import Reparacion, Cliente, ReparacionRepuesto, Repuesto, Firma, PlantillaMensaje, ChecklistItem
from app.firmas import guardar_firma_png
from app.notificaciones import renderizar_plantilla, generar_enlace_whatsapp_texto

reparaciones_bp = Blueprint("reparaciones", __name__)


def generar_numero_orden():
    """Nº correlativo por año, ej: 2026-0001, 2026-0002..."""
    anio = datetime.utcnow().year
    ultima = (
        Reparacion.query.filter(Reparacion.numero_orden.like(f"{anio}-%"))
        .order_by(Reparacion.id.desc())
        .first()
    )
    siguiente = 1
    if ultima:
        siguiente = int(ultima.numero_orden.split("-")[1]) + 1
    return f"{anio}-{siguiente:04d}"


@reparaciones_bp.get("")
def listar_reparaciones():
    """Soporta ?estado=diagnostico y ?q=busqueda para el kanban y el buscador."""
    estado = request.args.get("estado")
    q = request.args.get("q", "").strip()

    query = Reparacion.query
    if estado:
        query = query.filter_by(estado_actual=estado)
    if q:
        query = query.join(Cliente).filter(
            db.or_(
                Reparacion.numero_orden.ilike(f"%{q}%"),
                Reparacion.equipo.ilike(f"%{q}%"),
                Cliente.nombre.ilike(f"%{q}%"),
            )
        )
    reparaciones = query.order_by(Reparacion.fecha_recepcion.desc()).all()
    return jsonify([r.to_dict() for r in reparaciones])


@reparaciones_bp.post("")
def crear_reparacion():
    """Da de alta la reparación (recepción del equipo)."""
    data = request.get_json() or {}
    for campo in ("cliente_id", "equipo"):
        if not data.get(campo):
            return jsonify({"error": f"El campo '{campo}' es obligatorio"}), 400

    reparacion = Reparacion(
        numero_orden=generar_numero_orden(),
        cliente_id=data["cliente_id"],
        equipo=data["equipo"],
        tipo_trabajo=data.get("tipo_trabajo", "taller"),
        categoria=data.get("categoria"),
        direccion_servicio=data.get("direccion_servicio"),
        marca=data.get("marca"),
        modelo=data.get("modelo"),
        urgente=bool(data.get("urgente", False)),
        tecnico=data.get("tecnico"),
        accesorios_entregados=data.get("accesorios_entregados"),
        problema_reportado=data.get("problema_reportado"),
        estado_entrada=data.get("estado_entrada"),
        estado_actual="contratado" if data.get("tipo_trabajo") == "domicilio" else "recibido",
    )
    if data.get("fecha_estimada"):
        reparacion.fecha_estimada = datetime.fromisoformat(data["fecha_estimada"])
    db.session.add(reparacion)
    db.session.commit()

    if reparacion.urgente:
        from app.notificaciones import enviar_telegram
        cliente_nombre = reparacion.cliente.nombre if reparacion.cliente else "—"
        enviar_telegram(f"🚨 Aviso URGENTE nuevo: {cliente_nombre} — {reparacion.equipo} (orden {reparacion.numero_orden})")

    return jsonify(reparacion.to_dict()), 201


@reparaciones_bp.get("/<int:rep_id>")
def obtener_reparacion(rep_id):
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = reparacion.to_dict()
    data["repuestos_usados"] = [rr.to_dict() for rr in reparacion.repuestos_usados]
    data["movimientos"] = [m.to_dict() for m in reparacion.movimientos]
    data["checklist"] = [c.to_dict() for c in ChecklistItem.query.filter_by(reparacion_id=rep_id).order_by(ChecklistItem.orden).all()]
    data["firmas"] = [f.to_dict() for f in Firma.query.filter_by(reparacion_id=rep_id).order_by(Firma.fecha.desc()).all()]
    return jsonify(data)


@reparaciones_bp.patch("/<int:rep_id>")
def editar_reparacion(rep_id):
    """Para editar campos sueltos después de crearla, como la fecha
    estimada de entrega (si al principio no la sabías)."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    if "fecha_estimada" in data:
        reparacion.fecha_estimada = datetime.fromisoformat(data["fecha_estimada"]) if data["fecha_estimada"] else None
    if "urgente" in data:
        reparacion.urgente = bool(data["urgente"])
    if "marca" in data:
        reparacion.marca = data["marca"]
    if "modelo" in data:
        reparacion.modelo = data["modelo"]
    if "direccion_servicio" in data:
        reparacion.direccion_servicio = data["direccion_servicio"]
    if "categoria" in data:
        reparacion.categoria = data["categoria"]
    if "tecnico" in data:
        reparacion.tecnico = data["tecnico"]
    if "wifi_ssid" in data:
        reparacion.wifi_ssid = data["wifi_ssid"]
    if "wifi_password" in data:
        reparacion.wifi_password = data["wifi_password"]
    db.session.commit()
    return jsonify(reparacion.to_dict())


@reparaciones_bp.patch("/<int:rep_id>/estado")
def cambiar_estado(rep_id):
    """Mueve la reparación en el kanban. Estados especiales (entregado,
    no_reparable) disparan la lógica adicional (garantía, motivo)."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    nuevo_estado = data.get("estado")
    if not nuevo_estado:
        return jsonify({"error": "Falta el campo 'estado'"}), 400

    if nuevo_estado == "entregado":
        venia_de_no_reparable = reparacion.estado_actual == "no_reparable"
        reparacion.marcar_entregada(con_garantia=not venia_de_no_reparable)
    elif nuevo_estado == "completado":
        reparacion.marcar_completada()
    elif nuevo_estado == "no_reparable":
        if not data.get("motivo"):
            return jsonify({"error": "Indica el motivo de no reparable"}), 400
        reparacion.marcar_no_reparable(data["motivo"])
    else:
        reparacion.estado_actual = nuevo_estado

    if nuevo_estado == "listo" and not reparacion.fecha_listo:
        reparacion.fecha_listo = datetime.utcnow()

    db.session.commit()

    respuesta = reparacion.to_dict()

    # Si hay una plantilla configurada para este estado, se devuelve ya
    # redactada y con el enlace de WhatsApp listo — sin que el técnico
    # tenga que escribir nada.
    plantillas_disparadas = PlantillaMensaje.query.filter_by(estado_disparador=nuevo_estado).all()
    if plantillas_disparadas:
        respuesta["avisos"] = []
        for plantilla in plantillas_disparadas:
            texto = renderizar_plantilla(plantilla.texto, reparacion)
            respuesta["avisos"].append({
                "nombre": plantilla.nombre,
                "texto": texto,
                "enlace_whatsapp": generar_enlace_whatsapp_texto(reparacion, texto),
            })

    return jsonify(respuesta)


@reparaciones_bp.post("/<int:rep_id>/repuestos")
def añadir_repuesto(rep_id):
    """Asocia un repuesto usado a la reparación y descuenta stock. Los
    campos de trazabilidad (numero_serie, proveedor_compra_id,
    numero_factura_compra, fecha_compra) son opcionales."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    repuesto = Repuesto.query.get_or_404(data.get("repuesto_id"))
    cantidad = int(data.get("cantidad", 1))

    if repuesto.stock_actual < cantidad:
        return jsonify({"error": "Stock insuficiente de ese repuesto"}), 400

    uso = ReparacionRepuesto(
        reparacion_id=reparacion.id,
        repuesto_id=repuesto.id,
        cantidad=cantidad,
        precio_aplicado=data.get("precio_aplicado", repuesto.precio_venta),
        numero_serie=data.get("numero_serie"),
        proveedor_compra_id=data.get("proveedor_compra_id") or repuesto.proveedor_id,
        numero_factura_compra=data.get("numero_factura_compra"),
        fecha_compra=datetime.fromisoformat(data["fecha_compra"]).date() if data.get("fecha_compra") else None,
    )
    repuesto.stock_actual -= cantidad
    db.session.add(uso)
    db.session.commit()
    return jsonify(uso.to_dict()), 201



@reparaciones_bp.post("/<int:rep_id>/firma-entrega")
def firmar_entrega(rep_id):
    """Firma del cliente al recoger el equipo, dibujada en el mostrador
    (tablet o móvil del negocio, con tu sesión iniciada)."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    firma_png = data.get("firma_png")
    if not firma_png:
        return jsonify({"error": "Falta la firma"}), 400

    nombre_archivo, _ = guardar_firma_png(firma_png, reparacion.id, "entrega")
    firma = Firma(
        reparacion_id=reparacion.id,
        tipo="entrega",
        nombre_firmante=data.get("nombre_firmante") or (reparacion.cliente.nombre if reparacion.cliente else None),
        nombre_archivo=nombre_archivo,
    )
    db.session.add(firma)
    db.session.commit()
    return jsonify(firma.to_dict()), 201


@reparaciones_bp.get("/<int:rep_id>/firmas")
def listar_firmas(rep_id):
    firmas = Firma.query.filter_by(reparacion_id=rep_id).order_by(Firma.fecha.desc()).all()
    return jsonify([f.to_dict() for f in firmas])


@reparaciones_bp.post("/<int:rep_id>/checklist")
def añadir_checklist(rep_id):
    """Añade un punto a la hoja de trabajo de campo (ej. 'Router revisado')."""
    Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    if not data.get("texto"):
        return jsonify({"error": "Falta el texto del punto"}), 400

    ultimo_orden = db.session.query(db.func.max(ChecklistItem.orden)).filter_by(reparacion_id=rep_id).scalar() or 0
    item = ChecklistItem(reparacion_id=rep_id, texto=data["texto"], orden=ultimo_orden + 1)
    db.session.add(item)
    db.session.commit()
    return jsonify(item.to_dict()), 201


@reparaciones_bp.get("/buscar-serie/<numero_serie>")
def buscar_por_serie(numero_serie):
    """Trazabilidad: dado un nº de serie, dice en qué reparación se usó,
    a qué proveedor se le compró, con qué factura y en qué fecha —
    para tramitar la garantía sin buscar papeles."""
    uso = ReparacionRepuesto.query.filter_by(numero_serie=numero_serie).order_by(ReparacionRepuesto.id.desc()).first()
    if not uso:
        return jsonify({"error": "No se encontró ningún repuesto con ese número de serie"}), 404

    reparacion = Reparacion.query.get(uso.reparacion_id)
    resultado = uso.to_dict()
    resultado["reparacion"] = {
        "id": reparacion.id,
        "numero_orden": reparacion.numero_orden,
        "cliente": reparacion.cliente.to_dict() if reparacion.cliente else None,
        "equipo": reparacion.equipo,
        "fecha_entrega": reparacion.fecha_entrega.isoformat() if reparacion.fecha_entrega else None,
    } if reparacion else None
    return jsonify(resultado)


@reparaciones_bp.post("/<int:rep_id>/cobrar-y-facturar")
def cobrar_y_facturar(rep_id):
    """1 clic: registra el cobro Y emite la factura de golpe, sobre el
    total acumulado de la reparación (incluyendo este cobro)."""
    from decimal import Decimal
    from app.models import MovimientoFinanciero, Factura, ConfiguracionNegocio
    from app.routes.facturas import generar_numero_factura

    reparacion = Reparacion.query.get_or_404(rep_id)
    if not reparacion.cliente:
        return jsonify({"error": "Esta reparación no tiene cliente asociado"}), 400

    if Factura.query.filter_by(reparacion_id=rep_id).first():
        return jsonify({"error": "Esta reparación ya tiene una factura emitida. Genera una nueva reparación o usa el cobro normal sin refacturar."}), 400

    data = request.get_json() or {}
    if not data.get("monto"):
        return jsonify({"error": "El monto es obligatorio"}), 400

    movimiento = MovimientoFinanciero(
        reparacion_id=rep_id,
        tipo="ingreso",
        concepto=data.get("concepto") or "Reparación",
        monto=data["monto"],
        metodo_pago=data.get("metodo_pago"),
    )
    db.session.add(movimiento)
    db.session.flush()  # para que el cobro ya cuente en el total antes de facturar

    ingresos = MovimientoFinanciero.query.filter_by(reparacion_id=rep_id, tipo="ingreso").all()
    total_cobrado = sum((m.monto for m in ingresos), Decimal("0"))

    negocio = ConfiguracionNegocio.obtener()
    iva_pct = negocio.iva_pct if negocio.iva_pct is not None else Decimal("21")
    base_imponible = (total_cobrado / (1 + iva_pct / 100)).quantize(Decimal("0.01"))
    iva_importe = (total_cobrado - base_imponible).quantize(Decimal("0.01"))

    factura = Factura(
        numero=generar_numero_factura(),
        reparacion_id=rep_id,
        cliente_id=reparacion.cliente.id,
        concepto=data.get("concepto_factura") or f"Reparación de {reparacion.equipo}",
        base_imponible=base_imponible,
        iva_pct=iva_pct,
        iva_importe=iva_importe,
        total=total_cobrado,
    )
    db.session.add(factura)
    db.session.commit()

    return jsonify({"movimiento": movimiento.to_dict(), "factura": factura.to_dict()}), 201
