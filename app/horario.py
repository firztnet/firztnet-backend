"""Fechas en hora de Madrid.

El servidor guarda todas las fechas en hora universal (UTC), que en verano va
2 horas por detrás de Madrid y en invierno 1. Para saber qué es "hoy" o
"este mes" hay que mirarlo en hora de Madrid; si no, lo que pasa entre
medianoche y la 1-2 de la madrugada se apunta al día anterior."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")


def ahora_madrid():
    return datetime.now(MADRID)


def hoy_madrid():
    """La fecha de hoy en Madrid."""
    return ahora_madrid().date()


def a_utc(fecha_madrid):
    """Convierte una fecha-hora de Madrid (sin zona) a la hora UTC (sin zona)
    con la que se guardan las fechas en la base de datos."""
    return fecha_madrid.replace(tzinfo=MADRID).astimezone(timezone.utc).replace(tzinfo=None)


def a_madrid(fecha_utc):
    """Lo contrario: una fecha guardada (UTC, sin zona) pasada a hora de Madrid."""
    return fecha_utc.replace(tzinfo=timezone.utc).astimezone(MADRID).replace(tzinfo=None)


def limites_dia_utc(dia):
    """Inicio y fin (en UTC) del día `dia` de Madrid, para filtrar en la base de datos."""
    inicio = datetime.combine(dia, datetime.min.time())
    return a_utc(inicio), a_utc(inicio + timedelta(days=1))


def inicio_mes_utc(anio, mes):
    return a_utc(datetime(anio, mes, 1))
