from flask import Blueprint, jsonify, send_file
from app.models import Reparacion, ConfiguracionNegocio, Firma, ChecklistItem, SesionTrabajo
from app.pdf_generator import generar_pdf_parte_trabajo
from app.firmas import ruta_completa
from app.routes.sesiones import _minutos_trabajados

parte_trabajo_bp = Blueprint("parte_trabajo", __name__)


@parte_trabajo_bp.get("/reparaciones/<int:rep_id>/parte-trabajo/pdf")
def descargar_parte_trabajo(rep_id):
    reparacion = Reparacion.query.get_or_404(rep_id)
    negocio = ConfiguracionNegocio.obtener()

    repuestos_usados = [rr.to_dict() for rr in reparacion.repuestos_usados]
    checklist = [c.to_dict() for c in ChecklistItem.query.filter_by(reparacion_id=rep_id).order_by(ChecklistItem.orden).all()]

    firma = Firma.query.filter_by(reparacion_id=rep_id, tipo="entrega").order_by(Firma.id.desc()).first()
    firma_ruta = ruta_completa(firma.nombre_archivo) if firma else None

    sesiones = SesionTrabajo.query.filter_by(reparacion_id=rep_id).all()
    minutos = _minutos_trabajados(sesiones) if sesiones else None
    coste_mano_obra = round((minutos / 60) * float(negocio.tarifa_hora or 25), 2) if minutos else None

    buffer = generar_pdf_parte_trabajo(
        reparacion, negocio, repuestos_usados, checklist,
        firma_ruta=firma_ruta, coste_mano_obra=coste_mano_obra, minutos_trabajados=minutos,
    )
    return send_file(buffer, mimetype="application/pdf", download_name=f"parte_trabajo_{reparacion.numero_orden}.pdf")
