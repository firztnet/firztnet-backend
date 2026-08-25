"""Genera el PDF del comprobante (recepción, entrega o no reparable)
con el estilo de Firztnet, usando reportlab.

Genera SIEMPRE en memoria (BytesIO), sin depender de que exista un
archivo guardado en disco. Esto es importante porque en plataformas
como Railway el sistema de archivos es efímero — un PDF guardado en
disco puede desaparecer si el contenedor se reinicia. Al regenerarlo
al vuelo desde los datos de la reparación, nunca depende de nada
guardado previamente."""
import io
from datetime import datetime
from reportlab.lib.pagesizes import A5
from reportlab.lib.units import mm
from reportlab.lib.colors import HexColor
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
