"""Firztnet Central — fase 1: «Pedir ayuda».

Tus otros sistemas (hostelería, peluquerías...) mandan aquí, de servidor a
servidor, las peticiones de ayuda de los locales. Cada sistema tiene su propia
clave (variable de entorno CLAVES_SISTEMAS, por ejemplo
«hosteleria=clave1;peluquerias=clave2»): el sistema que llama se sabe por la
clave, nunca por lo que diga el mensaje.

· /api/central/entrada/...  → la usan los sistemas, con su clave (sin login).
· /api/central/ayuda...     → la usas tú desde el panel (con tu login).
"""
import hmac
import os
from datetime import datetime

from flask import Blueprint, jsonify, request

from app import db, limiter
from app.models import PeticionAyuda

central_bp = Blueprint("central", __name__)

TIPOS = {"impresora", "datafono", "aparato", "acceso", "internet", "otro"}
ESTADOS = {"nueva", "en_curso", "resuelta"}
NOMBRE_SISTEMA = {"hosteleria": "Hostelería", "peluquerias": "Peluquerías", "reformas": "Reformas", "logistica": "Logística", "reciclaje": "Reciclaje"}
NOMBRE_TIPO = {"impresora": "No imprime", "datafono": "Datáfono", "aparato": "Aparato o pantalla", "acceso": "No puede entrar", "internet": "Internet", "otro": "Otra cosa"}


def _claves():
    """«hosteleria=xxx;peluquerias=yyy» → {"hosteleria": "xxx", ...}. Claves cortas no valen."""
    claves = {}
    for parte in os.environ.get("CLAVES_SISTEMAS", "").replace(",", ";").split(";"):
        if "=" in parte:
            sistema, clave = parte.split("=", 1)
            sistema, clave = sistema.strip().lower(), clave.strip()
            if sistema and len(clave) >= 24:
                claves[sistema] = clave
    return claves


def _sistema_de_la_peticion():
    """Qué sistema llama, según su clave. None si la clave no es de ninguno."""
    recibida = (request.headers.get("X-Firztnet-Clave") or "").encode("utf-8")
    if not recibida:
        return None
    encontrado = None
    for sistema, clave in _claves().items():
        # Se comparan todas (sin salir antes) para no dar pistas por el tiempo de respuesta
        if hmac.compare_digest(recibida, clave.encode("utf-8")):
            encontrado = sistema
    return encontrado


def _texto(data, campo, maximo, obligatorio=False):
    valor = (data.get(campo) or "")
    valor = valor.strip() if isinstance(valor, str) else ""
    if obligatorio and not valor:
        raise ValueError(f"Falta «{campo}»")
    return valor[:maximo]


def _avisar_por_telegram(p):
    from app.notificaciones import enviar_telegram
    texto = f"{'🚨 URGENTE · ' if p.urgente else ''}🛟 Petición de ayuda {p.referencia}"
    texto += f"\n🏪 {p.negocio} ({NOMBRE_SISTEMA.get(p.sistema, p.sistema)})"
    texto += f"\n🔧 {NOMBRE_TIPO.get(p.tipo, p.tipo)}"
    texto += f"\n👤 {p.persona or '—'}" + (f" · {p.puesto}" if p.puesto else "")
    texto += f"\n📞 {p.telefono or '—'}"
    texto += f"\n💬 {p.mensaje[:300]}{'…' if len(p.mensaje) > 300 else ''}"
    try:
        enviar_telegram(texto)
    except Exception:
        pass  # si Telegram falla, la petición se guarda igual


# ---------- Lo que usan los sistemas (con su clave) ----------

@central_bp.post("/entrada/ayuda")
@limiter.limit("30 per minute")
def recibir_peticion():
    sistema = _sistema_de_la_peticion()
    if not sistema:
        return jsonify({"error": "Clave del sistema no válida"}), 401
    data = request.get_json(silent=True) or {}
    try:
        tipo = _texto(data, "tipo", 20) or "otro"
        p = PeticionAyuda(
            sistema=sistema,
            cliente_ref=_texto(data, "cliente_ref", 200, obligatorio=True),
            negocio=_texto(data, "negocio", 120, obligatorio=True),
            empresa=_texto(data, "empresa", 160),
            direccion_web=_texto(data, "direccion_web", 200),
            persona=_texto(data, "persona", 80),
            rol=_texto(data, "rol", 30),
            puesto=_texto(data, "puesto", 120),
            telefono=_texto(data, "telefono", 30),
            tipo=tipo if tipo in TIPOS else "otro",
            mensaje=_texto(data, "mensaje", 1000, obligatorio=True),
            urgente=data.get("urgente") is True,
            pagina=_texto(data, "pagina", 60),
            navegador=_texto(data, "navegador", 200),
        )
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    db.session.add(p)
    db.session.commit()
    _avisar_por_telegram(p)
    return jsonify({"id": p.id, "referencia": p.referencia}), 201


@central_bp.get("/entrada/mias")
@limiter.limit("60 per minute")
def peticiones_del_local():
    """Las últimas peticiones de un local, para que las vea en su panel con tu respuesta.
    Solo las de ese sistema: un sistema no puede leer las de otro."""
    sistema = _sistema_de_la_peticion()
    if not sistema:
        return jsonify({"error": "Clave del sistema no válida"}), 401
    ref = (request.args.get("ref") or "").strip()[:200]
    if not ref:
        return jsonify({"peticiones": []})
    lista = (PeticionAyuda.query.filter_by(sistema=sistema, cliente_ref=ref)
             .order_by(PeticionAyuda.fecha.desc()).limit(10).all())
    return jsonify({"peticiones": [p.para_local() for p in lista]})


# ---------- Lo que usas tú (con tu login) ----------

@central_bp.get("/ayuda")
def listar_peticiones():
    query = PeticionAyuda.query
    if request.args.get("todas") != "true":
        query = query.filter(PeticionAyuda.estado != "resuelta")
    lista = query.order_by(PeticionAyuda.urgente.desc(), PeticionAyuda.fecha.desc()).limit(300).all()
    return jsonify([p.to_dict() for p in lista])


@central_bp.patch("/ayuda/<int:peticion_id>")
def actualizar_peticion(peticion_id):
    p = PeticionAyuda.query.get_or_404(peticion_id)
    data = request.get_json(silent=True) or {}
    if "estado" in data:
        if data["estado"] not in ESTADOS:
            return jsonify({"error": "Estado no válido"}), 400
        p.estado = data["estado"]
        p.fecha_resuelta = datetime.utcnow() if p.estado == "resuelta" else None
    if "respuesta" in data:
        respuesta = (data.get("respuesta") or "").strip()[:2000]
        if respuesta != (p.respuesta or ""):
            p.respuesta = respuesta or None
            p.respuesta_fecha = datetime.utcnow() if respuesta else None
            if respuesta and p.estado == "nueva":
                p.estado = "en_curso"  # si ya le has contestado, deja de ser «nueva»
    if "notas" in data:
        p.notas = (data.get("notas") or "").strip()[:2000] or None
    db.session.commit()
    return jsonify(p.to_dict())


# ---------- Fase 2: la salud de tus sistemas (con tu login) ----------

@central_bp.get("/salud")
def estado_sistemas():
    from app.salud import resumen
    return jsonify(resumen())


@central_bp.post("/salud/comprobar")
@limiter.limit("10 per minute")
def comprobar_ahora():
    from app.salud import comprobar_todo, resumen
    comprobar_todo()
    return jsonify(resumen())


def _datos_sistema(data, actual=None):
    from urllib.parse import urlparse
    nombre = (data.get("nombre") if "nombre" in data else (actual.nombre if actual else "")) or ""
    url = (data.get("url") if "url" in data else (actual.url if actual else "")) or ""
    nombre, url = nombre.strip()[:80], url.strip()[:300]
    partes = urlparse(url)
    if not nombre:
        raise ValueError("Escribe un nombre")
    if partes.scheme not in {"http", "https"} or not partes.hostname:
        raise ValueError("La dirección debe empezar por https://")
    tipo = data.get("tipo", actual.tipo if actual else "sistema")
    return nombre, url, tipo if tipo in {"sistema", "web"} else "sistema"


@central_bp.post("/salud/sistemas")
def anadir_sistema():
    from app.models import SistemaVigilado
    from app.salud import asegurar_por_defecto
    asegurar_por_defecto()
    try:
        nombre, url, tipo = _datos_sistema(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    ultimo = db.session.query(db.func.max(SistemaVigilado.orden)).scalar() or 0
    s = SistemaVigilado(nombre=nombre, url=url, tipo=tipo, orden=ultimo + 1)
    db.session.add(s)
    db.session.commit()
    return jsonify({"id": s.id}), 201


@central_bp.patch("/salud/sistemas/<int:sistema_id>")
def editar_sistema(sistema_id):
    from app.models import SistemaVigilado
    from app.salud import cerrar_incidencias_abiertas
    s = SistemaVigilado.query.get_or_404(sistema_id)
    data = request.get_json(silent=True) or {}
    try:
        s.nombre, nueva_url, s.tipo = _datos_sistema(data, s)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    if nueva_url != s.url:
        s.url = nueva_url
        s.ssl_comprobado = None  # dirección nueva: se mira su candado en la siguiente ronda
    if "activo" in data:
        s.activo = bool(data["activo"])
        if not s.activo:
            cerrar_incidencias_abiertas(s)
    db.session.commit()
    return jsonify({"ok": True})


@central_bp.delete("/salud/sistemas/<int:sistema_id>")
def borrar_sistema(sistema_id):
    from app.models import IncidenciaSistema, SistemaVigilado
    s = SistemaVigilado.query.get_or_404(sistema_id)
    IncidenciaSistema.query.filter_by(sistema_id=s.id).delete()
    db.session.delete(s)
    db.session.commit()
    return jsonify({"ok": True})


# ---------- Fase 3: ficha única de cliente ----------

def _json(texto, defecto):
    import json
    try:
        return json.loads(texto) if texto else defecto
    except ValueError:
        return defecto


def _ficha(l, peticiones=None, completa=False):
    from datetime import datetime, timedelta
    aparatos = _json(l.aparatos_json, [])
    hace7 = (datetime.utcnow() - timedelta(days=7)).isoformat()
    sin_conexion = [a for a in aparatos if not a.get("ultima_conexion") or a["ultima_conexion"] < hace7]
    abiertas = [p for p in (peticiones or []) if p.estado != "resuelta"]
    ficha = {
        "id": l.id, "sistema": l.sistema, "slug": l.slug, "nombre": l.nombre, "tipo": l.tipo,
        "estado": l.estado, "dias": l.dias, "prueba_hasta": l.prueba_hasta, "renueva": l.renueva,
        "renovacion_vencida": bool(l.renovacion_vencida), "motivo_suspension": l.motivo_suspension,
        "contacto_nombre": l.contacto_nombre, "contacto_email": l.contacto_email, "contacto_telefono": l.contacto_telefono,
        "direccion_web": l.direccion_web, "alta": l.alta, "ultimo_uso": l.ultimo_uso,
        "uso": _json(l.uso_json, None), "negocios": _json(l.negocios_json, []),
        "num_aparatos": len(aparatos), "aparatos_sin_conexion": len(sin_conexion),
        "ayudas_abiertas": len(abiertas), "ayudas_total": len(peticiones or []),
        "notas": l.notas, "sincronizado": (l.sincronizado.isoformat() + "Z") if l.sincronizado else None,
    }
    visitas = _json(getattr(l, "visitas_json", None), [])
    if visitas:
        from datetime import date
        este = date.today().strftime("%Y-%m")
        ficha["visitas_mes"] = sum(int(v.get("visits") or 0) for v in visitas if v.get("date", "").startswith(este))
        ficha["visitas_mes_anterior"] = sum(int(v.get("visits") or 0) for v in visitas if v.get("date", "").startswith(_mes_anterior(este)))
    if completa:
        ficha["aparatos"] = aparatos
        ficha["ayudas"] = [p.to_dict() for p in (peticiones or [])]
    return ficha


def _peticiones_de(local):
    """Las peticiones de ayuda de ese local: las que llegaron desde su dirección."""
    if not local.direccion_web:
        return []
    return (PeticionAyuda.query.filter(PeticionAyuda.sistema == local.sistema,
                                       PeticionAyuda.cliente_ref.like(f"{local.direccion_web}#%"))
            .order_by(PeticionAyuda.fecha.desc()).all())


def _avisar_fin_de_prueba(l, sistema):
    """Te avisa por Telegram una sola vez cuando a una prueba le quedan 3 días o menos."""
    if l.estado != "prueba" or l.dias is None or l.dias > 3 or not l.prueba_hasta or l.aviso_prueba == l.prueba_hasta:
        return
    from app.notificaciones import enviar_telegram
    cuando = "hoy" if l.dias == 0 else "mañana" if l.dias == 1 else f"en {l.dias} días"
    texto = (f"⏳ La prueba de {l.nombre} ({NOMBRE_SISTEMA.get(sistema, sistema)}) termina {cuando} ({l.prueba_hasta}).\n"
             f"👤 {l.contacto_nombre or '—'}\n📞 {l.contacto_telefono or '—'}\n✉️ {l.contacto_email or '—'}\n"
             "Buen momento para llamarle y pasarle a activo.")
    try:
        enviar_telegram(texto)
    except Exception:  # noqa: BLE001
        pass
    l.aviso_prueba = l.prueba_hasta


@central_bp.post("/entrada/locales")
@limiter.limit("20 per minute")
def recibir_locales():
    """La plataforma manda la lista completa de sus clientes. Los que ya no vienen pasan a «baja»."""
    import json
    from app.models import LocalCliente
    sistema = _sistema_de_la_peticion()
    if not sistema:
        return jsonify({"error": "Clave del sistema no válida"}), 401
    data = request.get_json(silent=True) or {}
    locales = data.get("locales")
    if not isinstance(locales, list) or len(locales) > 2000:
        return jsonify({"error": "Lista de clientes no válida"}), 400
    ahora = datetime.utcnow()
    vistos = set()

    def corto(d, k, n):
        valor = d.get(k)
        return (str(valor)[:n] or None) if valor is not None else None

    for d in locales:
        if not isinstance(d, dict) or not d.get("slug") or not d.get("nombre"):
            continue
        slug = str(d["slug"])[:60]
        vistos.add(slug)
        l = LocalCliente.query.filter_by(sistema=sistema, slug=slug).first()
        if not l:
            l = LocalCliente(sistema=sistema, slug=slug, nombre=str(d["nombre"])[:120])
            db.session.add(l)
        l.nombre = str(d["nombre"])[:120]
        l.tipo = corto(d, "tipo", 20)
        l.estado = corto(d, "estado", 20)
        l.dias = d.get("dias") if isinstance(d.get("dias"), int) else None
        l.prueba_hasta = corto(d, "prueba_hasta", 10)
        l.renueva = corto(d, "renueva", 10)
        l.renovacion_vencida = bool(d.get("renovacion_vencida"))
        l.motivo_suspension = corto(d, "motivo_suspension", 300)
        l.contacto_nombre = corto(d, "contacto_nombre", 120)
        l.contacto_email = corto(d, "contacto_email", 160)
        l.contacto_telefono = corto(d, "contacto_telefono", 40)
        l.direccion_web = corto(d, "direccion_web", 200)
        l.alta = corto(d, "alta", 40)
        l.ultimo_uso = corto(d, "ultimo_uso", 40)
        l.uso_json = json.dumps(d.get("uso"))[:4000] if isinstance(d.get("uso"), dict) else None
        l.negocios_json = json.dumps(d.get("negocios")[:20])[:4000] if isinstance(d.get("negocios"), list) else None
        l.aparatos_json = json.dumps(d.get("aparatos")[:100])[:20000] if isinstance(d.get("aparatos"), list) else None
        if isinstance(d.get("visitas"), list):
            l.visitas_json = json.dumps(d["visitas"][:3000])[:200000]
        if isinstance(d.get("reservas_web"), list):
            l.reservas_json = json.dumps(d["reservas_web"][:50])[:5000]
        l.sincronizado = ahora
        _avisar_fin_de_prueba(l, sistema)
    for l in LocalCliente.query.filter_by(sistema=sistema).all():
        if l.slug not in vistos and l.estado != "baja":
            l.estado = "baja"
            l.dias = None
    db.session.flush()
    # Vigilancia automática de la web de cada cliente (se añade o se quita sola)
    from app.salud import sincronizar_webs_clientes
    sincronizar_webs_clientes(sistema, LocalCliente.query.filter_by(sistema=sistema).all())
    db.session.commit()
    return jsonify({"ok": True, "recibidos": len(vistos)})


@central_bp.get("/clientes")
def listar_clientes_sistemas():
    from app.models import LocalCliente
    locales = LocalCliente.query.order_by(LocalCliente.nombre).all()
    return jsonify([_ficha(l, _peticiones_de(l)) for l in locales])


@central_bp.get("/clientes/<int:local_id>")
def ficha_cliente_sistema(local_id):
    from app.models import LocalCliente
    l = LocalCliente.query.get_or_404(local_id)
    return jsonify(_ficha(l, _peticiones_de(l), completa=True))


@central_bp.patch("/clientes/<int:local_id>")
def notas_cliente_sistema(local_id):
    from app.models import LocalCliente
    l = LocalCliente.query.get_or_404(local_id)
    data = request.get_json(silent=True) or {}
    if "notas" in data:
        l.notas = (data.get("notas") or "").strip()[:4000] or None
    db.session.commit()
    return jsonify(_ficha(l, _peticiones_de(l), completa=True))


# ---------- Fase 4: informe mensual de visitas de la web de cada cliente ----------

NOMBRE_ORIGEN = {
    "directo": "Escriben la dirección o la tienen guardada", "google": "Google (búsqueda y mapas)",
    "instagram": "Instagram", "facebook": "Facebook", "tiktok": "TikTok", "qr": "Código QR del local",
    "whatsapp": "WhatsApp", "buscadores": "Otros buscadores", "otros": "Otras webs",
}
DIAS_SEMANA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def _mes_anterior(mes):
    anio, m = int(mes[:4]), int(mes[5:7])
    return f"{anio - 1}-12" if m == 1 else f"{anio}-{m - 1:02d}"


def _informe(l, mes):
    import calendar
    from datetime import date
    visitas = _json(getattr(l, "visitas_json", None), [])
    reservas = _json(getattr(l, "reservas_json", None), [])
    meses = sorted({v["date"][:7] for v in visitas if isinstance(v, dict) and v.get("date")}, reverse=True)
    if not mes:
        mes = meses[0] if meses else date.today().strftime("%Y-%m")
    anterior = _mes_anterior(mes)
    del_mes = [v for v in visitas if v.get("date", "").startswith(mes)]
    total = sum(int(v.get("visits") or 0) for v in del_mes)
    total_anterior = sum(int(v.get("visits") or 0) for v in visitas if v.get("date", "").startswith(anterior))

    anio, m = int(mes[:4]), int(mes[5:7])
    dias_mes = calendar.monthrange(anio, m)[1]
    por_dia = {f"{mes}-{d:02d}": 0 for d in range(1, dias_mes + 1)}
    por_semana = [0] * 7
    dispositivos = {"movil": 0, "ordenador": 0}
    origenes = {}
    for v in del_mes:
        n = int(v.get("visits") or 0)
        por_dia[v["date"]] = por_dia.get(v["date"], 0) + n
        por_semana[date.fromisoformat(v["date"]).weekday()] += n
        dispositivos[v.get("device", "movil")] = dispositivos.get(v.get("device", "movil"), 0) + n
        origenes[v.get("source", "otros")] = origenes.get(v.get("source", "otros"), 0) + n
    mejor_dia = max(por_dia.items(), key=lambda kv: kv[1]) if total else None
    mejor_semana = max(range(7), key=lambda i: por_semana[i]) if total else None
    res_mes = [r for r in reservas if r.get("mes") == mes]
    res_ant = [r for r in reservas if r.get("mes") == anterior]
    return {
        "local": {"id": l.id, "nombre": l.nombre, "sistema": l.sistema, "direccion_web": l.direccion_web,
                  "contacto_nombre": l.contacto_nombre, "contacto_email": l.contacto_email, "contacto_telefono": l.contacto_telefono},
        "mes": mes,
        "meses": meses,
        "visitas": total,
        "visitas_mes_anterior": total_anterior,
        "cambio_pct": round((total - total_anterior) * 100 / total_anterior) if total_anterior else None,
        "media_diaria": round(total / dias_mes, 1),
        "por_dia": [{"fecha": k, "visitas": n} for k, n in sorted(por_dia.items())],
        "por_dia_semana": [{"dia": DIAS_SEMANA[i], "visitas": por_semana[i]} for i in range(7)],
        "mejor_dia": {"fecha": mejor_dia[0], "visitas": mejor_dia[1]} if mejor_dia else None,
        "mejor_dia_semana": DIAS_SEMANA[mejor_semana] if mejor_semana is not None else None,
        "movil_pct": round(dispositivos.get("movil", 0) * 100 / total) if total else None,
        "origenes": [{"origen": k, "nombre": NOMBRE_ORIGEN.get(k, k), "visitas": n, "pct": round(n * 100 / total)}
                     for k, n in sorted(origenes.items(), key=lambda kv: -kv[1])],
        "reservas_web": sum(int(r.get("n") or 0) for r in res_mes),
        "reservas_web_mes_anterior": sum(int(r.get("n") or 0) for r in res_ant),
        "reservas_tipo": {"peluquerias": "citas", "hosteleria": "reservas de mesa", "reformas": "solicitudes de presupuesto", "logistica": "solicitudes por la web"}.get(l.sistema),
    }


@central_bp.get("/clientes/<int:local_id>/informe")
def informe_visitas(local_id):
    import re
    from app.models import LocalCliente
    l = LocalCliente.query.get_or_404(local_id)
    mes = request.args.get("mes") or ""
    if mes and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", mes):
        return jsonify({"error": "Mes no válido (AAAA-MM)"}), 400
    return jsonify(_informe(l, mes))
