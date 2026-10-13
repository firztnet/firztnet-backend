"""Mantenimientos periódicos (cuota fija mensual, visitas libres dentro de cada mes).

- Un CONTRATO guarda lo fijo: cliente, servicio, dirección, WiFi, tareas incluidas y cuota.
- Cada MES es una orden interna (Reparacion con contrato_id y periodo "AAAA-MM") que
  guarda el cobro de la cuota de ese mes. Así los cobros siguen apareciendo en Caja,
  en los informes y en los recibos, como cualquier otro cobro.
- Cada VISITA cuelga de un mes. Puede haber varias al mes y no llevan cobro.

El mes en curso de los contratos activos se crea solo la primera vez que se consulta."""
import json
import os
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, request, jsonify

from app import db
from app.models import (
    Cliente, Reparacion, MovimientoFinanciero, Factura, ContratoMantenimiento,
    VisitaMantenimiento, ESTADOS_CONTRATO,
)
from app.horario import hoy_madrid

mantenimientos_bp = Blueprint("mantenimientos", __name__)

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


# -------------------- utilidades --------------------

def _periodo_de(fecha):
    return f"{fecha.year}-{fecha.month:02d}"


def nombre_periodo(periodo):
    anio, mes = periodo.split("-")
    return f"{MESES[int(mes) - 1]} {anio}"


def _texto(data, campo, maximo):
    valor = (data.get(campo) or "").strip()
    if len(valor) > maximo:
        raise ValueError(f"El campo '{campo.replace('_', ' ')}' es demasiado largo (máximo {maximo} caracteres)")
    return valor or None


def _leer_cuota(valor):
    try:
        cuota = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError):
        raise ValueError("La cuota no es un número válido")
    if not cuota.is_finite() or cuota < 0 or cuota > 100000:
        raise ValueError("La cuota tiene que ser 0 o más")
    return cuota.quantize(Decimal("0.01"))


def _cobros_del_mes(mes):
    """Ingresos válidos del mes (sin los anulados ni sus apuntes de corrección)."""
    return [
        m for m in MovimientoFinanciero.query.filter_by(reparacion_id=mes.id, tipo="ingreso").order_by(MovimientoFinanciero.fecha).all()
        if not m.anulado and not m.anula_a_id
    ]


def _total_cobrado(mes):
    # Neto: incluye los apuntes de corrección en negativo (así cuadra con Caja).
    movimientos = MovimientoFinanciero.query.filter_by(reparacion_id=mes.id, tipo="ingreso").all()
    return float(sum((m.monto for m in movimientos), Decimal("0")))


def asegurar_mes(contrato, periodo):
    """Devuelve la orden interna del mes; si no existe, la crea."""
    mes = Reparacion.query.filter_by(contrato_id=contrato.id, periodo=periodo).first()
    if mes:
        return mes
    anio, num_mes = (int(x) for x in periodo.split("-"))
    mes = Reparacion(
        numero_orden=f"M{contrato.id:03d}-{periodo}",  # serie propia: no gasta números de las reparaciones
        cliente_id=contrato.cliente_id,
        equipo=f"{contrato.servicio} · {nombre_periodo(periodo)}"[:120],
        tipo_trabajo="domicilio",
        categoria="mantenimiento_empresas",
        direccion_servicio=contrato.direccion,
        estado_actual="contratado",
        fecha_recepcion=datetime(anio, num_mes, 1, 12, 0),
        contrato_id=contrato.id,
        periodo=periodo,
        cuota_mes=contrato.cuota,
    )
    db.session.add(mes)
    db.session.flush()
    return mes


def _resumen_mes(contrato, mes, con_detalle=False):
    visitas = VisitaMantenimiento.query.filter_by(reparacion_id=mes.id).order_by(VisitaMantenimiento.fecha, VisitaMantenimiento.id).all()
    cobrado = _total_cobrado(mes)
    cuota = float(mes.cuota_mes if mes.cuota_mes is not None else (contrato.cuota or 0))
    datos = {
        "reparacion_id": mes.id,
        "numero_orden": mes.numero_orden,
        "periodo": mes.periodo,
        "nombre": nombre_periodo(mes.periodo),
        "num_visitas": len(visitas),
        "visitas_terminadas": sum(1 for v in visitas if v.fin),
        "cuota": round(cuota, 2),
        "cobrado": round(cobrado, 2),
        "cuota_pagada": cuota <= 0 or cobrado >= cuota - 0.005,
        "tiene_factura": Factura.query.filter_by(reparacion_id=mes.id).first() is not None,
    }
    if con_detalle:
        datos["visitas"] = [v.to_dict() for v in visitas]
        datos["cobros"] = [m.to_dict() for m in _cobros_del_mes(mes)]
    return datos


def _contrato_completo(contrato):
    meses = Reparacion.query.filter_by(contrato_id=contrato.id).order_by(Reparacion.periodo.desc()).all()
    datos = contrato.to_dict()
    datos["meses"] = [_resumen_mes(contrato, m, con_detalle=True) for m in meses]
    return datos


def _asegurar_mes_actual(contrato):
    if contrato.estado == "activo":
        return asegurar_mes(contrato, _periodo_de(hoy_madrid()))
    return None


# -------------------- contratos --------------------

@mantenimientos_bp.get("/contratos")
def listar_contratos():
    """Todos los contratos con el resumen del mes en curso (lo crea si falta)."""
    contratos = ContratoMantenimiento.query.order_by(ContratoMantenimiento.id).all()
    for c in contratos:
        _asegurar_mes_actual(c)
    db.session.commit()

    periodo_actual = _periodo_de(hoy_madrid())
    resultado = []
    for c in contratos:
        datos = c.to_dict()
        mes = Reparacion.query.filter_by(contrato_id=c.id, periodo=periodo_actual).first()
        datos["mes_actual"] = _resumen_mes(c, mes) if mes else None
        visitas_c = (
            VisitaMantenimiento.query.join(Reparacion, VisitaMantenimiento.reparacion_id == Reparacion.id)
            .filter(Reparacion.contrato_id == c.id)
        )
        hoy = hoy_madrid()
        ultima = visitas_c.filter(VisitaMantenimiento.fecha <= hoy).order_by(VisitaMantenimiento.fecha.desc()).first()
        proxima = visitas_c.filter(VisitaMantenimiento.fecha > hoy, VisitaMantenimiento.fin.is_(None)).order_by(VisitaMantenimiento.fecha).first()
        datos["ultima_visita"] = ultima.fecha.isoformat() if ultima else None
        datos["proxima_visita"] = proxima.fecha.isoformat() if proxima else None
        resultado.append(datos)
    return jsonify(resultado)


@mantenimientos_bp.post("/contratos")
def crear_contrato():
    data = request.get_json() or {}
    cliente = Cliente.query.get(data.get("cliente_id")) if data.get("cliente_id") else None
    if not cliente:
        return jsonify({"error": "Elige el cliente"}), 400
    try:
        servicio = _texto(data, "servicio", 100)
        if not servicio:
            return jsonify({"error": "Escribe qué servicio es (por ejemplo: Mantenimiento informático)"}), 400
        cuota = _leer_cuota(data.get("cuota", 0))
        contrato = ContratoMantenimiento(
            cliente_id=cliente.id,
            servicio=servicio,
            direccion=_texto(data, "direccion", 200),
            wifi_ssid=_texto(data, "wifi_ssid", 80),
            wifi_password=_texto(data, "wifi_password", 120),
            tareas=_texto(data, "tareas", 5000),
            notas=_texto(data, "notas", 5000),
            cuota=cuota,
            estado=data.get("estado") if data.get("estado") in ESTADOS_CONTRATO else "activo",
            fecha_inicio=hoy_madrid(),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    db.session.add(contrato)
    db.session.flush()

    # Opcional: convertir una orden in situ que ya existía en un mes de este contrato
    # (sus cobros pasan a ser la cuota de ese mes). Deja de salir en el tablero.
    if data.get("adoptar_reparacion_id"):
        orden = Reparacion.query.get(data["adoptar_reparacion_id"])
        if not orden or orden.cliente_id != cliente.id or orden.tipo_trabajo != "domicilio" or orden.contrato_id:
            db.session.rollback()
            return jsonify({"error": "Esa orden no se puede pasar a este contrato (tiene que ser una orden in situ del mismo cliente)"}), 400
        # Mes al que pasa: el que se indique; si no, el del último cobro (es cuando se hizo
        # el trabajo); y si no tiene cobros, el de la fecha en que se dio de alta.
        periodo = (data.get("adoptar_periodo") or "").strip()
        if periodo:
            try:
                anio_p, mes_p = (int(x) for x in periodo.split("-"))
                assert 2000 <= anio_p <= 2100 and 1 <= mes_p <= 12
                periodo = f"{anio_p}-{mes_p:02d}"
            except (ValueError, AssertionError):
                db.session.rollback()
                return jsonify({"error": "El mes no es válido"}), 400
        else:
            ultimo_cobro = MovimientoFinanciero.query.filter_by(reparacion_id=orden.id, tipo="ingreso").order_by(MovimientoFinanciero.fecha.desc()).first()
            from app.horario import a_madrid
            referencia = a_madrid(ultimo_cobro.fecha) if ultimo_cobro and ultimo_cobro.fecha else (orden.fecha_recepcion or datetime.utcnow())
            periodo = _periodo_de(referencia)
        if Reparacion.query.filter_by(contrato_id=contrato.id, periodo=periodo).first():
            db.session.rollback()
            return jsonify({"error": "Ya hay un mes así en el contrato"}), 400
        orden.contrato_id = contrato.id
        orden.periodo = periodo
        orden.cuota_mes = contrato.cuota
        if contrato.fecha_inicio and orden.fecha_recepcion and orden.fecha_recepcion.date() < contrato.fecha_inicio:
            contrato.fecha_inicio = orden.fecha_recepcion.date()

    _asegurar_mes_actual(contrato)
    if not cliente.codigo or cliente.es_contacto:
        from app.routes.clientes import convertir_en_cliente
        convertir_en_cliente(cliente)
    db.session.commit()
    return jsonify(_contrato_completo(contrato)), 201


@mantenimientos_bp.get("/contratos/<int:contrato_id>")
def obtener_contrato(contrato_id):
    contrato = ContratoMantenimiento.query.get_or_404(contrato_id)
    _asegurar_mes_actual(contrato)
    db.session.commit()
    return jsonify(_contrato_completo(contrato))


@mantenimientos_bp.patch("/contratos/<int:contrato_id>")
def editar_contrato(contrato_id):
    contrato = ContratoMantenimiento.query.get_or_404(contrato_id)
    data = request.get_json() or {}
    try:
        if "servicio" in data:
            servicio = _texto(data, "servicio", 100)
            if not servicio:
                return jsonify({"error": "El servicio no puede quedar vacío"}), 400
            contrato.servicio = servicio
        for campo, maximo in (("direccion", 200), ("wifi_ssid", 80), ("wifi_password", 120), ("tareas", 5000), ("notas", 5000)):
            if campo in data:
                setattr(contrato, campo, _texto(data, campo, maximo))
        if "cuota" in data:
            contrato.cuota = _leer_cuota(data["cuota"])
            # La cuota nueva vale para el mes en curso y los siguientes que aún no tengan cobros;
            # los meses pasados se quedan con la cuota que tenían.
            actual = _periodo_de(hoy_madrid())
            for mes in Reparacion.query.filter(Reparacion.contrato_id == contrato.id, Reparacion.periodo >= actual).all():
                if not _cobros_del_mes(mes):  # sin cobros válidos (los anulados no cuentan)
                    mes.cuota_mes = contrato.cuota
        if "estado" in data:
            if data["estado"] not in ESTADOS_CONTRATO:
                return jsonify({"error": "Estado no válido"}), 400
            contrato.estado = data["estado"]
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    _asegurar_mes_actual(contrato)
    db.session.commit()
    return jsonify(_contrato_completo(contrato))


@mantenimientos_bp.delete("/contratos/<int:contrato_id>")
def eliminar_contrato(contrato_id):
    """Solo para contratos creados por error: si ya tiene algún cobro o factura no se
    puede borrar (hay que darlo de baja). Se borran sus meses vacíos y sus visitas."""
    from app.firmas import ruta_completa as ruta_firma
    contrato = ContratoMantenimiento.query.get_or_404(contrato_id)
    meses = Reparacion.query.filter_by(contrato_id=contrato.id).all()
    ids = [m.id for m in meses]
    if ids and (MovimientoFinanciero.query.filter(MovimientoFinanciero.reparacion_id.in_(ids)).first()
                or Factura.query.filter(Factura.reparacion_id.in_(ids)).first()):
        return jsonify({"error": "tiene_cobros", "mensaje": "Este contrato ya tiene cobros, así que no se puede borrar. Si ya no lo haces, cámbialo a «Dado de baja»."}), 409
    archivos = []
    for visita in VisitaMantenimiento.query.filter(VisitaMantenimiento.reparacion_id.in_(ids)).all() if ids else []:
        if visita.firma_archivo:
            archivos.append(ruta_firma(visita.firma_archivo))
        db.session.delete(visita)
    db.session.flush()
    for mes in meses:
        db.session.delete(mes)
    db.session.flush()
    db.session.delete(contrato)
    db.session.commit()
    for ruta in archivos:
        try:
            if os.path.exists(ruta):
                os.remove(ruta)
        except OSError:
            pass
    return jsonify({"eliminado": True})


# -------------------- visitas --------------------

@mantenimientos_bp.post("/contratos/<int:contrato_id>/visitas")
def crear_visita(contrato_id):
    contrato = ContratoMantenimiento.query.get_or_404(contrato_id)
    data = request.get_json() or {}
    try:
        fecha = date.fromisoformat(data["fecha"]) if data.get("fecha") else hoy_madrid()
    except ValueError:
        return jsonify({"error": "La fecha no es válida"}), 400
    mes = asegurar_mes(contrato, _periodo_de(fecha))
    visita = VisitaMantenimiento(reparacion_id=mes.id, fecha=fecha, tareas_hechas="[]")
    db.session.add(visita)
    db.session.commit()
    return jsonify(visita.to_dict()), 201


@mantenimientos_bp.patch("/visitas/<int:visita_id>")
def editar_visita(visita_id):
    visita = VisitaMantenimiento.query.get_or_404(visita_id)
    data = request.get_json() or {}
    ahora = datetime.utcnow()
    if data.get("empezar"):
        visita.inicio = ahora
        visita.fin = None
    if data.get("terminar"):
        if not visita.inicio:
            visita.inicio = ahora
        visita.fin = ahora
    if "tareas_hechas" in data:
        lista = data["tareas_hechas"] if isinstance(data["tareas_hechas"], list) else []
        visita.tareas_hechas = json.dumps([str(t)[:200] for t in lista][:100], ensure_ascii=False)
    if "notas" in data:
        notas = (data["notas"] or "").strip()
        if len(notas) > 5000:
            return jsonify({"error": "Las notas son demasiado largas (máximo 5000 caracteres)"}), 400
        visita.notas = notas or None
    if "fecha" in data and data["fecha"]:
        try:
            nueva = date.fromisoformat(data["fecha"])
        except ValueError:
            return jsonify({"error": "La fecha no es válida"}), 400
        mes_actual = Reparacion.query.get(visita.reparacion_id)
        if _periodo_de(nueva) != mes_actual.periodo:
            contrato = ContratoMantenimiento.query.get(mes_actual.contrato_id)
            visita.reparacion_id = asegurar_mes(contrato, _periodo_de(nueva)).id
        visita.fecha = nueva
    db.session.commit()
    return jsonify(visita.to_dict())


@mantenimientos_bp.post("/visitas/<int:visita_id>/firma")
def firmar_visita(visita_id):
    from app.firmas import guardar_firma_png, ruta_completa
    visita = VisitaMantenimiento.query.get_or_404(visita_id)
    data = request.get_json() or {}
    try:
        nombre_archivo, _ = guardar_firma_png(data.get("firma_png"), visita.reparacion_id, f"visita{visita.id}")
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    anterior = visita.firma_archivo
    visita.firma_archivo = nombre_archivo
    visita.nombre_firmante = (data.get("nombre_firmante") or "").strip()[:120] or None
    db.session.commit()
    if anterior:
        try:
            os.remove(ruta_completa(anterior))
        except OSError:
            pass
    return jsonify(visita.to_dict())


@mantenimientos_bp.delete("/visitas/<int:visita_id>")
def eliminar_visita(visita_id):
    """Para una visita apuntada por error."""
    from app.firmas import ruta_completa
    visita = VisitaMantenimiento.query.get_or_404(visita_id)
    archivo = visita.firma_archivo
    db.session.delete(visita)
    db.session.commit()
    if archivo:
        try:
            os.remove(ruta_completa(archivo))
        except OSError:
            pass
    return jsonify({"eliminado": True})
