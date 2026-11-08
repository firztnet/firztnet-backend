"""Firztnet Central — fase 2: la salud de tus sistemas y webs.

Cada 2 minutos Reparaciones abre cada sistema y web vigilados, como haría un
navegador, y anota si responde y cuánto tarda. Si uno falla dos veces seguidas
se abre una incidencia y te avisa por Telegram (y en la campana); cuando vuelve
a responder, se cierra y te dice cuánto tiempo estuvo caído. Una vez por hora
mira también cuántos días le quedan al candado (certificado HTTPS).

Límite: Reparaciones no puede avisar de su propia caída (si él no funciona,
no hay quién avise). Eso queda para más adelante.
"""
import socket
import ssl
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

from app import db
from app.models import IncidenciaSistema, SistemaVigilado

INTERVALO_MIN = 2
FALLOS_PARA_CAIDO = 2           # dos fallos seguidos (unos 4 min) = caído; así un parpadeo no te despierta
LENTO_MS = 5000                 # más de 5 s en responder = lento
TIEMPO_MAX = 12                 # segundos de espera antes de darlo por fallido
SSL_CADA = timedelta(hours=1)
SSL_AVISO_DIAS = 14
MADRID = ZoneInfo("Europe/Madrid")
# Una sola ronda a la vez (el reloj y el botón «Comprobar ahora» no se pisan ni avisan dos veces)
_CERROJO = threading.Lock()

SISTEMAS_POR_DEFECTO = [
    ("Hostelería", "https://hosteleria.firztnet.es/", "sistema"),
    ("Peluquerías", "https://peluquerias.firztnet.es/", "sistema"),
    ("Reformas", "https://reformas.firztnet.es/", "sistema"),
    ("Logística", "https://logistica.firztnet.es/", "sistema"),
    ("Reciclaje", "https://admin.reciclar.firztnet.es/plataforma/", "sistema"),
    ("Campus", "https://campus.firztnet.es/", "sistema"),
    ("Reparaciones (panel)", "https://reparaciones.firztnet.es/", "sistema"),
    ("Firztnet", "https://firztnet.es/", "web"),
    ("Firztweb", "https://webs.firztnet.es/", "web"),
    ("TechCompara", "https://techcompara.es/", "web"),
    ("Mis sistemas", "https://sistemas.firztnet.es/", "web"),
]


def hora_madrid(fecha_utc):
    return fecha_utc.replace(tzinfo=ZoneInfo("UTC")).astimezone(MADRID).strftime("%H:%M")


def duracion(minutos):
    if minutos < 60:
        return f"{minutos} min"
    horas, resto = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h {resto} min" if resto else f"{horas} h"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h"


def asegurar_por_defecto():
    """La primera vez, apunta tus sistemas y webs para vigilarlos."""
    if SistemaVigilado.query.count() == 0:
        for i, (nombre, url, tipo) in enumerate(SISTEMAS_POR_DEFECTO):
            db.session.add(SistemaVigilado(nombre=nombre, url=url, tipo=tipo, orden=i))
        db.session.commit()


def _probar(url):
    """Abre la dirección como un navegador. Funciona = responde sin error del servidor (menos de 500)."""
    inicio = time.monotonic()
    try:
        r = requests.get(url, timeout=TIEMPO_MAX, allow_redirects=True,
                         headers={"User-Agent": "FirztnetCentral/1.0 (vigilancia de sistemas)"})
        ms = int((time.monotonic() - inicio) * 1000)
        if r.status_code >= 500:
            return {"ok": False, "codigo": r.status_code, "ms": ms, "error": f"El servidor responde con error {r.status_code}"}
        return {"ok": True, "codigo": r.status_code, "ms": ms, "error": None}
    except requests.exceptions.Timeout:
        return {"ok": False, "codigo": None, "ms": TIEMPO_MAX * 1000, "error": f"No responde en {TIEMPO_MAX} segundos"}
    except requests.exceptions.SSLError:
        return {"ok": False, "codigo": None, "ms": None, "error": "Fallo del candado de seguridad (HTTPS)"}
    except requests.exceptions.ConnectionError:
        return {"ok": False, "codigo": None, "ms": None, "error": "No se puede conectar (dirección caída o DNS)"}
    except Exception as e:  # noqa: BLE001 — cualquier otro fallo cuenta como caída, sin tumbar la vigilancia
        return {"ok": False, "codigo": None, "ms": None, "error": str(e)[:200]}


def _caducidad_ssl(url):
    """Fecha en que caduca el certificado HTTPS, o None si no se puede saber."""
    partes = urlparse(url)
    if partes.scheme != "https" or not partes.hostname:
        return None
    try:
        contexto = ssl.create_default_context()
        with socket.create_connection((partes.hostname, partes.port or 443), timeout=8) as sock:
            with contexto.wrap_socket(sock, server_hostname=partes.hostname) as s:
                caduca = s.getpeercert().get("notAfter")
        return datetime.utcfromtimestamp(ssl.cert_time_to_seconds(caduca)) if caduca else None
    except Exception:  # noqa: BLE001
        return None


def _avisar(texto):
    from app.notificaciones import enviar_telegram
    try:
        enviar_telegram(texto)
    except Exception:  # noqa: BLE001
        pass


def comprobar_todo():
    """Una ronda de vigilancia. La llama el reloj cada 2 minutos y el botón «Comprobar ahora»."""
    with _CERROJO:
        _ronda()


def _ronda():
    asegurar_por_defecto()
    sistemas = SistemaVigilado.query.filter_by(activo=True).order_by(SistemaVigilado.orden).all()
    if not sistemas:
        return
    ahora = datetime.utcnow()
    urls = [s.url for s in sistemas]
    revisar_ssl = [s.url if (not s.ssl_comprobado or ahora - s.ssl_comprobado > SSL_CADA) else None for s in sistemas]
    # Todas a la vez (en paralelo): una web lenta no retrasa a las demás
    with ThreadPoolExecutor(max_workers=6) as pool:
        resultados = list(pool.map(_probar, urls))
        caducidades = list(pool.map(lambda u: _caducidad_ssl(u) if u else None, revisar_ssl))

    for s, r, caduca, mirado_ssl in zip(sistemas, resultados, caducidades, revisar_ssl):
        s.ultima_comprobacion = ahora
        s.ultimo_codigo = r["codigo"]
        s.ultimo_ms = r["ms"]
        if mirado_ssl:
            s.ssl_comprobado = ahora
            antes = s.ssl_caduca
            if caduca:
                s.ssl_caduca = caduca
                dias = (caduca - ahora).days
                # Aviso una sola vez al cruzar el umbral (no cada hora)
                if dias <= SSL_AVISO_DIAS and (not antes or (antes - ahora).days > SSL_AVISO_DIAS):
                    _avisar(f"🔒 El candado HTTPS de {s.nombre} caduca en {dias} día(s).\n{s.url}\nNormalmente se renueva solo; si no, revisa el dominio en su alojamiento.")
        if r["ok"]:
            s.ms_medio = r["ms"] if not s.ms_medio else int(s.ms_medio * 0.8 + r["ms"] * 0.2)
            s.ultimo_error = None
            if s.estado == "caido" or s.caido_desde:
                incidencia = IncidenciaSistema.query.filter_by(sistema_id=s.id, fin=None).order_by(IncidenciaSistema.id.desc()).first()
                minutos = 0
                if incidencia:
                    incidencia.fin = ahora
                    minutos = max(1, round((ahora - incidencia.inicio).total_seconds() / 60))
                _avisar(f"🟢 {s.nombre} vuelve a funcionar.\nEstuvo caído {duracion(minutos)}.\n{s.url}")
            s.fallos_seguidos = 0
            s.caido_desde = None
            s.estado = "lento" if r["ms"] >= LENTO_MS else "ok"
        else:
            s.ultimo_error = r["error"]
            s.fallos_seguidos = (s.fallos_seguidos or 0) + 1
            if s.fallos_seguidos >= FALLOS_PARA_CAIDO and s.estado != "caido":
                # El primer fallo fue hace ~2 minutos: la caída empezó entonces
                inicio = ahora - timedelta(minutes=INTERVALO_MIN * (s.fallos_seguidos - 1))
                s.estado = "caido"
                s.caido_desde = inicio
                db.session.add(IncidenciaSistema(sistema_id=s.id, inicio=inicio, motivo=r["error"]))
                _avisar(f"🔴 {s.nombre} NO RESPONDE desde las {hora_madrid(inicio)}.\nMotivo: {r['error']}\n{s.url}")
            # Un solo fallo suelto no cambia el semáforo: se espera a la siguiente ronda
    db.session.commit()


def cerrar_incidencias_abiertas(sistema):
    """Al pausar o borrar un sistema: su caída abierta termina ahora (para no contarla para siempre)."""
    for inc in IncidenciaSistema.query.filter_by(sistema_id=sistema.id, fin=None).all():
        inc.fin = datetime.utcnow()
    sistema.estado = "desconocido"
    sistema.fallos_seguidos = 0
    sistema.caido_desde = None


def resumen():
    """Lo que ve la pantalla «Estado de los sistemas»."""
    asegurar_por_defecto()
    ahora = datetime.utcnow()
    hace30 = ahora - timedelta(days=30)
    sistemas = SistemaVigilado.query.order_by(SistemaVigilado.orden, SistemaVigilado.id).all()
    lista = []
    for s in sistemas:
        # Tiempo caído en los últimos 30 días (desde que se vigila, si es más reciente)
        desde = max(hace30, s.creado or hace30)
        total = max(1.0, (ahora - desde).total_seconds())
        caido = 0.0
        for inc in IncidenciaSistema.query.filter(IncidenciaSistema.sistema_id == s.id,
                                                  db.or_(IncidenciaSistema.fin.is_(None), IncidenciaSistema.fin >= desde)).all():
            caido += ((inc.fin or ahora) - max(inc.inicio, desde)).total_seconds()
        lista.append({
            "id": s.id,
            "nombre": s.nombre,
            "url": s.url,
            "tipo": s.tipo,
            "activo": bool(s.activo),
            "estado": s.estado if s.activo else "pausado",
            "codigo": s.ultimo_codigo,
            "ms": s.ultimo_ms,
            "ms_medio": s.ms_medio,
            "error": s.ultimo_error,
            "ultima_comprobacion": (s.ultima_comprobacion.isoformat() + "Z") if s.ultima_comprobacion else None,
            "caido_desde": (s.caido_desde.isoformat() + "Z") if s.caido_desde else None,
            "disponibilidad_30d": round(max(0.0, 100 - caido * 100 / total), 2),
            "ssl_dias": (s.ssl_caduca - ahora).days if s.ssl_caduca else None,
        })
    incidencias = IncidenciaSistema.query.order_by(IncidenciaSistema.inicio.desc()).limit(40).all()
    return {"sistemas": lista, "incidencias": [i.to_dict() for i in incidencias], "intervalo_min": INTERVALO_MIN}
