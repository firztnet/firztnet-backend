from datetime import datetime, timedelta
from app import db

GARANTIA_MESES = 6


class Cliente(db.Model):
    __tablename__ = "clientes"
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(120), nullable=False)
    telefono = db.Column(db.String(30))
    email = db.Column(db.String(120))
    creado_en = db.Column(db.DateTime, default=datetime.utcnow)

    reparaciones = db.relationship("Reparacion", backref="cliente", lazy=True)

    def to_dict(self):
        return {
            "id": self.id,
            "nombre": self.nombre,
            "telefono": self.telefono,
            "email": self.email,
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
    accesorios_entregados = db.Column(db.String(255))
    problema_reportado = db.Column(db.Text)
    estado_entrada = db.Column(db.Text)  # rayones, golpes, etc. al recibir

    estado_actual = db.Column(db.String(30), db.ForeignKey("estados.codigo"), default="recibido")
    motivo_no_reparable = db.Column(db.Text)

    fecha_recepcion = db.Column(db.DateTime, default=datetime.utcnow)
    fecha_estimada = db.Column(db.DateTime)
    fecha_entrega = db.Column(db.DateTime)
    fecha_fin_garantia = db.Column(db.DateTime)

    repuestos_usados = db.relationship("ReparacionRepuesto", backref="reparacion", lazy=True)
    movimientos = db.relationship("MovimientoFinanciero", backref="reparacion", lazy=True)
    comprobantes = db.relationship("Comprobante", backref="reparacion", lazy=True)

    def marcar_entregada(self):
        self.estado_actual = "entregado"
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
            "accesorios_entregados": self.accesorios_entregados,
            "problema_reportado": self.problema_reportado,
            "estado_entrada": self.estado_entrada,
            "estado_actual": self.estado_actual,
            "motivo_no_reparable": self.motivo_no_reparable,
            "fecha_recepcion": self.fecha_recepcion.isoformat() if self.fecha_recepcion else None,
            "fecha_estimada": self.fecha_estimada.isoformat() if self.fecha_estimada else None,
            "fecha_entrega": self.fecha_entrega.isoformat() if self.fecha_entrega else None,
            "fecha_fin_garantia": self.fecha_fin_garantia.isoformat() if self.fecha_fin_garantia else None,
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


class Comprobante(db.Model):
    __tablename__ = "comprobantes"
    id = db.Column(db.Integer, primary_key=True)
    reparacion_id = db.Column(db.Integer, db.ForeignKey("reparaciones.id"), nullable=False)
    tipo = db.Column(db.String(20), nullable=False)  # recepcion, entrega, no_reparable
    enlace_seguimiento = db.Column(db.String(255))
    fecha_generado = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "reparacion_id": self.reparacion_id,
            "tipo": self.tipo,
            "enlace_seguimiento": self.enlace_seguimiento,
            "fecha_generado": self.fecha_generado.isoformat() if self.fecha_generado else None,
        }
