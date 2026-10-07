from datetime import datetime
from decimal import Decimal
from flask import Blueprint, request, jsonify
from app import db
from app.models import Cliente, NEGOCIOS_CLIENTE

clientes_bp = Blueprint("clientes", __name__)


def generar_codigo_cliente():
    """Nº correlativo simple para identificar al cliente, ej: CLI-0001.

    Se calcula a partir del código más alto que ya existe, no del id de la última fila:
    como ahora hay contactos (sin código) mezclados en la misma tabla, el id ya no sirve
    para esto, y daría códigos repetidos al convertir un contacto antiguo."""
    maximo = 0
    for (codigo,) in db.session.query(Cliente.codigo).filter(Cliente.codigo.like("CLI-%")).all():
        try:
            maximo = max(maximo, int(codigo[4:]))
        except ValueError:
            pass
    return f"CLI-{maximo + 1:04d}"


def _leer_negocios(data):
    """Devuelve (lista, error). Acepta una lista o un texto separado por comas."""
    bruto = data.get("negocios")
    if isinstance(bruto, str):
        bruto = [n.strip() for n in bruto.split(",") if n.strip()]
    if not isinstance(bruto, list) or not bruto:
        return None, "Elige al menos un negocio"
    if any(n not in NEGOCIOS_CLIENTE for n in bruto):
        return None, "Negocio no reconocido"
    return bruto, None


def convertir_en_cliente(cliente):
    """Pasa un contacto a cliente de verdad (le da su código). Si ya lo era, no hace nada."""
    if cliente.es_contacto:
        cliente.es_contacto = False
    if not cliente.codigo:
        cliente.codigo = generar_codigo_cliente()
    return cliente


@clientes_bp.get("")
def listar_clientes():
    q = request.args.get("q", "").strip()
    query = Cliente.query
    if request.args.get("incluir_contactos") != "true":
        query = query.filter(Cliente.es_contacto.isnot(True))
    negocio = request.args.get("negocio")
    if negocio in NEGOCIOS_CLIENTE:
        query = query.filter(Cliente.negocios.like(f"%{negocio}%"))
    if q:
        query = query.filter(Cliente.nombre.ilike(f"%{q}%"))
    clientes = query.order_by(Cliente.nombre).all()
    return jsonify([c.to_dict() for c in clientes])


@clientes_bp.post("")
def crear_cliente():
    data = request.get_json() or {}
    if not data.get("nombre"):
        return jsonify({"error": "El nombre es obligatorio"}), 400

    negocios = ["firztnet"]
    if "negocios" in data:
        negocios, error = _leer_negocios(data)
        if error:
            return jsonify({"error": error}), 400

    telefono = (data.get("telefono") or "").strip()
    contacto = Cliente.query.filter_by(telefono=telefono, es_contacto=True).first() if telefono else None
    if contacto:
        # Ya había escrito por la web: lo convertimos en vez de crear una ficha duplicada.
        contacto.nombre = data["nombre"]
        contacto.email = data.get("email") or contacto.email
        contacto.nif = data.get("nif") or contacto.nif
        contacto.poner_negocios(contacto.lista_negocios() + negocios)  # conserva por dónde escribió y suma lo que elijas
        convertir_en_cliente(contacto)
        db.session.commit()
        return jsonify(contacto.to_dict()), 201

    cliente = Cliente(
        codigo=generar_codigo_cliente(),
        nombre=data["nombre"],
        telefono=data.get("telefono"),
        email=data.get("email"),
        nif=data.get("nif"),
    )
    cliente.poner_negocios(negocios)
    db.session.add(cliente)
    db.session.commit()
    return jsonify(cliente.to_dict()), 201


@clientes_bp.post("/<int:cliente_id>/convertir")
def convertir_cliente(cliente_id):
    """Botón "Convertir en cliente" de las solicitudes que llegan desde las webs."""
    cliente = Cliente.query.get_or_404(cliente_id)
    convertir_en_cliente(cliente)
    db.session.commit()
    return jsonify(cliente.to_dict())


def _resumen_alertas(cliente):
    """Calcula, para un cliente: cuántas reparaciones entregadas no
    tienen ningún cobro registrado, y qué reparaciones siguen dentro
    del plazo de garantía."""
    hoy = datetime.utcnow()
    sin_cobrar = []
    en_garantia = []

    for rep in cliente.reparaciones:
        if rep.estado_actual in ("entregado", "completado"):
            total_cobrado = sum((m.monto for m in rep.movimientos if m.tipo == "ingreso"), Decimal("0"))
            if total_cobrado <= 0:
                sin_cobrar.append({"id": rep.id, "numero_orden": rep.numero_orden, "equipo": rep.equipo})

        if rep.fecha_fin_garantia and rep.fecha_fin_garantia >= hoy:
            en_garantia.append({
                "id": rep.id,
                "numero_orden": rep.numero_orden,
                "equipo": rep.equipo,
                "fecha_fin_garantia": rep.fecha_fin_garantia.isoformat() + "Z",
            })

    return {"sin_cobrar": sin_cobrar, "en_garantia": en_garantia}


@clientes_bp.get("/<int:cliente_id>")
def obtener_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    data = cliente.to_dict()
    data["reparaciones"] = [r.to_dict() for r in cliente.reparaciones]
    data["resumen"] = _resumen_alertas(cliente)
    return jsonify(data)


@clientes_bp.put("/<int:cliente_id>")
def actualizar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    data = request.get_json() or {}
    cliente.nombre = data.get("nombre", cliente.nombre)
    cliente.telefono = data.get("telefono", cliente.telefono)
    cliente.email = data.get("email", cliente.email)
    cliente.nif = data.get("nif", cliente.nif)
    if "negocios" in data:
        negocios, error = _leer_negocios(data)
        if error:
            return jsonify({"error": error}), 400
        cliente.poner_negocios(negocios)
    db.session.commit()
    return jsonify(cliente.to_dict())


@clientes_bp.post("/<int:cliente_id>/rgpd/olvidar")
def olvidar_cliente(cliente_id):
    """Derecho al olvido (RGPD): borra todo lo que se puede borrar
    (nombre, teléfono, email, NIF, fotos, firmas, WiFi guardado,
    dirección, solicitudes y recordatorios), pero CONSERVA lo que la
    ley obliga a guardar por temas fiscales: las facturas — aunque con
    el nombre/NIF ya "congelados" en el momento de emitirlas, así que
    siguen siendo correctas sin necesitar los datos vivos del cliente.

    Las reparaciones en sí (equipo, fechas, cobros) también se
    conservan, porque son necesarias para la contabilidad y el
    historial de garantías — pero ya sin nada que identifique
    personalmente al cliente salvo lo estrictamente fiscal."""
    from app.models import FotoReparacion, Firma, SolicitudServicio, Recordatorio, RegistroRGPD
    from app.firmas import ruta_completa as ruta_firma
    from app.routes.fotos import FOTOS_DIR
    import os

    cliente = Cliente.query.get_or_404(cliente_id)
    data = request.get_json() or {}
    motivo = data.get("motivo", "Solicitud del cliente")

    nombre_original = cliente.nombre
    fotos_borradas = 0
    firmas_borradas = 0

    for rep in cliente.reparaciones:
        # Fotos: se borra el archivo del disco y la fila de la base de datos.
        for foto in FotoReparacion.query.filter_by(reparacion_id=rep.id).all():
            ruta = os.path.join(FOTOS_DIR, foto.nombre_archivo)
            if os.path.exists(ruta):
                os.remove(ruta)
            db.session.delete(foto)
            fotos_borradas += 1

        # Firmas: igual, archivo + fila.
        for firma in Firma.query.filter_by(reparacion_id=rep.id).all():
            ruta = ruta_firma(firma.nombre_archivo)
            if os.path.exists(ruta):
                os.remove(ruta)
            db.session.delete(firma)
            firmas_borradas += 1

        # Datos personales/sensibles dentro de la propia reparación
        # (dirección, WiFi) — el equipo, fechas y cobros SÍ se conservan.
        rep.direccion_servicio = None
        rep.wifi_ssid = None
        rep.wifi_password = None

    # Solicitudes y recordatorios: no hay obligación legal de conservarlos.
    SolicitudServicio.query.filter_by(cliente_id=cliente.id).delete()
    Recordatorio.query.filter_by(cliente_id=cliente.id).delete()

    # El propio cliente: se anonimiza (no se borra la fila entera, para
    # no romper la relación con sus reparaciones/facturas ya existentes).
    cliente.nombre = f"Cliente eliminado (RGPD #{cliente.id})"
    cliente.telefono = None
    cliente.email = None
    cliente.nif = None

    registro = RegistroRGPD(cliente_id=cliente.id, nombre_en_el_momento=nombre_original, motivo=motivo)
    db.session.add(registro)
    db.session.commit()

    return jsonify({
        "ok": True,
        "fotos_borradas": fotos_borradas,
        "firmas_borradas": firmas_borradas,
        "conservado": "Facturas (obligación fiscal) y el historial de reparaciones (equipo, fechas, cobros), ya sin datos personales.",
    })
