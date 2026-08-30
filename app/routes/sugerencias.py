from collections import Counter
from flask import Blueprint, request, jsonify
from app.models import Reparacion

sugerencias_bp = Blueprint("sugerencias", __name__)

PALABRAS_VACIAS = {"el", "la", "los", "las", "de", "del", "y", "en", "un", "una", "no", "que", "con", "se", "es", "por", "al", "a"}


def _palabras_clave(texto):
    return {p for p in texto.lower().split() if len(p) > 2 and p not in PALABRAS_VACIAS}


@sugerencias_bp.get("/fallos-frecuentes")
def fallos_frecuentes():
    """A partir de una marca/modelo y/o un problema descrito, busca en
    tus reparaciones pasadas (ya entregadas o completadas) las más
    parecidas, y devuelve las causas/soluciones que se repiten más.
    No es IA — es tu propio historial, sin coste ni cuentas externas."""
    marca = (request.args.get("marca") or "").strip().lower()
    modelo = (request.args.get("modelo") or "").strip().lower()
    problema = (request.args.get("problema") or "").strip()

    candidatas = Reparacion.query.filter(
        Reparacion.estado_actual.in_(["entregado", "completado"]),
    ).all()

    palabras_busqueda = _palabras_clave(problema) if problema else set()

    coincidencias = []
    for rep in candidatas:
        puntos = 0
        if marca and rep.marca and rep.marca.lower() == marca:
            puntos += 2
        if modelo and rep.modelo and rep.modelo.lower() == modelo:
            puntos += 2
        if palabras_busqueda and rep.problema_reportado:
            comunes = palabras_busqueda & _palabras_clave(rep.problema_reportado)
            puntos += len(comunes)
        if puntos > 0:
            coincidencias.append((puntos, rep))

    if not coincidencias:
        return jsonify({"encontradas": 0, "sugerencias": []})

    coincidencias.sort(key=lambda x: x[0], reverse=True)
    top = [rep for _, rep in coincidencias[:20]]

    # Agrupa por el texto del problema reportado (lo más parecido a
    # "causa"/"síntoma" que registramos) y cuenta cuál se repite más.
    contador = Counter(rep.problema_reportado.strip() for rep in top if rep.problema_reportado)
    mas_comunes = contador.most_common(3)

    return jsonify({
        "encontradas": len(coincidencias),
        "sugerencias": [{"descripcion": texto, "veces_visto": veces} for texto, veces in mas_comunes],
    })


@sugerencias_bp.get("/estimador")
def estimador_tiempo_coste():
    """Tiempo medio real (de tu propio historial) para una categoría o
    tipo de trabajo, y un precio sugerido = mano de obra estimada +
    coste de piezas que le pases. Todo con tus propios datos."""
    from decimal import Decimal
    from app.models import ConfiguracionNegocio

    categoria = request.args.get("categoria")
    tipo_trabajo = request.args.get("tipo_trabajo", "taller")
    coste_piezas = Decimal(request.args.get("coste_piezas", "0") or "0")

    query = Reparacion.query.filter(
        Reparacion.tipo_trabajo == tipo_trabajo,
        Reparacion.estado_actual.in_(["entregado", "completado"]),
        Reparacion.fecha_entrega.isnot(None),
    )
    if categoria:
        query = query.filter(Reparacion.categoria == categoria)

    reparaciones = query.all()
    if not reparaciones:
        return jsonify({"encontradas": 0, "horas_promedio": None, "precio_sugerido": None})

    horas = [
        (rep.fecha_entrega - rep.fecha_recepcion).total_seconds() / 3600
        for rep in reparaciones if rep.fecha_recepcion
    ]
    horas_promedio = round(sum(horas) / len(horas), 1) if horas else 0

    negocio = ConfiguracionNegocio.obtener()
    tarifa_hora = negocio.tarifa_hora or Decimal("25")
    coste_mano_obra = round(Decimal(str(horas_promedio)) * tarifa_hora, 2)
    precio_sugerido = round(coste_mano_obra + coste_piezas, 2)

    return jsonify({
        "encontradas": len(reparaciones),
        "horas_promedio": horas_promedio,
        "coste_mano_obra_estimado": float(coste_mano_obra),
        "coste_piezas": float(coste_piezas),
        "precio_sugerido": float(precio_sugerido),
    })
