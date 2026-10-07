from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.auth import registrar_proteccion
import os

db = SQLAlchemy()
# Aviso: el almacenamiento en memoria de Flask-Limiter asume UN SOLO
# proceso (igual que el backup automático) — el Procfile actual no usa
# --workers, así que vale. Si algún día escalas a varios workers,
# habría que pasar a un almacenamiento compartido (ej. Redis).
limiter = Limiter(get_remote_address, default_limits=[])


def _origenes_permitidos():
    """De dónde puede llegar tráfico a esta API. Por defecto, solo tu
    propio panel — y localhost, para poder seguir probando en tu
    ordenador durante el desarrollo. Añade más dominios (ej. si compras
    firztnet.es) con la variable de entorno ORIGENES_EXTRA, separados
    por comas."""
    origenes = [
        os.environ.get("FRONTEND_URL", "https://firztnet-preview.vercel.app"),
        "http://localhost:5173",  # Vite en local
        "http://localhost:3000",
    ]
    extra = os.environ.get("ORIGENES_EXTRA", "")
    origenes += [o.strip() for o in extra.split(",") if o.strip()]
    return origenes


CLAVES_POR_DEFECTO = {
    "SECRET_KEY": "cambia-esta-clave-en-produccion",
    "ADMIN_PASSWORD": "cambia-esta-contraseña",
}


def en_railway():
    """Railway pone estas variables él solo en cada despliegue."""
    return any(os.environ.get(v) for v in ("RAILWAY_ENVIRONMENT", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_PROJECT_ID"))


def _exigir_claves_propias(app):
    """En Railway, el servidor NO arranca si falta SECRET_KEY o ADMIN_PASSWORD
    (o si siguen con el valor de ejemplo del código). Con la SECRET_KEY de
    ejemplo, cualquiera que la conozca podría fabricarse un acceso al panel
    sin saber tu contraseña. Mejor que no arranque a que arranque abierto."""
    if not en_railway():
        return  # en tu ordenador se puede probar con las de ejemplo
    problemas = []
    for nombre, valor_ejemplo in CLAVES_POR_DEFECTO.items():
        valor = app.config.get(nombre) or ""
        if not valor or valor == valor_ejemplo:
            problemas.append(f"{nombre} no está configurada en Railway (se está usando la de ejemplo del código)")
    if problemas:
        raise RuntimeError(
            "El servidor no arranca por seguridad: " + "; ".join(problemas)
            + ". Añádelas en Railway > tu servicio > Variables y vuelve a desplegar."
        )


def comprobar_almacenamiento(app):
    """Al arrancar en Railway, comprueba que la base de datos, las fotos y las
    firmas se guardan en el disco permanente (el "volumen"). Si algo está fuera,
    se borraría en el siguiente despliegue: en ese caso te avisa por Telegram.
    No para el servidor; solo avisa."""
    if not en_railway():
        return
    from app.routes.fotos import FOTOS_DIR
    from app.firmas import FIRMAS_DIR

    volumen = os.environ.get("RAILWAY_VOLUME_MOUNT_PATH")
    uri = app.config["SQLALCHEMY_DATABASE_URI"]
    rutas = {"las fotos": FOTOS_DIR, "las firmas": FIRMAS_DIR}
    if uri.startswith("sqlite"):
        rutas["la base de datos"] = uri[len("sqlite:///"):]  # "sqlite:////data/x.db" -> "/data/x.db"

    if not volumen:
        fuera = list(rutas.keys())
        motivo = "porque este servicio no tiene ningún disco permanente (volumen) conectado"
    else:
        raiz = os.path.abspath(volumen)
        fuera = [que for que, ruta in rutas.items() if not os.path.abspath(ruta).startswith(raiz + os.sep) and os.path.abspath(ruta) != raiz]
        motivo = f"porque están fuera del disco permanente ({volumen})"

    if len(app.config.get("SECRET_KEY") or "") < 32:
        from app.notificaciones import enviar_telegram
        try:
            enviar_telegram("⚠️ AVISO DE SEGURIDAD de Firztnet: tu SECRET_KEY de Railway es corta. "
                            "Conviene cambiarla por una de al menos 32 caracteres (tendrás que volver a iniciar sesión).")
        except Exception:
            pass

    if fuera:
        from app.notificaciones import enviar_telegram
        try:
            enviar_telegram(
                "⚠️ AVISO DE CONFIGURACIÓN de Firztnet: " + ", ".join(fuera)
                + f" se perderían en el próximo despliegue, {motivo}. "
                "Revisa en Railway las variables DATABASE_URL, FOTOS_DIR y FIRMAS_DIR."
            )
        except Exception:
            pass


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")
    _exigir_claves_propias(app)

    # Railway pasa cada petición por su propio "proxy": sin esto, el servidor ve
    # la misma IP (la del proxy) para todo el mundo, y los límites de intentos
    # (login, seguimiento público) se compartían entre todos — un desconocido
    # podía dejarte a TI sin poder entrar. ProxyFix toma la IP real que añade Railway.
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    db.init_app(app)
    CORS(app, origins=_origenes_permitidos())  # solo tu panel (y localhost en desarrollo) puede llamar a esta API
    registrar_proteccion(app)  # exige login (token) en toda la API
    limiter.init_app(app)

    from app.routes.auth import auth_bp
    from app.routes.clientes import clientes_bp
    from app.routes.reparaciones import reparaciones_bp
    from app.routes.repuestos import repuestos_bp
    from app.routes.proveedores import proveedores_bp
    from app.routes.finanzas import finanzas_bp
    from app.routes.reportes import reportes_bp
    from app.routes.comprobantes import comprobantes_bp
    from app.routes.configuracion import configuracion_bp
    from app.routes.recibos import recibos_bp
    from app.routes.facturas import facturas_bp
    from app.routes.seguimiento import seguimiento_bp
    from app.routes.fotos import fotos_bp
    from app.routes.checklist import checklist_bp
    from app.routes.presupuestos import presupuestos_bp
    from app.routes.plantillas import plantillas_bp
    from app.routes.rma import rma_bp
    from app.routes.solicitudes import solicitudes_bp
    from app.routes.sugerencias import sugerencias_bp
    from app.routes.backup import backup_bp
    from app.routes.sesiones import sesiones_bp
    from app.routes.conocimiento import conocimiento_bp
    from app.routes.recordatorios import recordatorios_bp
    from app.routes.parte_trabajo import parte_trabajo_bp
    from app.routes.estadisticas import estadisticas_bp
    from app.routes.ventas import ventas_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(clientes_bp, url_prefix="/api/clientes")
    app.register_blueprint(reparaciones_bp, url_prefix="/api/reparaciones")
    app.register_blueprint(repuestos_bp, url_prefix="/api/repuestos")
    app.register_blueprint(proveedores_bp, url_prefix="/api/proveedores")
    app.register_blueprint(finanzas_bp, url_prefix="/api/finanzas")
    app.register_blueprint(reportes_bp, url_prefix="/api/reportes")
    app.register_blueprint(comprobantes_bp, url_prefix="/api/comprobantes")
    app.register_blueprint(configuracion_bp, url_prefix="/api/configuracion")
    app.register_blueprint(recibos_bp, url_prefix="/api/recibos")
    app.register_blueprint(facturas_bp, url_prefix="/api/facturas")
    app.register_blueprint(seguimiento_bp, url_prefix="/api/seguimiento")
    app.register_blueprint(fotos_bp, url_prefix="/api")
    app.register_blueprint(checklist_bp, url_prefix="/api/checklist")
    app.register_blueprint(presupuestos_bp, url_prefix="/api")
    app.register_blueprint(plantillas_bp, url_prefix="/api/plantillas")
    app.register_blueprint(rma_bp, url_prefix="/api/rma")
    app.register_blueprint(solicitudes_bp, url_prefix="/api/solicitudes")
    app.register_blueprint(sugerencias_bp, url_prefix="/api/sugerencias")
    app.register_blueprint(backup_bp, url_prefix="/api/backup")
    app.register_blueprint(sesiones_bp, url_prefix="/api")
    app.register_blueprint(conocimiento_bp, url_prefix="/api/conocimiento")
    app.register_blueprint(recordatorios_bp, url_prefix="/api/recordatorios")
    app.register_blueprint(parte_trabajo_bp, url_prefix="/api")
    app.register_blueprint(estadisticas_bp, url_prefix="/api/estadisticas")
    app.register_blueprint(ventas_bp, url_prefix="/api/ventas")

    @app.get("/api/salud")
    def salud():
        return {"estado": "ok", "servicio": "Firztnet - gestión de reparaciones"}

    @app.errorhandler(413)
    def _archivo_demasiado_grande(e):
        from flask import jsonify
        return jsonify({"error": "El archivo (o la suma de archivos) supera el límite de 30 MB por subida."}), 413

    @app.errorhandler(429)
    def _demasiadas_peticiones(e):
        from flask import jsonify, request
        if request.path == "/api/auth/login":
            from app.notificaciones import enviar_telegram
            from app.routes.auth import _ip_real
            try:
                enviar_telegram(f"🚨 POSIBLE ATAQUE: se ha bloqueado el login por demasiados intentos fallidos seguidos.\nIP: {_ip_real()}")
            except Exception:
                pass
        return jsonify({"error": "Demasiados intentos seguidos. Espera un minuto y vuelve a intentarlo."}), 429

    @app.after_request
    def _cabeceras_seguridad(response):
        """Protecciones estándar de navegador, sin coste ni configuración:
        evitan que un navegador "adivine" el tipo de un archivo subido
        (X-Content-Type-Options), que alguien intente meter tu panel
        dentro de un iframe ajeno para engañar a un usuario
        (X-Frame-Options), y refuerzan que todo vaya siempre por HTTPS
        (Strict-Transport-Security)."""
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    _programar_backup_automatico(app)

    return app


def _programar_backup_automatico(app):
    """Backup diario automático (a las 4:00 UTC), enviado por Telegram
    si lo tienes configurado — si no, no hace nada (no rompe nada).

    Aviso: esto asume UN SOLO proceso de gunicorn (el Procfile actual
    no especifica --workers, así que por defecto es 1). Si algún día
    escalas a varios workers, esta tarea se dispararía una vez por
    worker — habría que moverla a un servicio de cron aparte en ese
    caso."""
    import os
    if os.environ.get("DESACTIVAR_BACKUP_AUTOMATICO") == "true":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        return  # si la librería no está instalada, simplemente no se programa nada

    def _tarea_backup():
        with app.app_context():
            from app.backup import crear_backup_zip
            from app.notificaciones import enviar_documento_telegram, enviar_telegram
            try:
                nombre_archivo, buffer = crear_backup_zip()
                contenido = buffer.read()
                tamano_mb = len(contenido) / (1024 * 1024)
                if tamano_mb > 49:
                    # Telegram no deja mandar archivos de más de 50 MB.
                    enviar_telegram(
                        f"❌ El backup automático de hoy NO se ha enviado: pesa {tamano_mb:.0f} MB y Telegram "
                        "solo admite 50 MB. Descárgalo a mano desde el panel (Ajustes > Copia de seguridad)."
                    )
                    return
                ok, detalle = enviar_documento_telegram(nombre_archivo, contenido, caption=f"📦 Backup automático diario — {nombre_archivo}")
                if not ok:
                    enviar_telegram(f"❌ El backup automático de hoy no se pudo enviar: {detalle}")
            except Exception as e:
                # Un fallo en el backup nunca debe tumbar el servidor, pero ya no se calla: te avisa.
                try:
                    enviar_telegram(f"❌ El backup automático de hoy ha FALLADO: {e}")
                except Exception:
                    pass

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_tarea_backup, "cron", hour=4, minute=0)
    scheduler.start()
