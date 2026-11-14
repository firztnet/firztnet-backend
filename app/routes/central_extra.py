"""Firztnet Central — mejoras:
 · 3 clientes en riesgo   · 4 recordatorio de cobro
 · 6 copias de seguridad vigiladas   · 7 respuestas rápidas para «Ayuda a clientes»
Las rutas van en el mismo blueprint que el resto de Central (/api/central/...).
"""
import json
import urllib.parse
from datetime import datetime, timedelta

from flask import jsonify, request

from app import db, limiter
from app.models import ConfiguracionNegocio, CopiaSistema, LocalCliente, PeticionAyuda, PlantillaAyuda, Venta
from app.routes.central import NOMBRE_SISTEMA, _json, central_bp, ingreso_mensual

VIVOS = ("prueba", "activo")


def _fecha(iso):
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "")[:26])
    except ValueError:
        try:
            return datetime.fromisoformat(str(iso)[:10])
        except ValueError:
            return None


def _euros(cents):
    return f"{cents / 100:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


# ====================== 7 · Respuestas rápidas ======================

PLANTILLAS_INICIALES = [
    ("Recibido, lo miramos", "Hola, hemos recibido tu petición y ya lo estamos mirando. Te decimos algo en cuanto lo tengamos."),
    ("Reiniciar la impresora", "Hola, prueba a apagar la impresora, esperar 10 segundos y volver a encenderla. Si sigue sin imprimir, dínoslo y lo vemos a distancia."),
    ("Reiniciar el aparato", "Hola, cierra la aplicación del todo, apaga el aparato (tablet o móvil), espera 10 segundos y vuelve a encenderlo. Si sigue igual, avísanos."),
    ("Comprobar internet", "Hola, parece un problema de conexión. Comprueba que el wifi o el router tienen luz y reinícialo (desenchufar 30 segundos). Si sigue igual, llámanos."),
    ("Pasamos a verlo", "Hola, pasamos a verlo en persona. ¿Te viene bien mañana por la mañana? Dinos una hora."),
    ("Solucionado", "Hola, ya está solucionado. Si vuelve a pasar, pídenos ayuda otra vez desde el panel. ¡Gracias!"),
]


def _asegurar_plantillas():
    if PlantillaAyuda.query.count() == 0:
        for i, (titulo, texto) in enumerate(PLANTILLAS_INICIALES):
            db.session.add(PlantillaAyuda(titulo=titulo, texto=texto, orden=i))
        db.session.commit()


@central_bp.get("/plantillas-ayuda")
def listar_plantillas_ayuda():
    _asegurar_plantillas()
    return jsonify([p.to_dict() for p in PlantillaAyuda.query.order_by(PlantillaAyuda.orden, PlantillaAyuda.id).all()])


def _leer_plantilla(data, p=None):
    titulo = (data.get("titulo", p.titulo if p else "") or "").strip()[:80]
    texto = (data.get("texto", p.texto if p else "") or "").strip()[:2000]
    if not titulo or not texto:
        raise ValueError("Escribe un título y el texto")
    return titulo, texto


@central_bp.post("/plantillas-ayuda")
def crear_plantilla_ayuda():
    try:
        titulo, texto = _leer_plantilla(request.get_json(silent=True) or {})
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    ultimo = db.session.query(db.func.max(PlantillaAyuda.orden)).scalar() or 0
    p = PlantillaAyuda(titulo=titulo, texto=texto, orden=ultimo + 1)
    db.session.add(p)
    db.session.commit()
    return jsonify(p.to_dict()), 201


@central_bp.patch("/plantillas-ayuda/<int:pid>")
def editar_plantilla_ayuda(pid):
    p = PlantillaAyuda.query.get_or_404(pid)
    try:
        p.titulo, p.texto = _leer_plantilla(request.get_json(silent=True) or {}, p)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    db.session.commit()
    return jsonify(p.to_dict())


@central_bp.delete("/plantillas-ayuda/<int:pid>")
def borrar_plantilla_ayuda(pid):
    db.session.delete(PlantillaAyuda.query.get_or_404(pid))
    db.session.commit()
    return jsonify({"ok": True})


@central_bp.get("/ayuda-estadisticas")
def estadisticas_ayuda():
    """Cuánto tardas en responder y en resolver (últimos 90 días)."""
    desde = datetime.utcnow() - timedelta(days=90)
    lista = PeticionAyuda.query.filter(PeticionAyuda.fecha >= desde).all()
    resp = [(p.respuesta_fecha - p.fecha).total_seconds() / 60 for p in lista if p.respuesta_fecha]
    resu = [(p.fecha_resuelta - p.fecha).total_seconds() / 3600 for p in lista if p.fecha_resuelta]
    return jsonify({
        "total_90d": len(lista),
        "respuesta_media_min": round(sum(resp) / len(resp)) if resp else None,
        "resolucion_media_h": round(sum(resu) / len(resu), 1) if resu else None,
        "resueltas": len(resu),
    })


# ====================== 3 · Clientes en riesgo ======================

def motivos_riesgo(l, ahora=None):
    """Por qué podrías perder a este cliente. Devuelve [(texto, 'alto'|'medio')]."""
    ahora = ahora or datetime.utcnow()
    uso = _json(l.uso_json, None) or {}
    alta = _fecha(l.alta)
    antiguedad = (ahora - alta).days if alta else 999
    motivos = []
    # Uso del sistema (no aplica a Reciclaje: allí el cliente solo tiene una web)
    if l.sistema != "reciclaje":
        ultimo = _fecha(l.ultimo_uso)
        if not ultimo and antiguedad >= 7:
            motivos.append(("No ha usado nunca el sistema", "alto"))
        elif ultimo and (ahora - ultimo).days >= 7:
            dias = (ahora - ultimo).days
            motivos.append((f"Lleva {dias} días sin usar el sistema", "alto" if dias >= 14 else "medio"))
    if uso.get("titular_sin_estrenar") and antiguedad >= 3:
        motivos.append(("El titular nunca ha entrado con su clave", "medio"))
    if l.sistema in ("hosteleria", "peluquerias") and uso.get("tickets_mes") == 0 and ahora.day >= 10 and antiguedad >= 30:
        motivos.append(("No ha cobrado nada este mes", "alto"))
    if l.renovacion_vencida:
        motivos.append(("Tiene la renovación vencida", "alto"))
    # Visitas de su web: últimas 2 semanas frente a las 2 anteriores
    visitas = _json(l.visitas_json, [])
    if visitas:
        hoy = ahora.date()
        recientes = anteriores = 0
        for v in visitas:
            try:
                d = datetime.fromisoformat(str(v.get("date"))[:10]).date()
            except ValueError:
                continue
            dias = (hoy - d).days
            if 0 <= dias < 14:
                recientes += int(v.get("visits") or 0)
            elif 14 <= dias < 28:
                anteriores += int(v.get("visits") or 0)
        if anteriores >= 10 and recientes <= anteriores * 0.5:
            motivos.append((f"Sus visitas han bajado un {round(100 - recientes * 100 / anteriores)} % en dos semanas", "medio"))
    # Muchas peticiones de ayuda seguidas: puede estar harto
    if l.direccion_web:
        n = PeticionAyuda.query.filter(PeticionAyuda.sistema == l.sistema, PeticionAyuda.cliente_ref.like(f"{l.direccion_web}#%"),
                                       PeticionAyuda.fecha >= ahora - timedelta(days=30)).count()
        if n >= 3:
            motivos.append((f"Ha pedido ayuda {n} veces en 30 días", "medio"))
    return motivos


def clientes_en_riesgo():
    ahora = datetime.utcnow()
    lista = []
    for l in LocalCliente.query.filter(LocalCliente.estado.in_(VIVOS)).all():
        if l.riesgo_pospuesto_hasta and l.riesgo_pospuesto_hasta > ahora:
            continue
        motivos = motivos_riesgo(l, ahora)
        if not motivos:
            continue
        nivel = "alto" if any(n == "alto" for _, n in motivos) else "medio"
        lista.append({
            "id": l.id, "nombre": l.nombre, "sistema": l.sistema, "estado": l.estado, "dias": l.dias,
            "contacto_nombre": l.contacto_nombre, "contacto_telefono": l.contacto_telefono, "contacto_email": l.contacto_email,
            "ingreso_mes_cents": ingreso_mensual(l), "nivel": nivel, "motivos": [m for m, _ in motivos],
        })
    lista.sort(key=lambda c: (c["nivel"] != "alto", -c["ingreso_mes_cents"]))
    return lista


@central_bp.get("/riesgo")
def ver_riesgo():
    return jsonify(clientes_en_riesgo())


@central_bp.post("/riesgo/<int:local_id>/contactado")
def riesgo_contactado(local_id):
    """«Ya le he llamado»: deja de salir en riesgo durante unos días."""
    l = LocalCliente.query.get_or_404(local_id)
    dias = (request.get_json(silent=True) or {}).get("dias", 14)
    dias = dias if isinstance(dias, int) and 1 <= dias <= 90 else 14
    l.riesgo_pospuesto_hasta = datetime.utcnow() + timedelta(days=dias)
    db.session.commit()
    return jsonify({"ok": True, "hasta": l.riesgo_pospuesto_hasta.isoformat() + "Z"})


# ====================== 4 · Recordatorio de cobro ======================

def _texto_recordatorio(l, importe_cents):
    conf = ConfiguracionNegocio.query.first()
    nombre = (l.contacto_nombre or "").split(",")[0].split(" ")[0]
    hola = f"Hola {nombre}," if nombre else "Hola,"
    vencida = l.renovacion_vencida or (l.dias is not None and l.dias < 0)
    fecha = datetime.fromisoformat(l.renueva).strftime("%d/%m/%Y") if l.renueva else ""
    sistema = NOMBRE_SISTEMA.get(l.sistema, l.sistema)
    if vencida:
        texto = f"{hola} te escribimos de Firztnet: la cuota de tu sistema de {sistema} ({l.nombre}) venció el {fecha}"
    else:
        texto = f"{hola} te escribimos de Firztnet para recordarte que el {fecha} se renueva la cuota de tu sistema de {sistema} ({l.nombre})"
    if importe_cents:
        texto += f": {_euros(importe_cents)}"
    texto += "."
    if conf and conf.telefono_bizum:
        texto += f" Puedes pagarla por Bizum al {conf.telefono_bizum}."
    texto += " Si ya la has pagado, olvida este mensaje. ¡Gracias!"
    return texto


def proximos_cobros(dias=30):
    lista = []
    for l in LocalCliente.query.filter(LocalCliente.estado == "activo").all():
        if not l.renueva or l.dias is None or l.dias > dias:
            continue
        importe = ingreso_mensual(l)
        texto = _texto_recordatorio(l, importe)
        telefono = "".join(ch for ch in (l.contacto_telefono or "") if ch.isdigit())
        if len(telefono) == 9:
            telefono = "34" + telefono
        lista.append({
            "id": l.id, "nombre": l.nombre, "sistema": l.sistema, "renueva": l.renueva, "dias": l.dias,
            "vencida": bool(l.renovacion_vencida or l.dias < 0), "importe_cents": importe,
            "contacto_nombre": l.contacto_nombre, "contacto_email": l.contacto_email, "contacto_telefono": l.contacto_telefono,
            "texto": texto, "whatsapp": f"https://wa.me/{telefono}?text={urllib.parse.quote(texto)}" if len(telefono) >= 11 else None,
        })
    lista.sort(key=lambda c: c["dias"])
    return lista


@central_bp.get("/cobros")
def ver_cobros():
    return jsonify(proximos_cobros())


# Dónde está cada sistema, para avisarle de un cobro (se puede cambiar con SISTEMAS_URLS: «hosteleria=https://...;...»)
URLS_SISTEMAS = {
    "hosteleria": "https://hosteleria.firztnet.es", "peluquerias": "https://peluquerias.firztnet.es",
    "logistica": "https://logistica.firztnet.es", "reciclaje": "https://admin.reciclar.firztnet.es",
}
RUTA_PAGO = {"logistica": "/central/pago"}  # el resto: /api/central/pago


def _url_sistema(sistema):
    import os
    for parte in os.environ.get("SISTEMAS_URLS", "").replace(",", ";").split(";"):
        if "=" in parte and parte.split("=", 1)[0].strip().lower() == sistema:
            return parte.split("=", 1)[1].strip().rstrip("/")
    return URLS_SISTEMAS.get(sistema)


def avisar_pago_al_sistema(l, cuotas, importe, metodo):
    """Le dice al sistema del cliente que ha pagado, para que adelante su renovación él solo.
    Devuelve (True, nueva_fecha) o (False, motivo). Nunca lanza: si falla, el cobro ya está apuntado."""
    import requests
    from app.routes.central import _claves
    url, clave = _url_sistema(l.sistema), _claves().get(l.sistema)
    if not url or not clave:
        return False, "Ese sistema todavía no recibe los cobros desde aquí"
    try:
        r = requests.post(url + RUTA_PAGO.get(l.sistema, "/api/central/pago"), timeout=12,
                          json={"slug": l.slug, "cuotas": cuotas, "importe": importe, "metodo": metodo},
                          headers={"X-Firztnet-Clave": clave, "User-Agent": "FirztnetCentral"})
        datos = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    except Exception:  # noqa: BLE001
        return False, "No se pudo contactar con su sistema"
    if r.status_code != 200 or not datos.get("renueva"):
        return False, (datos.get("error") or datos.get("detail") or f"Su sistema respondió con un error ({r.status_code})")
    return True, datos["renueva"]


@central_bp.post("/cobros/<int:local_id>/registrar")
def registrar_cobro(local_id):
    """Apunta que el cliente te ha pagado: queda como venta cobrada en «Ventas» y, si su sistema lo
    admite, su renovación se adelanta sola las cuotas pagadas (sin entrar en su panel)."""
    l = LocalCliente.query.get_or_404(local_id)
    data = request.get_json(silent=True) or {}
    try:
        importe = round(float(str(data.get("importe", "")).replace(",", ".")), 2)
        cuotas = max(1, min(24, int(data.get("cuotas") or 1)))
    except ValueError:
        return jsonify({"error": "Importe no válido"}), 400
    if importe <= 0 or importe > 100000:
        return jsonify({"error": "Importe no válido"}), 400
    metodo = (data.get("metodo") or "").strip()[:40]
    from app.horario import hoy_madrid
    v = Venta(negocio="firztweb", tipo="sistema", cliente_nombre=l.nombre[:150], importe=importe, cobrado=True, fecha=hoy_madrid(),
              descripcion=f"Cuota de {NOMBRE_SISTEMA.get(l.sistema, l.sistema)} · {l.nombre}" + (f" · {cuotas} cuota(s)" if cuotas > 1 else "") + (f" · {metodo}" if metodo else ""))
    db.session.add(v)
    db.session.commit()
    ok, dato = avisar_pago_al_sistema(l, cuotas, importe, metodo)
    if ok:
        # La ficha se pone al día ya (sin esperar a la siguiente lista del sistema)
        from datetime import date
        l.renueva = str(dato)[:10]
        try:
            l.dias = (date.fromisoformat(l.renueva) - date.today()).days
        except ValueError:
            pass
        l.renovacion_vencida = False
        if l.estado in ("prueba", "prueba_vencida"):
            l.estado = "activo"
        db.session.commit()
    return jsonify({"ok": True, "venta_id": v.id, "sistema_actualizado": ok,
                    "renueva": dato if ok else None, "motivo": None if ok else dato}), 201


@central_bp.post("/cobros/<int:local_id>/correo")
@limiter.limit("20 per minute")
def recordatorio_por_correo(local_id):
    """Manda el recordatorio de cobro por correo (solo cuando tú pulsas el botón)."""
    import os
    import urllib.error
    import urllib.request
    l = LocalCliente.query.get_or_404(local_id)
    if not l.contacto_email:
        return jsonify({"error": "Este cliente no tiene correo"}), 400
    clave = os.environ.get("RESEND_API_KEY")
    if not clave:
        return jsonify({"error": "Falta configurar RESEND_API_KEY en Railway"}), 400
    remitente = os.environ.get("EMAIL_REMITENTE", "onboarding@resend.dev")
    conf = ConfiguracionNegocio.query.first()
    texto = _texto_recordatorio(l, ingreso_mensual(l))
    cuerpo = {"from": f"Firztnet <{remitente}>", "to": [l.contacto_email], "reply_to": (conf.email if conf and conf.email else "contacto@firztnet.es"),
              "subject": f"Recordatorio de tu cuota de Firztnet · {l.nombre}", "text": texto}
    peticion = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(cuerpo).encode("utf-8"), method="POST",
                                      headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json", "User-Agent": "Firztnet/1.0 (+https://firztnet.es)"})
    try:
        with urllib.request.urlopen(peticion, timeout=20) as r:
            r.read()
    except urllib.error.HTTPError as e:
        return jsonify({"error": f"Resend respondió {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}"}), 502
    except Exception as e:  # noqa: BLE001
        return jsonify({"error": str(e)[:200]}), 502
    return jsonify({"ok": True})


def aviso_diario_cobros():
    """Cada mañana: te avisa por Telegram de las cuotas que se renuevan en 3 días o ya vencidas (una vez por renovación)."""
    from app.notificaciones import enviar_telegram
    lineas = []
    for c in proximos_cobros(dias=3):
        l = LocalCliente.query.get(c["id"])
        if l.aviso_cobro == l.renueva:
            continue
        cuando = "VENCIDA" if c["vencida"] else ("hoy" if c["dias"] == 0 else f"en {c['dias']} día(s)")
        lineas.append(f"• {c['nombre']} ({NOMBRE_SISTEMA.get(c['sistema'], c['sistema'])}) — {cuando}" + (f" · {_euros(c['importe_cents'])}" if c["importe_cents"] else ""))
        l.aviso_cobro = l.renueva
    db.session.commit()
    if lineas:
        try:
            enviar_telegram("💶 Cuotas que se renuevan pronto:\n" + "\n".join(lineas) + "\n\nEn Reparaciones → «Cobros» tienes el mensaje preparado para cada uno.")
        except Exception:  # noqa: BLE001
            pass


# ====================== 6 · Copias de seguridad vigiladas ======================

HORAS_MAX_SIN_COPIA = 26


def guardar_copia_sistema(sistema, datos):
    """La plataforma dice cuándo hizo su última copia (o que no hace copias automáticas)."""
    if not isinstance(datos, dict):
        return
    c = CopiaSistema.query.filter_by(sistema=sistema).first() or CopiaSistema(sistema=sistema)
    c.ultima = (str(datos.get("ultima"))[:40] if datos.get("ultima") else None)
    c.sin_copias = bool(datos.get("sin_copias"))
    c.detalle = (str(datos.get("detalle"))[:200] if datos.get("detalle") else None)
    c.recibido = datetime.utcnow()
    db.session.add(c)


def estado_copias():
    ahora = datetime.utcnow()
    lista = []
    for c in CopiaSistema.query.order_by(CopiaSistema.sistema).all():
        ultima = _fecha(c.ultima)
        if c.sin_copias:
            estado = "sin_copias"
        elif not ultima:
            estado = "desconocido"
        else:
            estado = "ok" if (ahora - ultima).total_seconds() / 3600 <= HORAS_MAX_SIN_COPIA else "atrasada"
        # Clientes con cambios posteriores a su última copia de hace más de un día (plataformas con una base por cliente)
        atrasados = []
        for l in LocalCliente.query.filter(LocalCliente.sistema == c.sistema, LocalCliente.estado.in_(VIVOS)).all():
            copia, uso = _fecha(l.ultima_copia), _fecha(l.ultimo_uso)
            if l.ultima_copia is not None and uso and (not copia or (uso - copia).total_seconds() / 3600 > HORAS_MAX_SIN_COPIA):
                atrasados.append(l.nombre)
        if atrasados and estado == "ok":
            estado = "atrasada"
        lista.append({"sistema": c.sistema, "nombre": NOMBRE_SISTEMA.get(c.sistema, c.sistema), "estado": estado,
                      "ultima": c.ultima, "detalle": c.detalle, "clientes_sin_copia": atrasados[:10],
                      "recibido": c.recibido.isoformat() + "Z" if c.recibido else None})
    return lista


@central_bp.get("/copias")
def ver_copias():
    return jsonify(estado_copias())


def aviso_diario_copias():
    """Una vez al día: si algún sistema lleva más de un día sin copia, te avisa por Telegram."""
    from app.notificaciones import enviar_telegram
    hoy = datetime.utcnow().strftime("%Y-%m-%d")
    malas = [c for c in estado_copias() if c["estado"] in ("atrasada",)]
    lineas = []
    for c in malas:
        fila = CopiaSistema.query.filter_by(sistema=c["sistema"]).first()
        if fila and fila.avisado != hoy:
            fila.avisado = hoy
            extra = f" (clientes: {', '.join(c['clientes_sin_copia'][:5])})" if c["clientes_sin_copia"] else ""
            lineas.append(f"• {c['nombre']}: última copia {c['ultima'] or 'desconocida'}{extra}")
    db.session.commit()
    if lineas:
        try:
            enviar_telegram("💾 Copias de seguridad atrasadas (más de un día sin copia):\n" + "\n".join(lineas))
        except Exception:  # noqa: BLE001
            pass
