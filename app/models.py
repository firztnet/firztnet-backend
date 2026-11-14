from datetime import datetime, timedelta
import secrets
from app import db

GARANTIA_MESES = 6


# Negocios a los que puede pertenecer un cliente (en este orden canónico).
NEGOCIOS_CLIENTE = ("firztnet", "firztweb")



def _iso_utc(fecha):
    """Las fechas-hora se guardan en hora universal (UTC) sin zona. Se envían al panel
    con una "Z" al final para que el navegador sepa que son UTC y las pase solo a la
    hora de Madrid (sin la Z, las tomaba como si ya fueran de Madrid: 1-2 horas de error)."""
    return (fecha.isoformat() + "Z") if fecha else None

class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30))
    email = db.Column(db.String(120))
    nif = db.Column(db.String(20))  # solo hace falta si pide factura
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)
    # True = alguien que escribió desde una web pero todavía no es cliente: no sale en la lista de
    # Clientes ni cuenta como "cliente nuevo" hasta que se pulsa "Convertir en cliente".
    es_contacto = db.Column(db.Boolean, default=False)
    # Etiquetas de negocio separadas por coma: "firztnet", "firztweb" o "firztnet,firztweb".
    # Una misma persona puede ser cliente de los dos (te trae un portátil y luego te pide una web).
    negocios = db.Column(db.String(60), default="firztnet")

    reparaciones = db.relationship("Reparacion", backref="cliente", lazy=True)

    def lista_negocios(self):
        presentes = {n.strip() for n in (self.negocios or "firztnet").split(",") if n.strip()}
        return [n for n in NEGOCIOS_CLIENTE if n in presentes] or ["firztnet"]

    def poner_negocios(self, lista):
        presentes = set(lista)
        self.negocios = ",".join(n for n in NEGOCIOS_CLIENTE if n in presentes) or "firztnet"

    def anadir_negocio(self, negocio):
        if negocio in NEGOCIOS_CLIENTE:
            self.poner_negocios(self.lista_negocios() + [negocio])

    def to_dict(self):
        return {
            "id": self.id,
            "codigo": self.codigo,
            "nombre": self.nombre,
            "telefono": self.telefono,
            "email": self.email,
            "nif": self.nif,
            "es_contacto": bool(self.es_contacto),
            "negocios": self.lista_negocios(),
        }


class Estado(db.Model):
    """Tabla de referencia para el kanban: Recibido, Diagnóstico, En reparación,
    Listo para entrega, Entregado, No reparable."""
    __tablename__ = "estados"
    codigo = db.Column(db.String(30), primary_key=True)
    nombre = db.Column(db.String(60), nullable=False)
    orden = db.Column(db.Integer, nullable=False)


class Proveedor(db.Model):
    __tablename__ = "proveedores"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30))
    email = db.Column(db.String(120))

    repuestos = db.relationship("Repuesto", backref="proveedor", lazy=True)

    def to_dict(self):
        return {"id": self.id, "nombre": self.nombre, "telefono": self.telefono, "email": self.email}


class Repuesto(db.Model):
    __tablename__ = "repuestos"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    categoria = db.Column(db.String(60))
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"))
    stock_actual = db.Column(db.Integer, default=0)
    stock_minimo = db.Column(db.Integer, default=1)
    precio_compra = db.Column(db.Numeric(10, 2), default=0)
    precio_venta = db.Column(db.Numeric(10, 2), default=0)
    activo = db.Column(db.Boolean, default=True)  # baja lógica — no se borra físicamente, para no romper el historial de reparaciones/ventas que ya lo usaron

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "categoria": self.categoria,
            "proveedor_id": self.proveedor_id,
            "stock_actual": self.stock_actual,
            "stock_minimo": self.stock_minimo,
            "stock_bajo": self.stock_actual <= self.stock_minimo,
            "activo": bool(self.activo) if self.activo is not None else True,
            "precio_compra": float(self.precio_compra or 0),
            "precio_venta": float(self.precio_venta or 0),
        }


class Reparacion(db.Model):
    __tablename__ = "reparaciones"
    id = db.Column(db.Integer, primary_key=True)
    numero_orden = db.Column(db.String(20), unique=True, nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)

    equipo = db.Column(db.String(120), nullable=False)
    tipo_trabajo = db.Column(db.String(20), default="taller")  # 'taller' o 'domicilio'
    categoria = db.Column(db.String(40))  # redes, camaras, impresoras, mantenimiento_empresas...
    direccion_servicio = db.Column(db.String(200))  # solo para 'domicilio'
    wifi_ssid = db.Column(db.String(80))  # solo si el servicio es de redes/instalación
    wifi_password = db.Column(db.String(120))
    marca = db.Column(db.String(60))
    modelo = db.Column(db.String(60))
    urgente = db.Column(db.Boolean, default=False)
    tecnico = db.Column(db.String(60))  # nombre del técnico responsable (sin login propio, de momento)
    accesorios_entregados = db.Column(db.String(255))
    problema_reportado = db.Column(db.Text)
    estado_entrada = db.Column(db.Text)  # rayones, golpes, etc. al recibir

    estado_actual = db.Column(db.String(30), db.ForeignKey("estados.codigo"), default="recibido")
    motivo_no_reparable = db.Column(db.Text)

    fecha_recepcion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_estimada = db.Column(db.DateTime)
    fecha_entrega = db.Column(db.DateTime)
    fecha_listo = db.Column(db.DateTime)  # cuándo quedó listo para recoger (para detectar abandono)
    fecha_fin_garantia = db.Column(db.DateTime)

    # Identificador aleatorio (no adivinable, a diferencia del nº de orden
    # que es correlativo) para la página pública de seguimiento del cliente.
    token_seguimiento = db.Column(db.String(40), unique=True, default=lambda: secrets.token_hex(8))

    # Presupuesto: uno activo por reparación. estado: pendiente / aceptado / rechazado
    presupuesto_importe = db.Column(db.Numeric(10, 2))
    presupuesto_descripcion = db.Column(db.Text)
    presupuesto_estado = db.Column(db.String(20))
    presupuesto_fecha = db.Column(db.DateTime)

    # Mantenimientos: si la orden es "un mes" de un contrato de mantenimiento, aquí va el
    # contrato y el mes ("2026-11"). Esas órdenes no salen en el tablero de reparaciones:
    # solo guardan los cobros de la cuota de ese mes, y las visitas cuelgan de ellas.
    contrato_id = db.Column(db.Integer, db.ForeignKey("contratos_mantenimiento.id"), nullable=True, index=True)
    periodo = db.Column(db.String(7), nullable=True)
    cuota_mes = db.Column(db.Numeric(10, 2), nullable=True)  # cuota acordada para ese mes (si luego cambia la cuota, los meses ya cobrados no cambian)

    repuestos_usados = db.relationship("ReparacionRepuesto", backref="reparacion", lazy=True)
    movimientos = db.relationship("MovimientoFinanciero", backref="reparacion", lazy=True)
    comprobantes = db.relationship("Comprobante", backref="reparacion", lazy=True)

    def marcar_entregada(self, con_garantia=True):
        """con_garantia=False cuando el equipo se entrega SIN haberse
        reparado (venía de 'no_reparable') — no tiene sentido darle
        garantía a algo que no se arregló."""
        self.estado_actual = "entregado"
        self.fecha_entrega = datetime.utcnow()
        if con_garantia:
            self.fecha_fin_garantia = self.fecha_entrega + timedelta(days=30 * GARANTIA_MESES)

    def marcar_completada(self):
        """Equivalente a 'entregada', pero para servicios a domicilio."""
        self.estado_actual = "completado"
        self.fecha_entrega = datetime.utcnow()
        self.fecha_fin_garantia = self.fecha_entrega + timedelta(days=30 * GARANTIA_MESES)

    def marcar_no_reparable(self, motivo):
        self.estado_actual = "no_reparable"
        self.motivo_no_reparable = motivo

    def to_dict(self):
        return {
            "id": self.id,
            "numero_orden": self.numero_orden,
            "cliente": self.cliente.to_dict() if self.cliente else None,
            "equipo": self.equipo,
            "tipo_trabajo": self.tipo_trabajo or "taller",
            "categoria": self.categoria,
            "direccion_servicio": self.direccion_servicio,
            "wifi_ssid": self.wifi_ssid,
            "wifi_password": self.wifi_password,
            "marca": self.marca,
            "modelo": self.modelo,
            "urgente": bool(self.urgente),
            "tecnico": self.tecnico,
            "accesorios_entregados": self.accesorios_entregados,
            "problema_reportado": self.problema_reportado,
            "estado_entrada": self.estado_entrada,
            "estado_actual": self.estado_actual,
            "motivo_no_reparable": self.motivo_no_reparable,
            "fecha_recepcion": _iso_utc(self.fecha_recepcion),
            "fecha_estimada": self.fecha_estimada.isoformat() if self.fecha_estimada else None,
            "fecha_entrega": _iso_utc(self.fecha_entrega),
            "fecha_listo": _iso_utc(self.fecha_listo),
            "fecha_fin_garantia": _iso_utc(self.fecha_fin_garantia),
            "token_seguimiento": self.token_seguimiento,
            "presupuesto_importe": float(self.presupuesto_importe) if self.presupuesto_importe is not None else None,
            "presupuesto_descripcion": self.presupuesto_descripcion,
            "presupuesto_estado": self.presupuesto_estado,
            "presupuesto_fecha": _iso_utc(self.presupuesto_fecha),
            "contrato_id": self.contrato_id,
            "periodo": self.periodo,
        }


class RegistroRGPD(db.Model):
    """Constancia de que se atendió una solicitud de 'derecho al
    olvido' — sin guardar los datos que ya se borraron, solo que
    existió la solicitud y cuándo, por si algún día hay que
    demostrar que se cumplió."""
    __tablename__ = "registros_rgpd"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, nullable=False)  # se guarda el id, pero el cliente ya queda anonimizado
    nombre_en_el_momento = db.Column(db.String(120))
    motivo = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "cliente_id": self.cliente_id,
            "nombre_en_el_momento": self.nombre_en_el_momento,
            "motivo": self.motivo,
            "fecha": _iso_utc(self.fecha),
        }


class Venta(db.Model):
    """Una venta de tus otros negocios — webs, apps, sistemas a medida
    (Firztweb) o productos de afiliados — para llevar el control en el
    mismo sitio que todo lo demás, sin depender de hojas sueltas."""
    __tablename__ = "ventas"
    id = db.Column(db.Integer, primary_key=True)
    negocio = db.Column(db.String(20), nullable=False, default="firztweb")  # 'firztnet', 'firztweb', 'afiliados'
    tipo = db.Column(db.String(20), nullable=False)  # 'web', 'app', 'sistema', 'afiliado', 'otro'
    cliente_nombre = db.Column(db.String(150))  # obligatorio salvo en ventas de afiliados (ahí no hay "cliente" propiamente)
    producto = db.Column(db.String(200))  # solo para afiliados: qué producto se vendió
    importe_total_venta = db.Column(db.Float)  # solo para afiliados: precio total del producto (antes de comisión)
    porcentaje_comision = db.Column(db.Float)  # solo para afiliados: % usado para calcular la comisión
    descripcion = db.Column(db.Text)
    importe = db.Column(db.Float, nullable=False, default=0)  # lo que realmente ingresas — en afiliados, la comisión ya calculada
    cobrado = db.Column(db.Boolean, default=False)
    enlace_nota = db.Column(db.String(500))  # ej. el enlace de afiliado, o cualquier nota suelta
    fecha = db.Column(db.Date, nullable=False, default=lambda: datetime.utcnow().date())
    fecha_creacion = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "negocio": self.negocio,
            "tipo": self.tipo,
            "cliente_nombre": self.cliente_nombre,
            "producto": self.producto,
            "importe_total_venta": self.importe_total_venta,
            "porcentaje_comision": self.porcentaje_comision,
            "descripcion": self.descripcion,
            "importe": self.importe,
            "cobrado": bool(self.cobrado),
            "enlace_nota": self.enlace_nota,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "fecha_creacion": _iso_utc(self.fecha_creacion),
        }


class VisitaWeb(db.Model):
    """Un registro por cada carga de página en tus webs públicas
    (Firztnet, Firztweb...) — contador propio, sin depender de
    ningún servicio externo."""
    __tablename__ = "visitas_web"
    id = db.Column(db.Integer, primary_key=True)
    sitio = db.Column(db.String(40), nullable=False)  # 'firztnet', 'firztweb', etc.
    ruta = db.Column(db.String(200))  # ej. '/', '/#contacto'
    referido = db.Column(db.String(300))  # de dónde venía (Google, directo...)
    dispositivo = db.Column(db.String(20), default="desconocido")  # 'movil' o 'escritorio'
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "sitio": self.sitio,
            "ruta": self.ruta,
            "referido": self.referido,
            "dispositivo": self.dispositivo,
            "fecha": _iso_utc(self.fecha),
        }


class EventoWeb(db.Model):
    """Un clic en un botón concreto, o una sección que el visitante ha
    visto al hacer scroll — para saber qué funciona de verdad en la
    página, no solo cuánta gente entra."""
    __tablename__ = "eventos_web"
    id = db.Column(db.Integer, primary_key=True)
    sitio = db.Column(db.String(40), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'clic' o 'seccion_vista'
    etiqueta = db.Column(db.String(80), nullable=False)  # ej. 'boton_presupuesto', 'seccion_servicios'
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "sitio": self.sitio,
            "tipo": self.tipo,
            "etiqueta": self.etiqueta,
            "fecha": _iso_utc(self.fecha),
        }


class SolicitudServicio(db.Model):
    """Petición de servicio — puede venir de un cliente ya conocido
    (desde su página de seguimiento, "necesito otro servicio") o de un
    contacto totalmente nuevo (desde el formulario público de
    presupuesto, sin historial previo). No crea una reparación sola,
    solo te avisa para que tú la deis de alta cuando la veas."""
    __tablename__ = "solicitudes_servicio"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    mensaje = db.Column(db.Text)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    atendida = db.Column(db.Boolean, default=False)
    origen = db.Column(db.String(20), default="existente")  # 'existente' o 'nuevo_contacto'
    negocio = db.Column(db.String(20), default="firztnet")  # 'firztnet' o 'firztweb' — a cuál de tus dos negocios pertenece

    cliente = db.relationship("Cliente")

    def to_dict(self):
        return {
            "id": self.id,
            "cliente_id": self.cliente_id,
            "cliente": self.cliente.to_dict() if self.cliente else None,
            "mensaje": self.mensaje,
            "fecha": _iso_utc(self.fecha),
            "atendida": bool(self.atendida),
            "origen": self.origen or "existente",
            "negocio": self.negocio or "firztnet",
        }


class RMA(db.Model):
    """Devolución en garantía a un proveedor: pieza defectuosa que
    envías a cambio/reembolso. Con nº de serie para poder rastrearla y
    no perder el dinero si el proveedor tarda o se hace el despistado."""
    __tablename__ = "rmas"
    id = db.Column(db.Integer, primary_key=True)
    repuesto_id = db.Column(db.Integer, db.ForeignKey("repuestos.id"), nullable=True)
    proveedor_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=False)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=True)
    numero_serie = db.Column(db.String(80))
    motivo = db.Column(db.Text, nullable=False)
    estado = db.Column(db.String(20), default="enviado")  # enviado, en_proceso, resuelto, rechazado
    resultado = db.Column(db.String(200))  # ej. "Sustituida por unidad nueva", "Reembolso 25€"
    importe_recuperado = db.Column(db.Numeric(10, 2))
    fecha_envio = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_resolucion = db.Column(db.DateTime)

    repuesto = db.relationship("Repuesto")
    proveedor = db.relationship("Proveedor")
    reparacion = db.relationship("Reparacion")

    def to_dict(self):
        return {
            "id": self.id,
            "repuesto_id": self.repuesto_id,
            "repuesto": self.repuesto.to_dict() if self.repuesto else None,
            "proveedor_id": self.proveedor_id,
            "proveedor": self.proveedor.to_dict() if self.proveedor else None,
            "reparacion_id": self.reparacion_id,
            "reparacion_numero_orden": self.reparacion.numero_orden if self.reparacion else None,
            "numero_serie": self.numero_serie,
            "motivo": self.motivo,
            "estado": self.estado,
            "resultado": self.resultado,
            "importe_recuperado": float(self.importe_recuperado) if self.importe_recuperado is not None else None,
            "fecha_envio": _iso_utc(self.fecha_envio),
            "fecha_resolucion": _iso_utc(self.fecha_resolucion),
        }


class ReparacionRepuesto(db.Model):
    """Tabla puente: qué repuestos (y cuántos) se usaron en cada reparación.
    Los campos de trazabilidad (nº de serie, proveedor, factura de
    compra) son opcionales — solo rellénalos en piezas que valga la
    pena rastrear si fallan (discos, fuentes, cámaras)."""
    __tablename__ = "reparacion_repuestos"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    repuesto_id = db.Column(db.Integer, db.ForeignKey("repuestos.id"), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_aplicado = db.Column(db.Numeric(10, 2), default=0)
    numero_serie = db.Column(db.String(80))
    proveedor_compra_id = db.Column(db.Integer, db.ForeignKey("proveedores.id"), nullable=True)
    numero_factura_compra = db.Column(db.String(60))
    fecha_compra = db.Column(db.Date, nullable=True)

    repuesto = db.relationship("Repuesto")
    proveedor_compra = db.relationship("Proveedor")

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "repuesto": self.repuesto.to_dict() if self.repuesto else None,
            "cantidad": self.cantidad,
            "precio_aplicado": float(self.precio_aplicado or 0),
            "numero_serie": self.numero_serie,
            "proveedor_compra_id": self.proveedor_compra_id,
            "proveedor_compra": self.proveedor_compra.to_dict() if self.proveedor_compra else None,
            "numero_factura_compra": self.numero_factura_compra,
            "fecha_compra": self.fecha_compra.isoformat() if self.fecha_compra else None,
        }


class MovimientoFinanciero(db.Model):
    __tablename__ = "movimientos_financieros"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=True)
    tipo = db.Column(db.String(10), nullable=False)  # 'ingreso' o 'gasto'
    concepto = db.Column(db.String(120))
    monto = db.Column(db.Numeric(10, 2), nullable=False)
    metodo_pago = db.Column(db.String(30))  # efectivo, tarjeta, transferencia
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    # Anulaciones: un movimiento nunca se borra. Si estaba mal, se marca como anulado y se
    # crea otro igual con el importe en negativo que lo compensa (así cuadran los totales
    # y queda constancia de qué se corrigió, cuándo y por qué).
    anulado = db.Column(db.Boolean, default=False)
    motivo_anulacion = db.Column(db.String(200))
    anula_a_id = db.Column(db.Integer, db.ForeignKey("movimientos_financieros.id"), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "tipo": self.tipo,
            "concepto": self.concepto,
            "monto": float(self.monto or 0),
            "metodo_pago": self.metodo_pago,
            "fecha": _iso_utc(self.fecha),
            "anulado": bool(self.anulado),
            "motivo_anulacion": self.motivo_anulacion,
            "anula_a_id": self.anula_a_id,
        }


class PlantillaMensaje(db.Model):
    """Mensajes predefinidos para casos comunes (equipo listo, esperando
    repuesto, presupuesto pendiente...). Si `estado_disparador` coincide
    con un estado del kanban, se usa automáticamente al mover una
    reparación a ese estado — dejando el aviso ya redactado y listo
    para enviar con un clic, sin escribirlo cada vez."""
    __tablename__ = "plantillas_mensaje"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    estado_disparador = db.Column(db.String(30), db.ForeignKey("estados.codigo"), nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "texto": self.texto,
            "estado_disparador": self.estado_disparador,
        }


class ConfiguracionNegocio(db.Model):
    """Fila única (id=1) con los datos del negocio que aparecen en los
    comprobantes: nombre, dirección, teléfono, email. Editable desde el
    panel, sin necesidad de tocar código ni redesplegar."""
    __tablename__ = "configuracion_negocio"
    id = db.Column(db.Integer, primary_key=True)
    nombre_negocio = db.Column(db.String(120), default="Firztnet")
    eslogan = db.Column(db.String(160), default="Reparación y soporte técnico")
    direccion = db.Column(db.String(200))
    telefono = db.Column(db.String(30))
    email = db.Column(db.String(120))
    nif = db.Column(db.String(20))  # necesario para emitir facturas
    iva_pct = db.Column(db.Numeric(5, 2), default=21)  # % de IVA que aplicas
    suplemento_desplazamiento = db.Column(db.Numeric(10, 2), default=20)  # € por servicio a domicilio
    tarifa_hora = db.Column(db.Numeric(10, 2), default=25)  # € por hora de mano de obra
    enlace_resenas_google = db.Column(db.String(300))  # enlace directo a "dejar una reseña" en tu ficha de Google
    tecnicos = db.Column(db.String(300))  # nombres separados por coma, ej: "Carlos, Ana"
    coste_almacenamiento_diario = db.Column(db.Numeric(10, 2), default=1)  # € por día, equipos sin recoger
    telegram_chat_id = db.Column(db.String(40))  # tu chat_id, para recibir avisos internos
    telefono_bizum = db.Column(db.String(20))  # número al que los clientes te pueden mandar un Bizum (sin proveedor de pago contratado)
    # Hasta qué momento has visto la actividad de tus webs. Lo que llegue después es "nuevo" en la campana
    # y en la pantalla Visitas web. Se guarda aquí (y no en el navegador) para que valga igual en el móvil y el ordenador.
    visitas_vistas_hasta = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "nombre_negocio": self.nombre_negocio,
            "eslogan": self.eslogan,
            "direccion": self.direccion,
            "telefono": self.telefono,
            "email": self.email,
            "nif": self.nif,
            "iva_pct": float(self.iva_pct if self.iva_pct is not None else 21),
            "suplemento_desplazamiento": float(self.suplemento_desplazamiento if self.suplemento_desplazamiento is not None else 20),
            "tarifa_hora": float(self.tarifa_hora if self.tarifa_hora is not None else 25),
            "enlace_resenas_google": self.enlace_resenas_google,
            "tecnicos": [t.strip() for t in (self.tecnicos or "").split(",") if t.strip()],
            "coste_almacenamiento_diario": float(self.coste_almacenamiento_diario if self.coste_almacenamiento_diario is not None else 1),
            "telegram_chat_id": self.telegram_chat_id,
            "telefono_bizum": self.telefono_bizum,
        }

    @staticmethod
    def obtener():
        config = ConfiguracionNegocio.query.get(1)
        if not config:
            config = ConfiguracionNegocio(id=1)
            db.session.add(config)
            try:
                db.session.commit()
            except Exception:
                # Dos peticiones a la vez con la base recién creada: la otra ya la ha creado.
                db.session.rollback()
                config = ConfiguracionNegocio.query.get(1)
        return config


class Factura(db.Model):
    """Factura fiscal formal, con numeración correlativa (obligatoria por
    ley: sin huecos, en orden cronológico). Una vez emitida NUNCA se
    borra ni se edita — si hay un error, se corrige emitiendo una
    factura rectificativa (por sustitución: sustituye los importes,
    referenciando la original), con su propia numeración separada."""
    __tablename__ = "facturas"
    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), unique=True, nullable=False)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    concepto = db.Column(db.String(200))
    base_imponible = db.Column(db.Numeric(10, 2), nullable=False)
    iva_pct = db.Column(db.Numeric(5, 2), nullable=False)
    iva_importe = db.Column(db.Numeric(10, 2), nullable=False)
    total = db.Column(db.Numeric(10, 2), nullable=False)
    fecha_emision = db.Column(db.DateTime, default=datetime.utcnow)
    es_rectificativa = db.Column(db.Boolean, default=False)
    factura_original_id = db.Column(db.Integer, db.ForeignKey("facturas.id"), nullable=True)
    motivo_rectificacion = db.Column(db.Text)
    cliente_nombre_congelado = db.Column(db.String(120))  # copia del nombre en el momento de emitirla
    cliente_nif_congelado = db.Column(db.String(20))  # copia del NIF en el momento de emitirla — así, si el
    # cliente pide luego borrar sus datos (RGPD), la factura sigue siendo correcta y legible para Hacienda
    # Lo mismo con TUS datos (el emisor): se copian al emitirla, para que la factura no
    # cambie nunca aunque luego cambies el nombre, el NIF o la dirección en Ajustes.
    emisor_nombre = db.Column(db.String(120))
    emisor_nif = db.Column(db.String(20))
    emisor_direccion = db.Column(db.String(200))
    emisor_telefono = db.Column(db.String(30))
    emisor_email = db.Column(db.String(120))

    reparacion = db.relationship("Reparacion")
    cliente = db.relationship("Cliente")
    factura_original = db.relationship("Factura", remote_side=[id])

    def to_dict(self):
        return {
            "id": self.id,
            "numero": self.numero,
            "reparacion_id": self.reparacion_id,
            "cliente_id": self.cliente_id,
            "concepto": self.concepto,
            "base_imponible": float(self.base_imponible),
            "iva_pct": float(self.iva_pct),
            "iva_importe": float(self.iva_importe),
            "total": float(self.total),
            "fecha_emision": _iso_utc(self.fecha_emision),
            "es_rectificativa": bool(self.es_rectificativa),
            "factura_original_id": self.factura_original_id,
            "factura_original_numero": self.factura_original.numero if self.factura_original else None,
            "motivo_rectificacion": self.motivo_rectificacion,
            "cliente_nombre_congelado": self.cliente_nombre_congelado,
            "cliente_nif_congelado": self.cliente_nif_congelado,
            "emisor_nombre": self.emisor_nombre,
            "emisor_nif": self.emisor_nif,
            "emisor_direccion": self.emisor_direccion,
        }


class Firma(db.Model):
    """Firma digital (dibujada en pantalla) para dos usos: aceptar/rechazar
    un presupuesto a distancia, o confirmar la recogida del equipo en el
    mostrador. El dibujo se guarda como imagen en disco (igual que las
    fotos), aquí solo la referencia."""
    __tablename__ = "firmas"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # 'presupuesto' o 'entrega'
    nombre_firmante = db.Column(db.String(120))
    nombre_archivo = db.Column(db.String(120), nullable=False)
    ip_aceptacion = db.Column(db.String(45))  # IPv4 o IPv6 de quien firmó, como prueba
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "tipo": self.tipo,
            "nombre_firmante": self.nombre_firmante,
            "nombre_archivo": self.nombre_archivo,
            "ip_aceptacion": self.ip_aceptacion,
            "fecha": _iso_utc(self.fecha),
        }


class ChecklistItem(db.Model):
    """Hoja de trabajo de campo: puntos a marcar durante un servicio a
    domicilio (ej. "Router revisado", "Cámara 1 alineada")."""
    __tablename__ = "checklist_items"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    texto = db.Column(db.String(160), nullable=False)
    completado = db.Column(db.Boolean, default=False)
    orden = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "texto": self.texto,
            "completado": bool(self.completado),
            "orden": self.orden,
        }


class SesionTrabajo(db.Model):
    """Cada tramo de tiempo trabajado en una reparación (permite pausar
    y reanudar): se abre al pulsar 'Iniciar servicio' y se cierra al
    pulsar 'Finalizar servicio'. El coste de mano de obra sale de sumar
    la duración de todas las sesiones cerradas de una reparación."""
    __tablename__ = "sesiones_trabajo"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    inicio = db.Column(db.DateTime, default=datetime.utcnow)
    fin = db.Column(db.DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "inicio": _iso_utc(self.inicio),
            "fin": _iso_utc(self.fin),
        }


class ArticuloConocimiento(db.Model):
    """Base de conocimiento interna: trucos y configuraciones rápidas
    (IPs por defecto de routers, comandos de reseteo, puertos de
    impresoras...). Búsqueda simple por título/contenido/categoría."""
    __tablename__ = "articulos_conocimiento"
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(160), nullable=False)
    contenido = db.Column(db.Text, nullable=False)
    categoria = db.Column(db.String(40))
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "titulo": self.titulo,
            "contenido": self.contenido,
            "categoria": self.categoria,
            "creado_en": _iso_utc(self.creado_en),
        }


class Recordatorio(db.Model):
    """Aviso de mantenimiento futuro (revisión de baterías SAI, limpieza
    de filtros, etc.), normalmente programado al cerrar un servicio a
    domicilio, para dentro de 6 o 12 meses."""
    __tablename__ = "recordatorios"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    texto = db.Column(db.String(200), nullable=False)
    fecha_programada = db.Column(db.Date, nullable=False)
    cumplido = db.Column(db.Boolean, default=False)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    cliente = db.relationship("Cliente")

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "cliente_id": self.cliente_id,
            "cliente": self.cliente.to_dict() if self.cliente else None,
            "texto": self.texto,
            "fecha_programada": self.fecha_programada.isoformat() if self.fecha_programada else None,
            "cumplido": bool(self.cumplido),
        }


class FotoReparacion(db.Model):
    """Fotos del estado físico del equipo al recibirlo (rayones, golpes,
    piezas que faltan) — evita disputas con el cliente sobre daños
    previos. El archivo en sí se guarda en disco (en el volumen
    persistente), aquí solo el nombre y la fecha."""
    __tablename__ = "fotos_reparacion"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    nombre_archivo = db.Column(db.String(120), nullable=False)
    fecha_subida = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "nombre_archivo": self.nombre_archivo,
            "fecha_subida": _iso_utc(self.fecha_subida),
        }


class Comprobante(db.Model):
    __tablename__ = "comprobantes"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # recepcion, entrega, no_reparable
    url_pdf = db.Column(db.String(255))
    enlace_seguimiento = db.Column(db.String(255))
    fecha_generado = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "tipo": self.tipo,
            "url_pdf": self.url_pdf,
            "enlace_seguimiento": self.enlace_seguimiento,
            "fecha_generado": _iso_utc(self.fecha_generado),
        }


class OrdenEliminada(db.Model):
    """Registro de las reparaciones borradas con el botón "Eliminar": qué orden era,
    de quién y cuándo se borró. Sirve de historial y, además, para que su número de
    orden no se vuelva a usar nunca (si no, la siguiente orden heredaría el número de
    una borrada y podría confundirse con papeles o etiquetas ya entregados)."""
    __tablename__ = "ordenes_eliminadas"
    id = db.Column(db.Integer, primary_key=True)
    numero_orden = db.Column(db.String(20), nullable=False, index=True)
    cliente_nombre = db.Column(db.String(120))
    equipo = db.Column(db.String(200))
    fecha_eliminacion = db.Column(db.DateTime, default=datetime.utcnow)


ESTADOS_CONTRATO = ("activo", "pendiente", "baja")


class ContratoMantenimiento(db.Model):
    """Mantenimiento periódico con cuota fija mensual (precio final, IVA incluido).
    Cada mes es una "orden" interna (Reparacion con contrato_id y periodo) que guarda
    el cobro de la cuota; dentro de cada mes puede haber varias visitas."""
    __tablename__ = "contratos_mantenimiento"
    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    servicio = db.Column(db.String(100), nullable=False)
    direccion = db.Column(db.String(200))
    wifi_ssid = db.Column(db.String(80))
    wifi_password = db.Column(db.String(120))
    tareas = db.Column(db.Text)  # lo que incluye: una tarea por línea
    cuota = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    estado = db.Column(db.String(20), nullable=False, default="activo")  # activo / pendiente / baja
    fecha_inicio = db.Column(db.Date)
    notas = db.Column(db.Text)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    cliente = db.relationship("Cliente")

    def lista_tareas(self):
        return [t.strip() for t in (self.tareas or "").splitlines() if t.strip()]

    def to_dict(self):
        return {
            "id": self.id,
            "cliente": self.cliente.to_dict() if self.cliente else None,
            "servicio": self.servicio,
            "direccion": self.direccion,
            "wifi_ssid": self.wifi_ssid,
            "wifi_password": self.wifi_password,
            "tareas": self.lista_tareas(),
            "cuota": float(self.cuota or 0),
            "estado": self.estado,
            "fecha_inicio": self.fecha_inicio.isoformat() if self.fecha_inicio else None,
            "notas": self.notas,
        }


class VisitaMantenimiento(db.Model):
    """Una visita dentro de un mes de mantenimiento (puede haber varias al mes).
    No lleva cobro: va incluida en la cuota del mes."""
    __tablename__ = "visitas_mantenimiento"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False, index=True)  # el mes
    fecha = db.Column(db.Date, nullable=False)  # día de la visita
    inicio = db.Column(db.DateTime)
    fin = db.Column(db.DateTime)
    tareas_hechas = db.Column(db.Text)  # JSON: lista de las tareas marcadas
    notas = db.Column(db.Text)
    firma_archivo = db.Column(db.String(120))
    nombre_firmante = db.Column(db.String(120))
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        import json
        try:
            hechas = json.loads(self.tareas_hechas or "[]")
        except ValueError:
            hechas = []
        minutos = None
        if self.inicio and self.fin:
            minutos = max(0, int((self.fin - self.inicio).total_seconds() // 60))
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "inicio": _iso_utc(self.inicio),
            "fin": _iso_utc(self.fin),
            "minutos": minutos,
            "tareas_hechas": hechas,
            "notas": self.notas,
            "firmada": bool(self.firma_archivo),
            "nombre_firmante": self.nombre_firmante,
        }


class PeticionAyuda(db.Model):
    """Firztnet Central: un local que usa uno de tus sistemas (hostelería,
    peluquerías...) pide ayuda desde su panel con el botón «Pedir ayuda».
    Llega de servidor a servidor con la clave propia de cada sistema. Tú la
    ves en «Ayuda a clientes», cambias su estado y le respondes: el local
    ve tu respuesta en su panel. Solo datos del negocio y de quien pide
    ayuda, nunca de los clientes de ese negocio."""
    __tablename__ = "peticiones_ayuda"
    id = db.Column(db.Integer, primary_key=True)
    sistema = db.Column(db.String(20), nullable=False)  # 'hosteleria', 'peluquerias'...: sale de la clave, no de lo que mande
    cliente_ref = db.Column(db.String(200), nullable=False, index=True)  # dirección del local + nº de negocio
    negocio = db.Column(db.String(120), nullable=False)
    empresa = db.Column(db.String(160))
    direccion_web = db.Column(db.String(200))
    persona = db.Column(db.String(80))
    rol = db.Column(db.String(30))
    puesto = db.Column(db.String(120))
    telefono = db.Column(db.String(30))
    tipo = db.Column(db.String(20), default="otro")
    mensaje = db.Column(db.Text, nullable=False)
    urgente = db.Column(db.Boolean, default=False)
    pagina = db.Column(db.String(60))
    navegador = db.Column(db.String(200))
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    estado = db.Column(db.String(20), default="nueva")  # 'nueva', 'en_curso', 'resuelta'
    respuesta = db.Column(db.Text)  # lo que ve el local en su panel
    respuesta_fecha = db.Column(db.DateTime)
    notas = db.Column(db.Text)  # solo para ti
    fecha_resuelta = db.Column(db.DateTime)

    @property
    def referencia(self):
        return f"AY-{self.id:05d}"

    def para_local(self):
        """Lo que ve el propio local en «Tus peticiones» (sin tus notas internas)."""
        return {
            "id": self.id,
            "referencia": self.referencia,
            "tipo": self.tipo,
            "mensaje": self.mensaje,
            "persona": self.persona,
            "fecha": _iso_utc(self.fecha),
            "estado": self.estado,
            "respuesta": self.respuesta,
            "respuesta_fecha": _iso_utc(self.respuesta_fecha) if self.respuesta_fecha else None,
        }

    def to_dict(self):
        return {
            **self.para_local(),
            "sistema": self.sistema,
            "cliente_ref": self.cliente_ref,
            "negocio": self.negocio,
            "empresa": self.empresa,
            "direccion_web": self.direccion_web,
            "rol": self.rol,
            "puesto": self.puesto,
            "telefono": self.telefono,
            "urgente": bool(self.urgente),
            "pagina": self.pagina,
            "navegador": self.navegador,
            "notas": self.notas,
            "fecha_resuelta": _iso_utc(self.fecha_resuelta) if self.fecha_resuelta else None,
        }


class SistemaVigilado(db.Model):
    """Firztnet Central — fase 2: cada sistema o web que Reparaciones vigila
    cada pocos minutos (hostelería, peluquerías, reformas, tus webs...)."""
    __tablename__ = "sistemas_vigilados"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(80), nullable=False)
    url = db.Column(db.String(300), nullable=False)
    tipo = db.Column(db.String(20), default="sistema")  # 'sistema' o 'web'
    activo = db.Column(db.Boolean, default=True)
    orden = db.Column(db.Integer, default=0)
    estado = db.Column(db.String(20), default="desconocido")  # 'ok', 'lento', 'caido', 'desconocido'
    ultimo_codigo = db.Column(db.Integer)
    ultimo_ms = db.Column(db.Integer)
    ms_medio = db.Column(db.Integer)
    ultimo_error = db.Column(db.String(200))
    ultima_comprobacion = db.Column(db.DateTime)
    fallos_seguidos = db.Column(db.Integer, default=0)
    caido_desde = db.Column(db.DateTime)
    ssl_caduca = db.Column(db.DateTime)
    ssl_comprobado = db.Column(db.DateTime)
    # Webs de clientes que se vigilan solas (se añaden y quitan con la lista de clientes de cada plataforma)
    origen = db.Column(db.String(10), default="manual")  # 'manual' o 'auto'
    local_id = db.Column(db.Integer)  # LocalCliente al que pertenece (solo las automáticas)
    sistema_cliente = db.Column(db.String(20))  # de qué plataforma es ese cliente (reciclaje, hosteleria...)
    creado = db.Column(db.DateTime, default=datetime.utcnow)


class IncidenciaSistema(db.Model):
    """Una caída de un sistema vigilado: desde cuándo hasta cuándo y por qué."""
    __tablename__ = "incidencias_sistemas"
    id = db.Column(db.Integer, primary_key=True)
    sistema_id = db.Column(db.Integer, db.ForeignKey("sistemas_vigilados.id"), nullable=False, index=True)
    inicio = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    fin = db.Column(db.DateTime)
    motivo = db.Column(db.String(200))

    sistema = db.relationship("SistemaVigilado")

    def to_dict(self):
        fin = self.fin or datetime.utcnow()
        return {
            "id": self.id,
            "sistema_id": self.sistema_id,
            "sistema": self.sistema.nombre if self.sistema else None,
            "inicio": _iso_utc(self.inicio),
            "fin": _iso_utc(self.fin) if self.fin else None,
            "abierta": self.fin is None,
            "minutos": max(1, round((fin - self.inicio).total_seconds() / 60)),
            "motivo": self.motivo,
        }


class LocalCliente(db.Model):
    """Firztnet Central — fase 3: cada cliente de tus plataformas (un bar, una
    peluquería...), tal como lo manda su plataforma cada 10 minutos. Es la
    «ficha única»: estado, prueba o renovación, contacto, uso, aparatos.
    Las notas son tuyas y no las toca la sincronización."""
    __tablename__ = "locales_clientes"
    id = db.Column(db.Integer, primary_key=True)
    sistema = db.Column(db.String(20), nullable=False, index=True)
    slug = db.Column(db.String(60), nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    tipo = db.Column(db.String(20))
    estado = db.Column(db.String(20))  # 'prueba', 'activo', 'suspendido', 'prueba_vencida', 'baja'
    dias = db.Column(db.Integer)  # días que quedan de prueba (o hasta renovar)
    prueba_hasta = db.Column(db.String(10))
    renueva = db.Column(db.String(10))
    renovacion_vencida = db.Column(db.Boolean, default=False)
    motivo_suspension = db.Column(db.String(300))
    contacto_nombre = db.Column(db.String(120))
    contacto_email = db.Column(db.String(160))
    contacto_telefono = db.Column(db.String(40))
    direccion_web = db.Column(db.String(200))
    alta = db.Column(db.String(40))
    ultimo_uso = db.Column(db.String(40))
    uso_json = db.Column(db.Text)
    negocios_json = db.Column(db.Text)
    aparatos_json = db.Column(db.Text)
    visitas_json = db.Column(db.Text)  # fase 4: visitas de su web por día, aparato y origen
    reservas_json = db.Column(db.Text)  # fase 4: reservas por internet por mes
    notas = db.Column(db.Text)
    sincronizado = db.Column(db.DateTime, default=datetime.utcnow)
    aviso_prueba = db.Column(db.String(10))  # fin de prueba del que ya se avisó (para avisar una sola vez)
    cuota_manual_cents = db.Column(db.Integer)  # lo que te paga al mes, si lo pones tú (manda sobre lo que diga su sistema)
    riesgo_pospuesto_hasta = db.Column(db.DateTime)  # «ya le he llamado»: no sale en «clientes en riesgo» hasta esta fecha
    aviso_cobro = db.Column(db.String(10))  # renovación de la que ya te avisó el recordatorio de cobro
    ultima_copia = db.Column(db.String(40))  # última copia de seguridad de sus datos (si su sistema lo dice)

    __table_args__ = (db.UniqueConstraint("sistema", "slug", name="uq_local_sistema_slug"),)


class EventoCliente(db.Model):
    """Cuadro de mando: cada cambio de estado de un cliente de tus sistemas (alta, pasa a
    activo, termina la prueba, se suspende, se da de baja...), para contar conversiones y bajas."""
    __tablename__ = "eventos_clientes"
    id = db.Column(db.Integer, primary_key=True)
    local_id = db.Column(db.Integer, db.ForeignKey("locales_clientes.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False)  # alta, activo, prueba, prueba_vencida, suspendido, baja
    antes = db.Column(db.String(20))
    fecha = db.Column(db.DateTime, default=datetime.utcnow, index=True)


class ResumenDiario(db.Model):
    """Cuadro de mando: una foto al día de tus ingresos fijos y tus clientes, para ver cómo evolucionan."""
    __tablename__ = "resumen_diario"
    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.Date, nullable=False, unique=True)
    ingresos_mes_cents = db.Column(db.Integer, default=0)
    clientes_pagando = db.Column(db.Integer, default=0)
    clientes_prueba = db.Column(db.Integer, default=0)


class InformeMensual(db.Model):
    """El informe de visitas de un mes para un cliente. Se prepara solo el día 1; solo se
    envía cuando tú lo aceptas en «Informes mensuales»."""
    __tablename__ = "informes_mensuales"
    id = db.Column(db.Integer, primary_key=True)
    local_id = db.Column(db.Integer, db.ForeignKey("locales_clientes.id", ondelete="CASCADE"), nullable=False, index=True)
    mes = db.Column(db.String(7), nullable=False, index=True)  # AAAA-MM
    email = db.Column(db.String(160))
    asunto = db.Column(db.String(200))
    html = db.Column(db.Text)
    visitas = db.Column(db.Integer, default=0)
    cambio_pct = db.Column(db.Integer)
    estado = db.Column(db.String(12), default="preparado")  # preparado, enviado, descartado, error
    error = db.Column(db.String(300))
    creado = db.Column(db.DateTime, default=datetime.utcnow)
    enviado = db.Column(db.DateTime)

    __table_args__ = (db.UniqueConstraint("local_id", "mes", name="uq_informe_local_mes"),)


class PlantillaAyuda(db.Model):
    """Respuestas rápidas para «Ayuda a clientes»: un clic y el texto queda escrito."""
    __tablename__ = "plantillas_ayuda"
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(80), nullable=False)
    texto = db.Column(db.Text, nullable=False)
    orden = db.Column(db.Integer, default=0)

    def to_dict(self):
        return {"id": self.id, "titulo": self.titulo, "texto": self.texto, "orden": self.orden}


class CopiaSistema(db.Model):
    """Copias de seguridad vigiladas: cuándo hizo cada sistema su última copia."""
    __tablename__ = "copias_sistemas"
    id = db.Column(db.Integer, primary_key=True)
    sistema = db.Column(db.String(20), nullable=False, unique=True)
    ultima = db.Column(db.String(40))  # fecha-hora ISO de la última copia, o vacío si el sistema no hace copias
    sin_copias = db.Column(db.Boolean, default=False)  # el sistema dice que no hace copias automáticas
    detalle = db.Column(db.String(200))
    recibido = db.Column(db.DateTime, default=datetime.utcnow)
    avisado = db.Column(db.String(10))  # día del último aviso por Telegram (uno al día como mucho)


# -------------------- FLOTA (vehículos de la empresa) --------------------

TIPOS_REGISTRO_VEHICULO = ("itv", "mantenimiento", "reparacion", "combustible", "seguro", "impuesto", "otro")


class Vehiculo(db.Model):
    """Un vehículo de la empresa: sus datos fijos y las próximas fechas (ITV, seguro, mantenimiento)."""
    __tablename__ = "vehiculos"
    id = db.Column(db.Integer, primary_key=True)
    matricula = db.Column(db.String(15), nullable=False)
    marca = db.Column(db.String(60))
    modelo = db.Column(db.String(60))
    anio = db.Column(db.Integer)
    combustible = db.Column(db.String(20))  # gasolina, diesel, hibrido, electrico, glp
    km_actuales = db.Column(db.Integer, default=0)
    fecha_matriculacion = db.Column(db.Date)
    proxima_itv = db.Column(db.Date)
    seguro_compania = db.Column(db.String(80))
    seguro_poliza = db.Column(db.String(60))
    seguro_vence = db.Column(db.Date)
    proximo_mant_fecha = db.Column(db.Date)
    proximo_mant_km = db.Column(db.Integer)
    intervalo_mant_km = db.Column(db.Integer)     # cada cuántos km toca el mantenimiento (ej. 15000)
    intervalo_mant_meses = db.Column(db.Integer)  # o cada cuántos meses (ej. 12)
    notas = db.Column(db.Text)
    activo = db.Column(db.Boolean, default=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    registros = db.relationship("RegistroVehiculo", backref="vehiculo", lazy="dynamic",
                                cascade="all, delete-orphan", order_by="RegistroVehiculo.fecha.desc()")

    def nombre_corto(self):
        nombre = " ".join(x for x in (self.marca, self.modelo) if x)
        return f"{nombre} ({self.matricula})" if nombre else self.matricula

    def to_dict(self):
        f = lambda d: d.isoformat() if d else None
        return {
            "id": self.id,
            "matricula": self.matricula,
            "marca": self.marca,
            "modelo": self.modelo,
            "anio": self.anio,
            "combustible": self.combustible,
            "km_actuales": self.km_actuales or 0,
            "fecha_matriculacion": f(self.fecha_matriculacion),
            "proxima_itv": f(self.proxima_itv),
            "seguro_compania": self.seguro_compania,
            "seguro_poliza": self.seguro_poliza,
            "seguro_vence": f(self.seguro_vence),
            "proximo_mant_fecha": f(self.proximo_mant_fecha),
            "proximo_mant_km": self.proximo_mant_km,
            "intervalo_mant_km": self.intervalo_mant_km,
            "intervalo_mant_meses": self.intervalo_mant_meses,
            "notas": self.notas,
            "activo": bool(self.activo),
        }


class RegistroVehiculo(db.Model):
    """Lo que le pasa al vehículo: ITV pasada, mantenimiento, reparación, repostaje, seguro, impuesto...
    Si tiene coste y se marca, se apunta además como gasto en Caja (movimiento_id)."""
    __tablename__ = "registros_vehiculo"
    id = db.Column(db.Integer, primary_key=True)
    vehiculo_id = db.Column(db.Integer, db.ForeignKey("vehiculos.id"), nullable=False, index=True)
    tipo = db.Column(db.String(20), nullable=False)
    fecha = db.Column(db.Date, nullable=False)
    km = db.Column(db.Integer)
    coste = db.Column(db.Numeric(10, 2))
    litros = db.Column(db.Numeric(8, 2))       # repostajes
    resultado = db.Column(db.String(20))       # ITV: favorable, desfavorable, negativa
    lugar = db.Column(db.String(100))          # taller, estación ITV, gasolinera...
    descripcion = db.Column(db.Text)
    movimiento_id = db.Column(db.Integer, db.ForeignKey("movimientos_financieros.id"), nullable=True)
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "vehiculo_id": self.vehiculo_id,
            "tipo": self.tipo,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "km": self.km,
            "coste": float(self.coste) if self.coste is not None else None,
            "litros": float(self.litros) if self.litros is not None else None,
            "resultado": self.resultado,
            "lugar": self.lugar,
            "descripcion": self.descripcion,
            "en_caja": bool(self.movimiento_id),
            "movimiento_id": self.movimiento_id,
        }


# -------------------- PUNTO DE VENTA (Firztnet POS en las tiendas) --------------------
# Central da de alta las tiendas, firma sus licencias y recibe su parte. El POS sigue
# funcionando en local sin internet; cuando hay conexión, llama él a Central.

class PosTienda(db.Model):
    """Una tienda cliente del punto de venta."""
    __tablename__ = "pos_tiendas"
    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(60), unique=True, nullable=False)
    nombre = db.Column(db.String(120), nullable=False)
    nif = db.Column(db.String(20))
    contacto_nombre = db.Column(db.String(120))
    contacto_telefono = db.Column(db.String(40))
    contacto_email = db.Column(db.String(160))
    modo = db.Column(db.String(10), default="cuota")       # cuota | unico
    cuota_cents = db.Column(db.Integer, default=0)          # cuota mensual (o precio del pago único)
    pagado_hasta = db.Column(db.Date)                       # cuota: último día pagado
    prueba_hasta = db.Column(db.Date)                       # prueba gratis: último día
    dias_gracia = db.Column(db.Integer, default=7)          # días tras el impago antes de bloquear
    dias_sin_conexion = db.Column(db.Integer, default=15)   # cuota/prueba: días máximo sin hablar con Central
    max_equipos = db.Column(db.Integer, default=1)          # ordenadores con el POS instalado
    estado = db.Column(db.String(12), default="activa")     # prueba | activa | suspendida | baja
    codigo_hash = db.Column(db.String(64), index=True)      # código de activación (solo su huella)
    codigo_pista = db.Column(db.String(4))                  # sus 4 últimos caracteres, para reconocerlo
    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime, default=datetime.utcnow)

    equipos = db.relationship("PosEquipo", backref="tienda", lazy="dynamic", cascade="all, delete-orphan")


class PosEquipo(db.Model):
    """Un ordenador de una tienda con el POS instalado y activado."""
    __tablename__ = "pos_equipos"
    id = db.Column(db.Integer, primary_key=True)
    tienda_id = db.Column(db.Integer, db.ForeignKey("pos_tiendas.id"), nullable=False, index=True)
    machine_id = db.Column(db.String(20), nullable=False, index=True)
    nombre = db.Column(db.String(80))
    token_hash = db.Column(db.String(64), index=True)       # credencial propia del equipo (solo su huella)
    clave_copias = db.Column(db.String(60))                 # cifra sus copias; solo la tienen el equipo y Central
    activo = db.Column(db.Boolean, default=True)
    alta = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_parte = db.Column(db.DateTime)
    version = db.Column(db.String(20))
    ultima_copia = db.Column(db.String(40))
    reloj_atrasado = db.Column(db.Boolean, default=False)
    datos_json = db.Column(db.Text)                         # su último parte (ventas del día, errores...)


class PosPrueba(db.Model):
    """Prueba gratis de 7 días: una por ordenador, apuntada aquí para que no se reinicie borrando nada."""
    __tablename__ = "pos_pruebas"
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.String(20), unique=True, nullable=False)
    negocio = db.Column(db.String(120))
    inicio = db.Column(db.DateTime, default=datetime.utcnow)
    tienda_id = db.Column(db.Integer, db.ForeignKey("pos_tiendas.id"))
