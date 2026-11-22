import math
import os

from fastapi import HTTPException


def gps_limits() -> dict[str, float]:
    limits = {
        "excelente": float(os.environ.get("GPS_LIMITE_EXCELENTE", "5")),
        "buena": float(os.environ.get("GPS_LIMITE_BUENA", "10")),
        "aceptable": float(os.environ.get("GPS_LIMITE_ACEPTABLE", "20")),
        "baja": float(os.environ.get("GPS_LIMITE_BAJA", "50")),
    }
    values = list(limits.values())
    if not all(math.isfinite(value) and value > 0 for value in values) or values != sorted(set(values)):
        raise RuntimeError("Los límites GPS deben ser positivos y estrictamente crecientes")
    return limits


def validate_gps_measurement(precision: float | None, captured_at: object | None) -> None:
    if precision is None or captured_at is None:
        raise HTTPException(status_code=422, detail="La captura GPS requiere precisión y fecha de medición")
    if precision > gps_limits()["aceptable"]:
        raise HTTPException(status_code=422, detail="La precisión GPS es insuficiente; repite la captura")
