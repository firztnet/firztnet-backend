"""Genera el PDF del comprobante (recepción, entrega o no reparable)
con el estilo de Firztnet, usando reportlab.

Genera SIEMPRE en memoria (BytesIO), sin depender de que exista un
archivo guardado en disco. Esto es importante porque en plataformas
como Railway el sistema de archivos es efímero — un PDF guardado en
disco puede desaparecer si el contenedor se reinicia. Al regenerarlo
al vuelo desde los datos de la reparación, nunca depende de nada
guardado previamente."""
import io
import os
from datetime import datetime
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
from reportlab.lib.utils import ImageReader
import qrcode
from reportlab.pdfgen import canvas
from app.models import ConfiguracionNegocio

AZUL = HexColor("#2563EB")
GRIS_TEXTO = HexColor("#334155")
GRIS_CLARO = HexColor("#94A3B8")

TITULOS = {
    "recepcion": "Comprobante de recepción",
    "entrega": "Comprobante de entrega",
    "no_reparable": "Diagnóstico: equipo no reparable",
}


def _fecha(dt):
    if not dt:
        return "—"
    return dt.strftime("%d/%m/%Y")


def generar_pdf_comprobante(reparacion, tipo, enlace_seguimiento=None):
    """reparacion es una instancia del modelo Reparacion (con .cliente cargado).
    Devuelve los bytes del PDF (io.BytesIO), listos para servir con send_file
    o adjuntar a un email — no se guarda nada en disco."""
    negocio = ConfiguracionNegocio.obtener()
    buffer = io.BytesIO()

    c = canvas.Canvas(buffer, pagesize=A5)
    ancho, alto = A5
    margen = 14 * mm
    y = alto - margen

    # Cabecera con marca
    c.setFillColor(AZUL)
    c.rect(0, alto - 22 * mm, ancho, 22 * mm, fill=True, stroke=False)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margen, alto - 14 * mm, (negocio.nombre_negocio or "Firztnet").upper())
    c.setFont("Helvetica", 9)
    c.drawString(margen, alto - 19 * mm, negocio.eslogan or "")

    y = alto - 32 * mm

    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margen, y, TITULOS.get(tipo, "Comprobante"))
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    c.setFillColor(AZUL)
    c.drawString(margen, y, f"Nº de orden: {reparacion.numero_orden}")
    y -= 8 * mm

    def linea(etiqueta, valor):
        nonlocal y
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8.5)
        c.drawString(margen, y, etiqueta)
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(margen, y - 4.2 * mm, str(valor))
        y -= 10 * mm

    linea("Cliente", reparacion.cliente.nombre if reparacion.cliente else "—")
    linea("Equipo", reparacion.equipo)
    if reparacion.accesorios_entregados:
        linea("Accesorios entregados", reparacion.accesorios_entregados)
    linea("Problema reportado", reparacion.problema_reportado or "—")
    if reparacion.estado_entrada:
        linea("Estado físico de entrada", reparacion.estado_entrada)

    linea("Fecha de recepción", _fecha(reparacion.fecha_recepcion))

    if tipo == "entrega":
        linea("Fecha de entrega", _fecha(reparacion.fecha_entrega))
        linea("Garantía válida hasta", _fecha(reparacion.fecha_fin_garantia))
    elif tipo == "no_reparable":
        linea("Motivo", reparacion.motivo_no_reparable or "—")

    y -= 4 * mm
    c.setStrokeColor(GRIS_CLARO)
    c.setDash(1, 2)
    c.line(margen, y, ancho - margen, y)
    c.setDash()
    y -= 8 * mm

    if enlace_seguimiento:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 7.5)
        c.drawString(margen, y, "Sigue el estado de tu reparación en:")
        y -= 4.5 * mm
        c.setFillColor(AZUL)
        c.setFont("Helvetica", 8)
        c.drawString(margen, y, enlace_seguimiento)
        y -= 8 * mm

    c.setFillColor(GRIS_CLARO)
    c.setFont("Helvetica", 7)
    condiciones = (
        "Condiciones: el equipo debe recogerse en un plazo de 30 días desde el aviso de "
        "disponibilidad. No nos responsabilizamos de equipos no recogidos pasado ese plazo."
    )
    if tipo == "entrega":
        condiciones = "Garantía de 6 meses desde la fecha de entrega, cubre exclusivamente la reparación realizada."
    c.drawString(margen, 16 * mm, condiciones[:95])

    contacto = " · ".join(filter(None, [negocio.direccion, negocio.telefono, negocio.email]))
    if contacto:
        c.drawString(margen, 10 * mm, contacto[:100])

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def _dibujar_cabecera(c, negocio, ancho, alto, margen, subtitulo=None):
    """Cabecera azul compartida por comprobantes, recibos y facturas."""
    c.setFillColor(AZUL)
    c.rect(0, alto - 22 * mm, ancho, 22 * mm, fill=True, stroke=False)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 16)
    c.drawString(margen, alto - 14 * mm, (negocio.nombre_negocio or "Firztnet").upper())
    c.setFont("Helvetica", 9)
    c.drawString(margen, alto - 19 * mm, subtitulo or negocio.eslogan or "")


def generar_pdf_recibo(reparacion, movimientos_ingreso):
    """Recibo sencillo de los cobros hechos por una reparación — no es
    una factura fiscal, solo justifica el pago (importe, concepto,
    método, fecha). Vale para la mayoría de clientes que no piden
    factura formal."""
    negocio = ConfiguracionNegocio.obtener()
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A5)
    ancho, alto = A5
    margen = 14 * mm
    _dibujar_cabecera(c, negocio, ancho, alto, margen)

    y = alto - 32 * mm
    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margen, y, "Recibo de pago")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(AZUL)
    c.drawString(margen, y, f"Nº de orden: {reparacion.numero_orden}")
    y -= 10 * mm

    c.setFillColor(GRIS_CLARO)
    c.setFont("Helvetica", 8.5)
    c.drawString(margen, y, "Cliente")
    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 9.5)
    c.drawString(margen, y - 4.2 * mm, reparacion.cliente.nombre if reparacion.cliente else "—")
    y -= 14 * mm

    # Cabecera de la tabla de conceptos
    c.setFillColor(GRIS_CLARO)
    c.setFont("Helvetica", 8)
    c.drawString(margen, y, "CONCEPTO")
    c.drawString(margen + 78 * mm, y, "MÉTODO")
    c.drawRightString(ancho - margen, y, "IMPORTE")
    y -= 4 * mm
    c.setStrokeColor(GRIS_CLARO)
    c.line(margen, y, ancho - margen, y)
    y -= 6 * mm

    total = 0
    c.setFont("Helvetica", 9)
    c.setFillColor(GRIS_TEXTO)
    for m in movimientos_ingreso:
        c.drawString(margen, y, (m.concepto or "Reparación")[:40])
        c.drawString(margen + 78 * mm, y, (m.metodo_pago or "—").capitalize())
        c.drawRightString(ancho - margen, y, f"{float(m.monto):,.2f} €")
        total += float(m.monto)
        y -= 6 * mm

    y -= 2 * mm
    c.setStrokeColor(GRIS_CLARO)
    c.line(margen, y, ancho - margen, y)
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 12)
    c.setFillColor(AZUL)
    c.drawString(margen, y, "TOTAL COBRADO")
    c.drawRightString(ancho - margen, y, f"{total:,.2f} €")

    contacto = " · ".join(filter(None, [negocio.direccion, negocio.telefono, negocio.email]))
    if contacto:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 7)
        c.drawString(margen, 10 * mm, contacto[:100])

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def generar_pdf_factura(factura, reparacion, cliente, negocio):
    """Factura fiscal formal: nº correlativo, NIF de ambas partes,
    base imponible, IVA desglosado y total. Si es una rectificativa,
    lo indica claramente y referencia la factura original."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A5)
    ancho, alto = A5
    margen = 14 * mm
    _dibujar_cabecera(c, negocio, ancho, alto, margen, subtitulo=f"NIF: {negocio.nif or '—'}")

    y = alto - 32 * mm
    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(margen, y, "FACTURA RECTIFICATIVA" if factura.es_rectificativa else "FACTURA")
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(HexColor("#DC2626") if factura.es_rectificativa else AZUL)
    c.drawRightString(ancho - margen, y, factura.numero)
    y -= 7 * mm

    if factura.es_rectificativa:
        c.setFillColor(HexColor("#DC2626"))
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(margen, y, f"Rectifica a la factura {factura.factura_original.numero}")
        y -= 4.5 * mm
        c.setFont("Helvetica", 7.5)
        c.setFillColor(GRIS_CLARO)
        for linea in _partir_texto(f"Motivo: {factura.motivo_rectificacion}", 65):
            c.drawString(margen, y, linea)
            y -= 3.8 * mm
        y -= 2 * mm

    c.setFont("Helvetica", 8.5)
    c.setFillColor(GRIS_CLARO)
    c.drawString(margen, y, f"Fecha de emisión: {_fecha(factura.fecha_emision)}")
    c.drawRightString(ancho - margen, y, f"Nº de orden: {reparacion.numero_orden}")
    y -= 10 * mm

    # Datos del cliente
    c.setFillColor(GRIS_CLARO)
    c.setFont("Helvetica", 8)
    c.drawString(margen, y, "FACTURAR A")
    y -= 5 * mm
    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 10)
    # Prioridad a los datos "congelados" en el momento de emitir la
    # factura — así, si el cliente pide luego borrar sus datos (RGPD),
    # esta factura sigue mostrando lo correcto. Si es una factura
    # antigua sin ese campo (de antes de este cambio), se usa el dato
    # en vivo del cliente como respaldo.
    nombre_mostrado = factura.cliente_nombre_congelado or cliente.nombre
    nif_mostrado = factura.cliente_nif_congelado or cliente.nif
    c.drawString(margen, y, nombre_mostrado)
    y -= 5 * mm
    c.setFont("Helvetica", 9)
    c.drawString(margen, y, f"NIF: {nif_mostrado or '—'}")
    y -= 12 * mm

    # Tabla de conceptos (una sola línea: la reparación completa)
    c.setFillColor(GRIS_CLARO)
    c.setFont("Helvetica", 8)
    c.drawString(margen, y, "CONCEPTO")
    c.drawRightString(ancho - margen, y, "IMPORTE")
    y -= 4 * mm
    c.setStrokeColor(GRIS_CLARO)
    c.line(margen, y, ancho - margen, y)
    y -= 7 * mm

    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica", 9.5)
    c.drawString(margen, y, (factura.concepto or f"Reparación de {reparacion.equipo}")[:55])
    c.drawRightString(ancho - margen, y, f"{float(factura.base_imponible):,.2f} €")
    y -= 10 * mm

    c.setStrokeColor(GRIS_CLARO)
    c.line(margen, y, ancho - margen, y)
    y -= 8 * mm

    def total_linea(etiqueta, valor, negrita=False):
        nonlocal y
        c.setFont("Helvetica-Bold" if negrita else "Helvetica", 10 if negrita else 9)
        c.setFillColor(AZUL if negrita else GRIS_TEXTO)
        c.drawString(margen, y, etiqueta)
        c.drawRightString(ancho - margen, y, valor)
        y -= 6.5 * mm

    total_linea("Base imponible", f"{float(factura.base_imponible):,.2f} €")
    total_linea(f"IVA ({float(factura.iva_pct):.0f}%)", f"{float(factura.iva_importe):,.2f} €")
    y -= 1.5 * mm
    total_linea("TOTAL", f"{float(factura.total):,.2f} €", negrita=True)

    contacto = " · ".join(filter(None, [negocio.direccion, negocio.telefono, negocio.email]))
    if contacto:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 7)
        c.drawString(margen, 10 * mm, contacto[:100])

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def generar_pdf_presupuesto(reparacion, negocio, firma_ruta=None):
    """Presupuesto formal de la reparación, con espacio para firma de
    aceptación. Si ya está firmado (firma_ruta), la incrusta."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A5)
    ancho, alto = A5
    margen = 14 * mm
    _dibujar_cabecera(c, negocio, ancho, alto, margen)

    y = alto - 32 * mm
    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margen, y, "Presupuesto")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(AZUL)
    c.drawString(margen, y, f"Nº de orden: {reparacion.numero_orden}")
    y -= 10 * mm

    def linea(etiqueta, valor):
        nonlocal y
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8.5)
        c.drawString(margen, y, etiqueta)
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(margen, y - 4.2 * mm, str(valor)[:60])
        y -= 11 * mm

    linea("Cliente", reparacion.cliente.nombre if reparacion.cliente else "—")
    linea("Equipo", reparacion.equipo)
    linea("Descripción", reparacion.presupuesto_descripcion or f"Reparación de {reparacion.equipo}")

    y -= 3 * mm
    c.setStrokeColor(GRIS_CLARO)
    c.line(margen, y, ancho - margen, y)
    y -= 10 * mm

    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(AZUL)
    c.drawString(margen, y, "IMPORTE PRESUPUESTADO")
    c.drawRightString(ancho - margen, y, f"{float(reparacion.presupuesto_importe or 0):,.2f} €")
    y -= 12 * mm

    c.setFillColor(GRIS_CLARO)
    c.setFont("Helvetica", 7.5)
    c.drawString(margen, y, "Presupuesto orientativo. El importe final puede variar si aparecen")
    y -= 3.8 * mm
    c.drawString(margen, y, "incidencias adicionales durante la reparación, que se te comunicarán antes.")
    y -= 14 * mm

    if firma_ruta and os.path.exists(firma_ruta):
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8)
        c.drawString(margen, y, "Firmado y aceptado por el cliente:")
        y -= 26 * mm
        try:
            c.drawImage(firma_ruta, margen, y, width=60 * mm, height=22 * mm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    else:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8)
        c.drawString(margen, y, "Pendiente de aceptación por el cliente.")

    contacto = " · ".join(filter(None, [negocio.direccion, negocio.telefono, negocio.email]))
    if contacto:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 7)
        c.drawString(margen, 10 * mm, contacto[:100])

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def generar_pdf_parte_trabajo(reparacion, negocio, repuestos_usados, checklist, firma_ruta=None, coste_mano_obra=None, minutos_trabajados=None):
    """Parte de trabajo de un servicio a domicilio: qué se hizo, qué
    material se usó, cuánto tiempo llevó, y la firma de conformidad del
    cliente — para dejárselo en el momento por WhatsApp."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A5)
    ancho, alto = A5
    margen = 14 * mm
    _dibujar_cabecera(c, negocio, ancho, alto, margen)

    y = alto - 32 * mm
    c.setFillColor(GRIS_TEXTO)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(margen, y, "Parte de trabajo")
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.setFillColor(AZUL)
    c.drawString(margen, y, f"Nº de orden: {reparacion.numero_orden}")
    y -= 9 * mm

    def linea(etiqueta, valor):
        nonlocal y
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8.5)
        c.drawString(margen, y, etiqueta)
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica-Bold", 9.5)
        c.drawString(margen, y - 4.2 * mm, str(valor)[:65])
        y -= 10 * mm

    linea("Cliente", reparacion.cliente.nombre if reparacion.cliente else "—")
    if reparacion.direccion_servicio:
        linea("Dirección", reparacion.direccion_servicio)
    linea("Servicio realizado", reparacion.equipo)
    if reparacion.problema_reportado:
        linea("Descripción del aviso", reparacion.problema_reportado)

    # Checklist completado
    completados = [i for i in checklist if i.get("completado")]
    if completados:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8.5)
        c.drawString(margen, y, "Tareas realizadas")
        y -= 5 * mm
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica", 9)
        for item in completados[:8]:
            c.drawString(margen, y, f"✓ {item['texto'][:55]}")
            y -= 5 * mm
        y -= 3 * mm

    # Material usado
    if repuestos_usados:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8.5)
        c.drawString(margen, y, "Material usado")
        y -= 5 * mm
        c.setFillColor(GRIS_TEXTO)
        c.setFont("Helvetica", 9)
        for uso in repuestos_usados[:6]:
            nombre = uso["repuesto"]["nombre"] if uso.get("repuesto") else "—"
            c.drawString(margen, y, f"{uso['cantidad']}× {nombre[:45]}")
            y -= 5 * mm
        y -= 3 * mm

    if minutos_trabajados is not None:
        horas = minutos_trabajados / 60
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8.5)
        c.drawString(margen, y, f"Tiempo en el servicio: {horas:.1f} h")
        y -= 5 * mm
        if coste_mano_obra is not None:
            c.drawString(margen, y, f"Mano de obra: {coste_mano_obra:,.2f} €")
            y -= 5 * mm
        y -= 3 * mm

    y -= 4 * mm
    if firma_ruta and os.path.exists(firma_ruta):
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8)
        c.drawString(margen, y, "Firmado y aceptado por el cliente:")
        y -= 26 * mm
        try:
            c.drawImage(firma_ruta, margen, y, width=60 * mm, height=22 * mm, preserveAspectRatio=True, mask="auto")
        except Exception:
            pass
    else:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 8)
        c.drawString(margen, y, "Pendiente de firma de conformidad.")

    contacto = " · ".join(filter(None, [negocio.direccion, negocio.telefono, negocio.email]))
    if contacto:
        c.setFillColor(GRIS_CLARO)
        c.setFont("Helvetica", 7)
        c.drawString(margen, 10 * mm, contacto[:100])

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def generar_pdf_etiqueta_qr(reparacion, negocio, frontend_url):
    """Etiqueta pequeña con un QR que lleva directo a la página pública
    de seguimiento de esta reparación en concreto — para imprimir y
    pegar en el equipo al recibirlo. El cliente, al escanearlo, ve el
    estado en tiempo real, la garantía, el WiFi (si aplica) y puede
    pedir un nuevo servicio."""
    enlace = f"{frontend_url}/seguimiento?token={reparacion.token_seguimiento}"

    qr = qrcode.QRCode(box_size=10, border=2)
    qr.add_data(enlace)
    qr.make(fit=True)
    imagen_qr = qr.make_image(fill_color="#0F172A", back_color="white")
    buffer_qr = io.BytesIO()
    imagen_qr.save(buffer_qr, format="PNG")
    buffer_qr.seek(0)

    # Tamaño de etiqueta pequeña (aprox. una etiqueta de envío), no A5 completo.
    ancho, alto = 80 * mm, 50 * mm
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(ancho, alto))

    margen = 4 * mm
    c.setFillColor(HexColor("#2563EB"))
    c.rect(0, alto - 9 * mm, ancho, 9 * mm, fill=1, stroke=0)
    c.setFillColor(HexColor("#FFFFFF"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margen, alto - 6.5 * mm, negocio.nombre_negocio or "FIRZTNET")

    tam_qr = 32 * mm
    c.drawImage(ImageReader(buffer_qr), margen, alto - 9 * mm - tam_qr - 3 * mm, width=tam_qr, height=tam_qr)

    x_texto = margen + tam_qr + 4 * mm
    y = alto - 15 * mm
    c.setFillColor(HexColor("#0F172A"))
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_texto, y, reparacion.numero_orden)
    y -= 5 * mm
    c.setFont("Helvetica", 7.5)
    c.setFillColor(HexColor("#475569"))
    for linea in _partir_texto(reparacion.equipo, 20):
        c.drawString(x_texto, y, linea)
        y -= 3.6 * mm
    y -= 2 * mm
    c.setFont("Helvetica-Oblique", 6.5)
    c.setFillColor(HexColor("#64748B"))
    c.drawString(x_texto, y, "Escanea para ver")
    y -= 3 * mm
    c.drawString(x_texto, y, "el estado y la garantía")

    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer


def _partir_texto(texto, max_caracteres):
    """Reparte un texto largo en varias líneas cortas, sin cortar palabras."""
    palabras = (texto or "").split()
    lineas, actual = [], ""
    for palabra in palabras:
        prueba = f"{actual} {palabra}".strip()
        if len(prueba) > max_caracteres and actual:
            lineas.append(actual)
            actual = palabra
        else:
            actual = prueba
    if actual:
        lineas.append(actual)
    return lineas[:2]  # como mucho 2 líneas, para que quepa en la etiqueta
