from datetime import datetime, timedelta
import secrets
from app import db

GARANTIA_MESES = 6


class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    codigo = db.Column(db.String(20), unique=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30))
    email = db.Column(db.String(120))
    nif = db.Column(db.String(20))  # solo hace falta si pide factura
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    reparaciones = db.relationship("Reparacion", backref="cliente", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "codigo": self.codigo,
            "nombre": self.nombre,
            "telefono": self.telefono,
            "email": self.email,
            "nif": self.nif,
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

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "categoria": self.categoria,
            "proveedor_id": self.proveedor_id,
            "stock_actual": self.stock_actual,
            "stock_minimo": self.stock_minimo,
            "stock_bajo": self.stock_actual <= self.stock_minimo,
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
    marca = db.Column(db.String(60))
    modelo = db.Column(db.String(60))
    urgente = db.Column(db.Boolean, default=False)
    accesorios_entregados = db.Column(db.String(255))
    problema_reportado = db.Column(db.Text)
    estado_entrada = db.Column(db.Text)  # rayones, golpes, etc. al recibir

    estado_actual = db.Column(db.String(30), db.ForeignKey("estados.codigo"), default="recibido")
    motivo_no_reparable = db.Column(db.Text)

    fecha_recepcion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_estimada = db.Column(db.DateTime)
    fecha_entrega = db.Column(db.DateTime)
    fecha_fin_garantia = db.Column(db.DateTime)

    # Identificador aleatorio (no adivinable, a diferencia del nº de orden
    # que es correlativo) para la página pública de seguimiento del cliente.
    token_seguimiento = db.Column(db.String(40), unique=True, default=lambda: secrets.token_hex(8))

    # Presupuesto: uno activo por reparación. estado: pendiente / aceptado / rechazado
    presupuesto_importe = db.Column(db.Numeric(10, 2))
    presupuesto_descripcion = db.Column(db.Text)
    presupuesto_estado = db.Column(db.String(20))
    presupuesto_fecha = db.Column(db.DateTime)

    repuestos_usados = db.relationship("ReparacionRepuesto", backref="reparacion", lazy=True)
    movimientos = db.relationship("MovimientoFinanciero", backref="reparacion", lazy=True)
    comprobantes = db.relationship("Comprobante", backref="reparacion", lazy=True)

    def marcar_entregada(self):
        self.estado_actual = "entregado"
        self.fecha_entrega = datetime.utcnow()
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
            "marca": self.marca,
            "modelo": self.modelo,
            "urgente": bool(self.urgente),
            "accesorios_entregados": self.accesorios_entregados,
            "problema_reportado": self.problema_reportado,
            "estado_entrada": self.estado_entrada,
            "estado_actual": self.estado_actual,
            "motivo_no_reparable": self.motivo_no_reparable,
            "fecha_recepcion": self.fecha_recepcion.isoformat() if self.fecha_recepcion else None,
            "fecha_estimada": self.fecha_estimada.isoformat() if self.fecha_estimada else None,
            "fecha_entrega": self.fecha_entrega.isoformat() if self.fecha_entrega else None,
            "fecha_fin_garantia": self.fecha_fin_garantia.isoformat() if self.fecha_fin_garantia else None,
            "token_seguimiento": self.token_seguimiento,
            "presupuesto_importe": float(self.presupuesto_importe) if self.presupuesto_importe is not None else None,
            "presupuesto_descripcion": self.presupuesto_descripcion,
            "presupuesto_estado": self.presupuesto_estado,
            "presupuesto_fecha": self.presupuesto_fecha.isoformat() if self.presupuesto_fecha else None,
        }


class ReparacionRepuesto(db.Model):
    """Tabla puente: qué repuestos (y cuántos) se usaron en cada reparación."""
    __tablename__ = "reparacion_repuestos"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    repuesto_id = db.Column(db.Integer, db.ForeignKey("repuestos.id"), nullable=False)
    cantidad = db.Column(db.Integer, default=1)
    precio_aplicado = db.Column(db.Numeric(10, 2), default=0)

    repuesto = db.relationship("Repuesto")

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "repuesto": self.repuesto.to_dict() if self.repuesto else None,
            "cantidad": self.cantidad,
            "precio_aplicado": float(self.precio_aplicado or 0),
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

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "tipo": self.tipo,
            "concepto": self.concepto,
            "monto": float(self.monto or 0),
            "metodo_pago": self.metodo_pago,
            "fecha": self.fecha.isoformat() if self.fecha else None,
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
        }

    @staticmethod
    def obtener():
        config = ConfiguracionNegocio.query.get(1)
        if not config:
            config = ConfiguracionNegocio(id=1)
            db.session.add(config)
            db.session.commit()
        return config


class Factura(db.Model):
    """Factura fiscal formal, con numeración correlativa (obligatoria por
    ley: sin huecos, en orden cronológico). Una vez emitida no se borra
    ni se renumera — si hay un error, se anula con una rectificativa
    (no implementado todavía, de momento evita borrar facturas)."""
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

    reparacion = db.relationship("Reparacion")
    cliente = db.relationship("Cliente")

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
            "fecha_emision": self.fecha_emision.isoformat() if self.fecha_emision else None,
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
    fecha = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "tipo": self.tipo,
            "nombre_firmante": self.nombre_firmante,
            "nombre_archivo": self.nombre_archivo,
            "fecha": self.fecha.isoformat() if self.fecha else None,
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
            "fecha_subida": self.fecha_subida.isoformat() if self.fecha_subida else None,
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
            "fecha_generado": self.fecha_generado.isoformat() if self.fecha_generado else None,
        }
