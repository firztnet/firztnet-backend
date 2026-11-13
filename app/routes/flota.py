"""Flota: los vehículos de la empresa.

- Cada VEHÍCULO guarda sus datos y las próximas fechas: ITV, vencimiento del seguro y
  próximo mantenimiento (por fecha y/o por kilómetros).
- Cada REGISTRO es algo que le ha pasado: ITV pasada, mantenimiento, reparación,
  repostaje, seguro renovado, impuesto... Al registrarlo se ponen al día los kilómetros
  y las próximas fechas, y si tiene coste se puede apuntar como gasto en Caja.
- Los AVISOS (ITV, seguro o mantenimiento vencidos o cerca) salen en la campanita."""
from datetime import date, datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify

from app import db
from app.models import Vehiculo, RegistroVehiculo, MovimientoFinanciero, TIPOS_REGISTRO_VEHICULO
from app.horario import hoy_madrid, a_utc

flota_bp = Blueprint("flota", __name__)

NOMBRE_TIPO = {
    "itv": "ITV",
    "mantenimiento": "Mantenimiento",
    "reparacion": "Reparación",
    "combustible": "Combustible",
    "seguro": "Seguro",
    "impuesto": "Impuesto de circulación",
    "otro": "Otro gasto",
}
COMBUSTIBLES = ("gasolina", "diesel", "hibrido", "electrico", "glp")
DIAS_AVISO = 30      # avisar cuando falten 30 días o menos
KM_AVISO = 1000      # o 1000 km o menos para el mantenimiento


# -------------------- lectura de datos --------------------

def _texto(data, campo, largo):
    valor = (data.get(campo) or "").strip()
    return valor[:largo] or None


def _fecha(valor, campo):
    if valor in (None, ""):
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ValueError(f"La fecha de «{campo}» no es válida")


def _entero(valor, campo, maximo=5_000_000):
    if valor in (None, ""):
        return None
    try:
        n = int(float(str(valor).replace(".", "").replace(",", "."))) if isinstance(valor, str) else int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"«{campo}» tiene que ser un número")
    if n < 0 or n > maximo:
        raise ValueError(f"«{campo}» no es un número válido")
    return n


def _decimal(valor, campo, maximo=1_000_000):
    if valor in (None, ""):
        return None
    try:
        d = Decimal(str(valor).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ValueError(f"«{campo}» tiene que ser un importe válido")
    if d < 0 or d > maximo:
        raise ValueError(f"«{campo}» no es un importe válido")
    return d


def _sumar_meses(fecha, meses):
    mes = fecha.month - 1 + meses
    anio = fecha.year + mes // 12
    mes = mes % 12 + 1
    dias_mes = [31, 29 if (anio % 4 == 0 and (anio % 100 != 0 or anio % 400 == 0)) else 28,
                31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1]
    return date(anio, mes, min(fecha.day, dias_mes))


def _aplicar_datos_vehiculo(v, data, nuevo=False):
    """Copia al vehículo los campos que vienen en `data` (solo los que vienen)."""
    if nuevo or "matricula" in data:
        matricula = (data.get("matricula") or "").strip().upper().replace(" ", "").replace("-", "")
        if not matricula:
            raise ValueError("Escribe la matrícula")
        v.matricula = matricula[:15]
    for campo, largo in (("marca", 60), ("modelo", 60), ("seguro_compania", 80), ("seguro_poliza", 60)):
        if campo in data:
            setattr(v, campo, _texto(data, campo, largo))
    if "notas" in data:
        v.notas = (data.get("notas") or "").strip() or None
    if "combustible" in data:
        c = (data.get("combustible") or "").strip().lower() or None
        if c and c not in COMBUSTIBLES:
            raise ValueError("Combustible no válido")
        v.combustible = c
    if "anio" in data:
        anio = _entero(data.get("anio"), "Año", 2100)
        if anio is not None and anio < 1950:
            raise ValueError("El año no es válido")
        v.anio = anio
    for campo, nombre in (("km_actuales", "Kilómetros"), ("proximo_mant_km", "Próximo mantenimiento (km)"),
                          ("intervalo_mant_km", "Cada cuántos km")):
        if campo in data:
            setattr(v, campo, _entero(data.get(campo), nombre))
    if "intervalo_mant_meses" in data:
        v.intervalo_mant_meses = _entero(data.get("intervalo_mant_meses"), "Cada cuántos meses", 120)
    for campo, nombre in (("fecha_matriculacion", "Matriculación"), ("proxima_itv", "Próxima ITV"),
                          ("seguro_vence", "Vencimiento del seguro"), ("proximo_mant_fecha", "Próximo mantenimiento")):
        if campo in data:
            setattr(v, campo, _fecha(data.get(campo), nombre))
    if "activo" in data:
        v.activo = bool(data.get("activo"))
    if v.km_actuales is None:
        v.km_actuales = 0


# -------------------- avisos y resúmenes --------------------

def _aviso_fecha(fecha, que, hoy):
    if not fecha:
        return None
    dias = (fecha - hoy).days
    if dias < 0:
        hace = f"hace {-dias} {'día' if dias == -1 else 'días'}"
        texto = {"ITV": f"ITV caducada {hace}", "Seguro": f"Seguro vencido {hace}"}.get(que, f"{que} pasado de fecha {hace}")
        return {"que": que, "nivel": "vencido", "dias": dias, "fecha": fecha.isoformat(), "texto": texto}
    if dias <= DIAS_AVISO:
        cuando = "hoy" if dias == 0 else "mañana" if dias == 1 else f"en {dias} días"
        return {"que": que, "nivel": "pronto", "dias": dias, "fecha": fecha.isoformat(), "texto": f"{que} {cuando}"}
    return None


def avisos_de(v, hoy=None):
    hoy = hoy or hoy_madrid()
    avisos = []
    for fecha, que in ((v.proxima_itv, "ITV"), (v.seguro_vence, "Seguro"), (v.proximo_mant_fecha, "Mantenimiento")):
        a = _aviso_fecha(fecha, que, hoy)
        if a:
            avisos.append(a)
    if v.proximo_mant_km:
        faltan = v.proximo_mant_km - (v.km_actuales or 0)
        ya_hay = any(a["que"] == "Mantenimiento" for a in avisos)
        if faltan <= KM_AVISO and not ya_hay:
            if faltan < 0:
                avisos.append({"que": "Mantenimiento", "nivel": "vencido", "km": faltan,
                               "texto": f"Mantenimiento pasado {-faltan:,} km".replace(",", ".")})
            else:
                avisos.append({"que": "Mantenimiento", "nivel": "pronto", "km": faltan,
                               "texto": f"Mantenimiento en {faltan:,} km".replace(",", ".")})
    return avisos


def _gasto_anio(v, anio):
    total = Decimal("0")
    for r in v.registros.filter(RegistroVehiculo.fecha >= date(anio, 1, 1), RegistroVehiculo.fecha <= date(anio, 12, 31)):
        total += r.coste or 0
    return float(total)


def _consumo_medio(v):
    """Litros cada 100 km, con los repostajes que tienen km y litros (desde el primero al último)."""
    llenos = [r for r in v.registros.filter(RegistroVehiculo.tipo == "combustible").all() if r.km and r.litros]
    if len(llenos) < 2:
        return None
    llenos.sort(key=lambda r: (r.km, r.fecha))
    km = llenos[-1].km - llenos[0].km
    if km <= 0:
        return None
    litros = sum(float(r.litros) for r in llenos[1:])  # el primer repostaje solo marca el punto de partida
    return round(litros / km * 100, 1)


def _resumen(v, detalle=False):
    hoy = hoy_madrid()
    datos = v.to_dict()
    datos["nombre"] = v.nombre_corto()
    datos["avisos"] = avisos_de(v, hoy)
    datos["gasto_anio"] = _gasto_anio(v, hoy.year)
    ultimo = v.registros.first()
    datos["ultimo_registro"] = ultimo.to_dict() if ultimo else None
    if detalle:
        datos["registros"] = [r.to_dict() for r in v.registros.all()]
        por_tipo = {}
        for r in v.registros.filter(RegistroVehiculo.fecha >= date(hoy.year, 1, 1)):
            if r.coste:
                por_tipo[r.tipo] = round(por_tipo.get(r.tipo, 0) + float(r.coste), 2)
        datos["gasto_anio_por_tipo"] = por_tipo
        datos["consumo_medio"] = _consumo_medio(v)
    return datos


# -------------------- vehículos --------------------

@flota_bp.get("/vehiculos")
def listar_vehiculos():
    vehiculos = Vehiculo.query.order_by(Vehiculo.activo.desc(), Vehiculo.matricula).all()
    return jsonify([_resumen(v) for v in vehiculos])


@flota_bp.post("/vehiculos")
def crear_vehiculo():
    data = request.get_json() or {}
    v = Vehiculo()
    try:
        _aplicar_datos_vehiculo(v, data, nuevo=True)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if Vehiculo.query.filter_by(matricula=v.matricula).first():
        return jsonify({"error": f"Ya hay un vehículo con la matrícula {v.matricula}"}), 409
    # Si no se indica el próximo mantenimiento pero sí cada cuánto, se calcula desde hoy / los km actuales
    if not v.proximo_mant_km and v.intervalo_mant_km:
        v.proximo_mant_km = (v.km_actuales or 0) + v.intervalo_mant_km
    db.session.add(v)
    db.session.commit()
    return jsonify(_resumen(v, detalle=True)), 201


@flota_bp.get("/vehiculos/<int:vehiculo_id>")
def obtener_vehiculo(vehiculo_id):
    return jsonify(_resumen(Vehiculo.query.get_or_404(vehiculo_id), detalle=True))


@flota_bp.patch("/vehiculos/<int:vehiculo_id>")
def editar_vehiculo(vehiculo_id):
    v = Vehiculo.query.get_or_404(vehiculo_id)
    data = request.get_json() or {}
    try:
        _aplicar_datos_vehiculo(v, data)
    except ValueError as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 400
    otro = Vehiculo.query.filter(Vehiculo.matricula == v.matricula, Vehiculo.id != v.id).first()
    if otro:
        db.session.rollback()
        return jsonify({"error": f"Ya hay un vehículo con la matrícula {v.matricula}"}), 409
    db.session.commit()
    return jsonify(_resumen(v, detalle=True))


@flota_bp.delete("/vehiculos/<int:vehiculo_id>")
def eliminar_vehiculo(vehiculo_id):
    """Solo para vehículos creados por error. Si ya tiene gastos apuntados en Caja, se da de baja."""
    v = Vehiculo.query.get_or_404(vehiculo_id)
    if v.registros.filter(RegistroVehiculo.movimiento_id.isnot(None)).first():
        return jsonify({
            "error": "tiene_gastos",
            "mensaje": "Este vehículo tiene gastos apuntados en Caja, así que no se borra. "
                       "Si ya no es de la empresa, edítalo y quita «En uso» (queda su historial).",
        }), 409
    db.session.delete(v)
    db.session.commit()
    return jsonify({"eliminado": True})


# -------------------- registros --------------------

@flota_bp.post("/vehiculos/<int:vehiculo_id>/registros")
def crear_registro(vehiculo_id):
    v = Vehiculo.query.get_or_404(vehiculo_id)
    data = request.get_json() or {}
    tipo = (data.get("tipo") or "").strip().lower()
    if tipo not in TIPOS_REGISTRO_VEHICULO:
        return jsonify({"error": "Tipo de registro no válido"}), 400
    try:
        fecha = _fecha(data.get("fecha"), "Fecha") or hoy_madrid()
        km = _entero(data.get("km"), "Kilómetros")
        coste = _decimal(data.get("coste"), "Coste")
        litros = _decimal(data.get("litros"), "Litros", 1000)
        proxima_fecha = _fecha(data.get("proxima_fecha"), "Próxima fecha")
        proximo_km = _entero(data.get("proximo_km"), "Próximo mantenimiento (km)")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if fecha > hoy_madrid() + timedelta(days=1):
        return jsonify({"error": "La fecha no puede ser futura: registra lo que ya se ha hecho"}), 400
    resultado = (data.get("resultado") or "").strip().lower() or None
    if tipo == "itv" and resultado not in (None, "favorable", "desfavorable", "negativa"):
        return jsonify({"error": "Resultado de ITV no válido"}), 400

    r = RegistroVehiculo(
        vehiculo_id=v.id, tipo=tipo, fecha=fecha, km=km, coste=coste,
        litros=litros if tipo == "combustible" else None,
        resultado=resultado if tipo == "itv" else None,
        lugar=_texto(data, "lugar", 100),
        descripcion=(data.get("descripcion") or "").strip() or None,
    )
    db.session.add(r)

    # Kilómetros: solo suben (un registro antiguo con menos km no los baja)
    if km is not None and km > (v.km_actuales or 0):
        v.km_actuales = km

    # Próximas fechas según lo registrado
    if tipo == "itv":
        if proxima_fecha:
            v.proxima_itv = proxima_fecha
    elif tipo == "mantenimiento":
        if proxima_fecha:
            v.proximo_mant_fecha = proxima_fecha
        elif v.intervalo_mant_meses:
            v.proximo_mant_fecha = _sumar_meses(fecha, v.intervalo_mant_meses)
        if proximo_km:
            v.proximo_mant_km = proximo_km
        elif v.intervalo_mant_km and (km or v.km_actuales):
            v.proximo_mant_km = (km or v.km_actuales) + v.intervalo_mant_km
    elif tipo == "seguro":
        if proxima_fecha:
            v.seguro_vence = proxima_fecha
        compania = _texto(data, "seguro_compania", 80)
        if compania:
            v.seguro_compania = compania

    # Gasto en Caja (con la fecha del registro, a mediodía en Madrid)
    if coste and coste > 0 and data.get("apuntar_en_caja"):
        concepto = f"{NOMBRE_TIPO[tipo]} · {v.nombre_corto()}"[:120]
        mov = MovimientoFinanciero(
            tipo="gasto", concepto=concepto, monto=coste,
            metodo_pago=(data.get("metodo_pago") or "efectivo")[:30],
            fecha=a_utc(datetime.combine(fecha, time(12, 0))),
        )
        db.session.add(mov)
        db.session.flush()
        r.movimiento_id = mov.id

    db.session.commit()
    return jsonify({"registro": r.to_dict(), "vehiculo": _resumen(v, detalle=True)}), 201


@flota_bp.delete("/registros/<int:registro_id>")
def eliminar_registro(registro_id):
    """Borra un registro mal apuntado. Si tenía gasto en Caja, ese gasto se ANULA (no se borra),
    igual que cualquier otro movimiento: queda constancia y los totales cuadran."""
    r = RegistroVehiculo.query.get_or_404(registro_id)
    v = r.vehiculo
    if r.movimiento_id:
        mov = MovimientoFinanciero.query.get(r.movimiento_id)
        if mov and not mov.anulado:
            motivo = "Registro de vehículo borrado"
            mov.anulado = True
            mov.motivo_anulacion = motivo
            db.session.add(MovimientoFinanciero(
                tipo=mov.tipo, concepto=f"ANULACIÓN: {mov.concepto or mov.tipo}"[:120],
                monto=-mov.monto, metodo_pago=mov.metodo_pago, anula_a_id=mov.id, motivo_anulacion=motivo,
            ))
    db.session.delete(r)
    db.session.commit()
    return jsonify({"eliminado": True, "vehiculo": _resumen(v, detalle=True)})


# -------------------- avisos (campanita) --------------------

@flota_bp.get("/avisos")
def avisos():
    hoy = hoy_madrid()
    lista = []
    for v in Vehiculo.query.filter(Vehiculo.activo.is_(True)).order_by(Vehiculo.matricula).all():
        for a in avisos_de(v, hoy):
            lista.append({**a, "vehiculo_id": v.id, "matricula": v.matricula, "vehiculo": v.nombre_corto()})
    return jsonify(lista)
