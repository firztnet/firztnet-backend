"""Firztnet Central — Punto de venta (Firztnet POS).

El POS funciona en el ordenador de cada tienda, sin internet. Cuando hay conexión
llama él a Central (nunca al revés: en la tienda no se abre ninguna puerta):

· /api/central/pos/entrada/...  → lo usa el POS (sin login):
    activar (con el código que das tú), prueba (7 días gratis), migrar (claves
    antiguas), parte (cada 10 minutos: ventas del día, versión, copias) y copia
    (copia de seguridad cifrada).
· /api/central/pos/...          → lo usas tú desde el panel (con tu login).

Licencias: Central las firma con su clave privada (POS_CLAVE_PRIVADA, Ed25519).
El POS solo tiene la clave pública: puede comprobarlas, pero nunca fabricarlas.
"""
import base64
import calendar
import hashlib
import hmac
import json
import os
import re
import secrets
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request, send_file

from app import db, limiter
from app.models import LocalCliente, PosEquipo, PosPrueba, PosTienda, Venta

pos_bp = Blueprint("pos", __name__)

DIAS_PRUEBA = 7
COPIAS_A_GUARDAR = 14
MAX_COPIA = 25 * 1024 * 1024
ESTADO_CENTRAL = {"prueba": "prueba", "activa": "activo", "suspendida": "suspendido", "baja": "baja"}
ALFABETO = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin 0/O ni 1/I, para dictarlo por teléfono


# ---------- Utilidades ----------

def _b64(datos):
    return base64.urlsafe_b64encode(datos).decode().rstrip("=")


def _clave_privada():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    texto = (os.environ.get("POS_CLAVE_PRIVADA") or "").strip()
    if not texto:
        return None
    try:
        return Ed25519PrivateKey.from_private_bytes(base64.b64decode(texto))
    except Exception:  # noqa: BLE001
        return None


def _firmar(contenido):
    clave = _clave_privada()
    if not clave:
        raise RuntimeError("Falta POS_CLAVE_PRIVADA")
    datos = json.dumps(contenido, separators=(",", ":"), sort_keys=True, ensure_ascii=False).encode("utf-8")
    return f"{_b64(datos)}.{_b64(clave.sign(datos))}"


def _huella(texto):
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()


def _sumar_meses(d, meses):
    mes = d.month - 1 + meses
    anio, mes = d.year + mes // 12, mes % 12 + 1
    return date(anio, mes, min(d.day, calendar.monthrange(anio, mes)[1]))


def _slug(nombre):
    base = re.sub(r"[^a-z0-9]+", "-", (nombre or "").lower().translate(str.maketrans("áéíóúüñ", "aeiouun"))).strip("-")[:40] or "tienda"
    slug, n = base, 2
    while PosTienda.query.filter_by(slug=slug).first():
        slug, n = f"{base}-{n}", n + 1
    return slug


def _codigo_nuevo(t):
    codigo = "".join(secrets.choice(ALFABETO) for _ in range(8))
    codigo = f"{codigo[:4]}-{codigo[4:]}"
    t.codigo_hash = _huella(codigo.replace("-", ""))
    t.codigo_pista = codigo[-4:]
    return codigo


def _texto(data, campo, maximo):
    valor = data.get(campo)
    return str(valor).strip()[:maximo] if valor not in (None, "") else None


def _machine(data):
    m = re.sub(r"\D", "", str(data.get("machine_id") or ""))
    return m if 6 <= len(m) <= 20 else None


def _fecha(texto):
    try:
        return date.fromisoformat(str(texto)[:10]) if texto else None
    except ValueError:
        return None


# ---------- Licencia ----------

def licencia_de(t, machine_id, manual=False):
    """La licencia firmada de un equipo, según cómo esté la tienda hoy."""
    hoy = date.today()
    ahora = datetime.utcnow()
    if t.estado in ("suspendida", "baja"):
        tipo, hasta = "bloqueada", hoy - timedelta(days=1)
    elif t.estado == "prueba":
        tipo, hasta = "prueba", t.prueba_hasta or hoy
    elif t.modo == "unico":
        tipo, hasta = "unico", None
    else:
        tipo, hasta = "cuota", (t.pagado_hasta or hoy) + timedelta(days=t.dias_gracia or 0)
    # Cuota y prueba: tiene que hablar con Central de vez en cuando (no si se activó a mano, sin internet)
    conexion = None if (tipo == "unico" or manual) else (ahora + timedelta(days=t.dias_sin_conexion or 15)).isoformat(timespec="seconds") + "Z"
    return _firmar({
        "v": 1, "tienda": t.slug, "negocio": t.nombre, "machine": machine_id, "tipo": tipo,
        "hasta": hasta.isoformat() if hasta else None,
        "pagado_hasta": t.pagado_hasta.isoformat() if (tipo == "cuota" and t.pagado_hasta) else None,
        "conexion_hasta": conexion, "equipos": t.max_equipos or 1,
        "emitida": ahora.isoformat(timespec="seconds") + "Z",
    })


def _respuesta_equipo(t, e, token=None):
    r = {"licencia": licencia_de(t, e.machine_id), "tienda": {"slug": t.slug, "nombre": t.nombre}}
    if token:
        r["token"] = token
        r["clave_copias"] = e.clave_copias
    return r


def _equipo_nuevo(t, machine_id, nombre):
    from cryptography.fernet import Fernet
    token = secrets.token_urlsafe(32)
    e = PosEquipo.query.filter_by(tienda_id=t.id, machine_id=machine_id).first()
    if not e:
        e = PosEquipo(tienda_id=t.id, machine_id=machine_id, clave_copias=Fernet.generate_key().decode())
        db.session.add(e)
    e.nombre = nombre or e.nombre or "Caja"
    e.token_hash = _huella(token)
    e.activo = True
    return e, token


def _del_token():
    token = (request.headers.get("X-Pos-Token") or "").strip()
    if len(token) < 20:
        return None
    return PosEquipo.query.filter_by(token_hash=_huella(token)).first()


# ---------- Ficha en Central (clientes de sistemas, cuadro de mando, cobros) ----------

def sincronizar_ficha(t):
    """La tienda aparece en «Clientes de sistemas» y cuenta en el cuadro de mando como cualquier otro cliente."""
    from app.routes.central import _anotar_evento, _avisar_fin_de_prueba
    hoy = date.today()
    l = LocalCliente.query.filter_by(sistema="pos", slug=t.slug).first()
    nuevo = l is None
    if nuevo:
        l = LocalCliente(sistema="pos", slug=t.slug, nombre=t.nombre[:120], alta=(t.creado or datetime.utcnow()).isoformat() + "Z")
        db.session.add(l)
    antes = None if nuevo else l.estado
    l.nombre = t.nombre[:120]
    l.tipo = "tienda"
    l.estado = ESTADO_CENTRAL.get(t.estado, t.estado)
    vence = t.prueba_hasta if t.estado == "prueba" else (t.pagado_hasta if t.modo == "cuota" else None)
    l.dias = (vence - hoy).days if vence else None
    l.prueba_hasta = t.prueba_hasta.isoformat() if t.prueba_hasta else None
    l.renueva = t.pagado_hasta.isoformat() if (t.modo == "cuota" and t.pagado_hasta and t.estado == "activa") else None
    l.renovacion_vencida = bool(t.modo == "cuota" and t.estado == "activa" and t.pagado_hasta and t.pagado_hasta < hoy)
    l.contacto_nombre, l.contacto_email, l.contacto_telefono = t.contacto_nombre, t.contacto_email, t.contacto_telefono
    equipos = t.equipos.filter_by(activo=True).all()
    ultimo = max((e.ultimo_parte for e in equipos if e.ultimo_parte), default=None)
    ventas = {"ventas_hoy_cents": 0, "tickets_hoy": 0}
    for e in equipos:
        try:
            d = json.loads(e.datos_json or "{}")
        except ValueError:
            d = {}
        ventas["ventas_hoy_cents"] += int(d.get("ventas_hoy_cents") or 0)
        ventas["tickets_hoy"] += int(d.get("tickets_hoy") or 0)
    l.uso_json = json.dumps({
        "cuota_cents": (t.cuota_cents or 0) if t.modo == "cuota" else 0, "periodo": "mensual", "modo": t.modo,
        "equipos": len(equipos), "max_equipos": t.max_equipos, **ventas,
        "versiones": sorted({e.version for e in equipos if e.version}),
    })
    l.aparatos_json = json.dumps([{"nombre": e.nombre, "version": e.version, "ultimo_parte": e.ultimo_parte.isoformat() + "Z" if e.ultimo_parte else None} for e in equipos])
    l.ultimo_uso = ultimo.isoformat() + "Z" if ultimo else None
    copias = [e.ultima_copia for e in equipos if e.ultima_copia]
    l.ultima_copia = min(copias) if copias else None
    l.sincronizado = datetime.utcnow()
    _avisar_fin_de_prueba(l, "pos")
    db.session.flush()
    _anotar_evento(l, nuevo, antes)


def _copia_del_sistema():
    """Para el panel de copias de Central: la copia más antigua entre las tiendas vivas."""
    from app.routes.central_extra import guardar_copia_sistema
    ultimas = [e.ultima_copia for t in PosTienda.query.filter(PosTienda.estado.in_(("prueba", "activa"))).all()
               for e in t.equipos.filter_by(activo=True).all()]
    if ultimas:
        guardar_copia_sistema("pos", {"ultima": min(u or "1970-01-01T00:00:00Z" for u in ultimas), "detalle": "Copia diaria de cada tienda, cifrada"})


# ---------- Lo que usa el POS (sin login) ----------

@pos_bp.post("/entrada/activar")
@limiter.limit("10 per minute")
def activar():
    data = request.get_json(silent=True) or {}
    machine = _machine(data)
    codigo = re.sub(r"[^A-Z0-9]", "", str(data.get("codigo") or "").upper())
    if not machine or len(codigo) != 8:
        return jsonify({"error": "Escribe el código de activación que te ha dado Firztnet"}), 400
    if not _clave_privada():
        return jsonify({"error": "Firztnet todavía no tiene configuradas las licencias. Avísale."}), 503
    t = PosTienda.query.filter_by(codigo_hash=_huella(codigo)).first()
    if not t or t.estado == "baja":
        return jsonify({"error": "Ese código no es válido. Revísalo o pide uno nuevo a Firztnet."}), 400
    ya = t.equipos.filter_by(machine_id=machine).first()
    if not ya and t.equipos.filter_by(activo=True).count() >= (t.max_equipos or 1):
        return jsonify({"error": f"Esta tienda ya tiene activados sus {t.max_equipos} ordenador(es). Pide a Firztnet que amplíe la licencia."}), 409
    e, token = _equipo_nuevo(t, machine, _texto(data, "equipo", 80))
    e.version = _texto(data, "version", 20)
    if t.estado == "prueba":
        t.estado = "activa"  # tenía la prueba y ahora entra con su código: ya es cliente
    sincronizar_ficha(t)
    db.session.commit()
    return jsonify(_respuesta_equipo(t, e, token))


@pos_bp.post("/entrada/prueba")
@limiter.limit("10 per minute")
def prueba():
    data = request.get_json(silent=True) or {}
    machine, negocio = _machine(data), _texto(data, "negocio", 120)
    if not machine or not negocio:
        return jsonify({"error": "Escribe el nombre del negocio para empezar la prueba"}), 400
    if not _clave_privada():
        return jsonify({"error": "Firztnet todavía no tiene configuradas las licencias. Avísale."}), 503
    p = PosPrueba.query.filter_by(machine_id=machine).first()
    if p:
        t = PosTienda.query.get(p.tienda_id) if p.tienda_id else None
        if not t or t.estado != "prueba" or (t.prueba_hasta and t.prueba_hasta < date.today()):
            return jsonify({"error": "Este ordenador ya usó su prueba gratuita. Pide tu código a Firztnet."}), 400
    else:
        t = PosTienda(slug=_slug(negocio), nombre=negocio, estado="prueba", modo="cuota",
                      prueba_hasta=date.today() + timedelta(days=DIAS_PRUEBA), notas="Empezó con la prueba gratis desde el POS")
        db.session.add(t)
        db.session.flush()
        db.session.add(PosPrueba(machine_id=machine, negocio=negocio, tienda_id=t.id))
    e, token = _equipo_nuevo(t, machine, _texto(data, "equipo", 80))
    e.version = _texto(data, "version", 20)
    sincronizar_ficha(t)
    db.session.commit()
    try:
        from app.notificaciones import enviar_telegram
        enviar_telegram(f"🧾 Punto de venta: «{t.nombre}» ha empezado la prueba gratis de {DIAS_PRUEBA} días.")
    except Exception:  # noqa: BLE001
        pass
    return jsonify(_respuesta_equipo(t, e, token))


@pos_bp.post("/entrada/migrar")
@limiter.limit("10 per minute")
def migrar():
    """Tiendas activadas con la clave antigua: se comprueba aquí y pasan a licencia firmada sin perder nada."""
    data = request.get_json(silent=True) or {}
    machine, negocio = _machine(data), _texto(data, "negocio", 120)
    clave = re.sub(r"[^A-Z0-9]", "", str(data.get("clave") or "").upper())
    secreto = os.environ.get("POS_SECRETO_ANTIGUO") or ""
    if not machine or not negocio or not clave:
        return jsonify({"error": "Faltan datos de la licencia antigua"}), 400
    if not secreto or not _clave_privada():
        return jsonify({"error": "Firztnet todavía no tiene configuradas las licencias. Avísale."}), 503
    base = f"{negocio.strip().lower()}|{machine}"
    esperada = hmac.new(secreto.encode(), base.encode(), hashlib.sha256).hexdigest()[:20].upper()
    if not hmac.compare_digest(esperada, clave):
        return jsonify({"error": "La licencia antigua no es válida para este ordenador"}), 400
    e = PosEquipo.query.filter_by(machine_id=machine).first()
    t = e.tienda if e else None
    if not t:
        t = PosTienda(slug=_slug(negocio), nombre=negocio, estado="activa", modo="unico",
                      notas="Activada con la clave antigua; pasada sola a licencia firmada")
        db.session.add(t)
        db.session.flush()
    e, token = _equipo_nuevo(t, machine, _texto(data, "equipo", 80))
    e.version = _texto(data, "version", 20)
    sincronizar_ficha(t)
    db.session.commit()
    try:
        from app.notificaciones import enviar_telegram
        enviar_telegram(f"🧾 Punto de venta: «{t.nombre}» ha pasado a la licencia nueva y ya informa a Central. "
                        "Revisa en «Punto de venta» si es pago único o cuota.")
    except Exception:  # noqa: BLE001
        pass
    return jsonify(_respuesta_equipo(t, e, token))


@pos_bp.post("/entrada/parte")
@limiter.limit("60 per minute")
def parte():
    e = _del_token()
    if not e:
        return jsonify({"error": "Equipo no reconocido"}), 401
    if not e.activo:
        return jsonify({"error": "Este ordenador está desactivado. Pide un código nuevo a Firztnet.", "revocado": True}), 403
    data = request.get_json(silent=True) or {}
    t = e.tienda
    e.ultimo_parte = datetime.utcnow()
    e.version = _texto(data, "version", 20) or e.version
    if data.get("ultima_copia"):
        e.ultima_copia = _texto(data, "ultima_copia", 40)
    reloj = data.get("reloj")
    try:
        desfase = abs((datetime.fromisoformat(str(reloj).replace("Z", "")) - datetime.utcnow()).total_seconds())
        e.reloj_atrasado = desfase > 3600
    except (TypeError, ValueError):
        pass
    guardar = {k: data.get(k) for k in ("ventas_hoy_cents", "tickets_hoy", "ventas_7d_cents", "ultima_venta", "errores", "productos", "bloqueado")}
    if isinstance(guardar.get("errores"), list):
        guardar["errores"] = [str(x)[:300] for x in guardar["errores"][:20]]
    e.datos_json = json.dumps(guardar, default=str)[:20000]
    sincronizar_ficha(t)
    _copia_del_sistema()
    db.session.commit()
    respuesta = _respuesta_equipo(t, e)
    if t.estado == "activa" and t.modo == "cuota" and t.pagado_hasta and t.pagado_hasta < date.today():
        limite = t.pagado_hasta + timedelta(days=t.dias_gracia or 0)
        respuesta["aviso"] = f"Tu cuota está pendiente. El programa seguirá funcionando hasta el {limite.strftime('%d/%m/%Y')}."
    return jsonify(respuesta)


@pos_bp.post("/entrada/copia")
@limiter.limit("10 per minute")
def recibir_copia():
    """Copia de seguridad del POS, ya cifrada en la tienda con la clave de ese equipo."""
    e = _del_token()
    if not e or not e.activo:
        return jsonify({"error": "Equipo no reconocido"}), 401
    datos = request.get_data(cache=False)
    if not datos or len(datos) > MAX_COPIA:
        return jsonify({"error": "Copia vacía o demasiado grande"}), 400
    carpeta = _carpeta_copias(e)
    os.makedirs(carpeta, exist_ok=True)
    nombre = datetime.utcnow().strftime("%Y%m%d-%H%M%S") + ".enc"
    with open(os.path.join(carpeta, nombre), "wb") as f:
        f.write(datos)
    for viejo in sorted(os.listdir(carpeta))[:-COPIAS_A_GUARDAR]:
        try:
            os.remove(os.path.join(carpeta, viejo))
        except OSError:
            pass
    e.ultima_copia = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    sincronizar_ficha(e.tienda)
    _copia_del_sistema()
    db.session.commit()
    return jsonify({"ok": True, "copia": nombre})


def _carpeta_copias(e):
    raiz = os.environ.get("POS_COPIAS_DIR") or os.path.join(
        os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "pos-copias")
    return os.path.join(raiz, e.tienda.slug, str(e.id))


# ---------- Lo que usas tú (con tu login) ----------

def _tienda_dict(t, completa=False):
    equipos = t.equipos.order_by(PosEquipo.id).all()
    hoy = date.today()
    d = {
        "id": t.id, "slug": t.slug, "nombre": t.nombre, "nif": t.nif, "estado": t.estado, "modo": t.modo,
        "cuota": (t.cuota_cents or 0) / 100, "pagado_hasta": t.pagado_hasta.isoformat() if t.pagado_hasta else None,
        "prueba_hasta": t.prueba_hasta.isoformat() if t.prueba_hasta else None,
        "dias_gracia": t.dias_gracia, "dias_sin_conexion": t.dias_sin_conexion, "max_equipos": t.max_equipos,
        "contacto_nombre": t.contacto_nombre, "contacto_telefono": t.contacto_telefono, "contacto_email": t.contacto_email,
        "notas": t.notas, "codigo_pista": t.codigo_pista, "creado": t.creado.isoformat() + "Z" if t.creado else None,
        "impago": bool(t.modo == "cuota" and t.estado == "activa" and t.pagado_hasta and t.pagado_hasta < hoy),
        "equipos": [],
    }
    for e in equipos:
        try:
            datos = json.loads(e.datos_json or "{}")
        except ValueError:
            datos = {}
        horas = (datetime.utcnow() - e.ultimo_parte).total_seconds() / 3600 if e.ultimo_parte else None
        d["equipos"].append({
            "id": e.id, "nombre": e.nombre, "machine_id": e.machine_id, "activo": e.activo, "version": e.version,
            "ultimo_parte": e.ultimo_parte.isoformat() + "Z" if e.ultimo_parte else None,
            "sin_noticias_horas": round(horas, 1) if horas is not None else None,
            "ultima_copia": e.ultima_copia, "reloj_atrasado": e.reloj_atrasado, "datos": datos,
            "copias": sorted(os.listdir(_carpeta_copias(e)), reverse=True)[:COPIAS_A_GUARDAR] if completa and os.path.isdir(_carpeta_copias(e)) else [],
        })
    return d


def _leer_tienda(t, data):
    if "nombre" in data:
        nombre = _texto(data, "nombre", 120)
        if not nombre:
            raise ValueError("El nombre de la tienda es obligatorio")
        t.nombre = nombre
    for campo, maximo in (("nif", 20), ("contacto_nombre", 120), ("contacto_telefono", 40), ("contacto_email", 160), ("notas", 2000)):
        if campo in data:
            setattr(t, campo, _texto(data, campo, maximo))
    if "modo" in data:
        if data["modo"] not in ("cuota", "unico"):
            raise ValueError("Elige cuota mensual o pago único")
        t.modo = data["modo"]
    if "estado" in data:
        if data["estado"] not in ("prueba", "activa", "suspendida", "baja"):
            raise ValueError("Estado no válido")
        t.estado = data["estado"]
    if "cuota" in data:
        try:
            t.cuota_cents = int(round(float(str(data["cuota"] or 0).replace(",", ".")) * 100))
        except ValueError:
            raise ValueError("Importe no válido")
    for campo, minimo, maximo in (("dias_gracia", 0, 60), ("dias_sin_conexion", 3, 90), ("max_equipos", 1, 20)):
        if campo in data:
            try:
                valor = int(data[campo])
            except (TypeError, ValueError):
                raise ValueError(f"Número no válido en {campo}")
            setattr(t, campo, max(minimo, min(maximo, valor)))
    for campo in ("pagado_hasta", "prueba_hasta"):
        if campo in data:
            setattr(t, campo, _fecha(data[campo]))
    if t.modo == "cuota" and t.estado == "activa" and not t.pagado_hasta:
        t.pagado_hasta = _sumar_meses(date.today(), 1)


@pos_bp.get("/estado")
def estado_configuracion():
    clave = _clave_privada()
    publica = None
    if clave:
        from cryptography.hazmat.primitives import serialization
        publica = base64.b64encode(clave.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
    return jsonify({"licencias": bool(clave), "migracion": bool(os.environ.get("POS_SECRETO_ANTIGUO")), "clave_publica": publica})


@pos_bp.get("/tiendas")
def listar_tiendas():
    return jsonify([_tienda_dict(t) for t in PosTienda.query.order_by(PosTienda.nombre).all()])


@pos_bp.get("/tiendas/<int:tid>")
def ver_tienda(tid):
    return jsonify(_tienda_dict(PosTienda.query.get_or_404(tid), completa=True))


@pos_bp.post("/tiendas")
def crear_tienda():
    data = request.get_json(silent=True) or {}
    t = PosTienda(slug=_slug(data.get("nombre")), nombre="", estado="activa", modo="cuota")
    try:
        _leer_tienda(t, {"estado": "activa", **data})
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    t.slug = _slug(t.nombre)
    codigo = _codigo_nuevo(t)
    db.session.add(t)
    db.session.flush()
    sincronizar_ficha(t)
    db.session.commit()
    return jsonify({**_tienda_dict(t), "codigo": codigo}), 201


@pos_bp.route("/tiendas/<int:tid>", methods=["PUT", "PATCH"])
def editar_tienda(tid):
    t = PosTienda.query.get_or_404(tid)
    try:
        _leer_tienda(t, request.get_json(silent=True) or {})
    except ValueError as err:
        return jsonify({"error": str(err)}), 400
    sincronizar_ficha(t)
    db.session.commit()
    return jsonify(_tienda_dict(t))


@pos_bp.post("/tiendas/<int:tid>/codigo")
def nuevo_codigo(tid):
    t = PosTienda.query.get_or_404(tid)
    codigo = _codigo_nuevo(t)
    db.session.commit()
    return jsonify({"codigo": codigo})


@pos_bp.post("/tiendas/<int:tid>/pago")
def registrar_pago(tid):
    """Te ha pagado: la cuota avanza los meses pagados y queda apuntado como venta cobrada."""
    t = PosTienda.query.get_or_404(tid)
    data = request.get_json(silent=True) or {}
    try:
        meses = max(1, min(24, int(data.get("meses") or 1)))
        importe = round(float(str(data.get("importe") or (t.cuota_cents or 0) / 100 * meses).replace(",", ".")), 2)
    except ValueError:
        return jsonify({"error": "Importe no válido"}), 400
    if importe < 0 or importe > 100000:
        return jsonify({"error": "Importe no válido"}), 400
    hoy = date.today()
    if t.modo == "cuota":
        desde = t.pagado_hasta if (t.pagado_hasta and t.pagado_hasta >= hoy) else hoy
        t.pagado_hasta = _sumar_meses(desde, meses)
    if t.estado in ("prueba", "suspendida"):
        t.estado = "activa"
    metodo = (data.get("metodo") or "").strip()[:40]
    if importe > 0:
        from app.horario import hoy_madrid
        concepto = f"{'Cuota' if t.modo == 'cuota' else 'Licencia'} Punto de venta · {t.nombre}"
        if t.modo == "cuota":
            concepto += f" · {meses} mes(es) hasta {t.pagado_hasta.strftime('%d/%m/%Y')}"
        db.session.add(Venta(negocio="firztweb", tipo="sistema", cliente_nombre=t.nombre[:150], importe=importe, cobrado=True,
                             fecha=hoy_madrid(), descripcion=concepto + (f" · {metodo}" if metodo else "")))
    sincronizar_ficha(t)
    db.session.commit()
    return jsonify(_tienda_dict(t))


@pos_bp.post("/equipos/<int:eid>/desactivar")
def desactivar_equipo(eid):
    e = PosEquipo.query.get_or_404(eid)
    e.activo = False
    e.token_hash = None
    sincronizar_ficha(e.tienda)
    db.session.commit()
    return jsonify({"ok": True})


@pos_bp.post("/tiendas/<int:tid>/licencia-manual")
def licencia_manual(tid):
    """Para un ordenador sin internet: licencia firmada para pegar a mano (no informa a Central hasta tener código)."""
    t = PosTienda.query.get_or_404(tid)
    machine = _machine(request.get_json(silent=True) or {})
    if not machine:
        return jsonify({"error": "Escribe el ID del equipo (12 cifras) que sale en su pantalla de activación"}), 400
    if not _clave_privada():
        return jsonify({"error": "Falta configurar POS_CLAVE_PRIVADA en Railway"}), 503
    return jsonify({"licencia": licencia_de(t, machine, manual=True)})


@pos_bp.get("/equipos/<int:eid>/copias/<nombre>")
def descargar_copia(eid, nombre):
    """Descarga una copia ya descifrada: el archivo pos.db tal cual, para devolvérselo a la tienda."""
    from io import BytesIO
    from cryptography.fernet import Fernet, InvalidToken
    e = PosEquipo.query.get_or_404(eid)
    if not re.fullmatch(r"\d{8}-\d{6}\.enc", nombre):
        return jsonify({"error": "Copia no válida"}), 400
    ruta = os.path.join(_carpeta_copias(e), nombre)
    if not os.path.isfile(ruta):
        return jsonify({"error": "Esa copia ya no existe"}), 404
    try:
        with open(ruta, "rb") as f:
            datos = Fernet(e.clave_copias.encode()).decrypt(f.read())
    except (InvalidToken, ValueError):
        return jsonify({"error": "No se pudo descifrar la copia"}), 500
    return send_file(BytesIO(datos), as_attachment=True, download_name=f"pos-{e.tienda.slug}-{nombre[:15]}.db", mimetype="application/octet-stream")
