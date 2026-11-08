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
