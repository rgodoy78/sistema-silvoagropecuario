"""Geometría de gráficos SVG calculada en el servidor.

Los gráficos se dibujan con SVG y atributos de presentación (sin estilos ni
scripts inline), así respetan la CSP estricta y no necesitan JavaScript.
Las plantillas están en templates/core/charts/.
"""

import math

# Cantidad de colores de serie definidos en app.css (.series-1 ... .series-6).
SERIES_COLORS = 6


def fmt(value):
    """Número con separador de miles chileno: 12345 -> '12.345'."""
    if isinstance(value, float) and not value.is_integer():
        return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{int(value):,}".replace(",", ".")


def _nice_max(value, ticks=4, integer=False):
    """Máximo del eje redondeado a un paso 'lindo' (1, 2, 2.5 o 5 × 10^n).

    Con integer=True el paso es entero (para conteos: nada de "0,5 usuarios").
    """
    if value <= 0:
        return ticks
    raw_step = value / ticks
    if integer and raw_step <= 1:
        return ticks
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * magnitude
        if integer and step != int(step):
            continue
        if step >= raw_step:
            break
    return step * ticks


def _grid(max_value, top, bottom, ticks=4):
    lines = []
    for i in range(ticks + 1):
        value = max_value * i / ticks
        y = bottom - (bottom - top) * i / ticks
        lines.append({"y": round(y, 1), "label": fmt(value)})
    return lines


def bar_chart(labels, values, width=520, height=240, integer=False):
    """Barras verticales de una serie."""
    left, right, top, bottom = 44, width - 8, 16, height - 30
    max_value = _nice_max(max(values, default=0), integer=integer)
    slot = (right - left) / max(len(values), 1)
    bar_w = min(slot * 0.6, 48)
    bars = []
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        h = (bottom - top) * value / max_value
        x = left + slot * i + (slot - bar_w) / 2
        bars.append({
            "x": round(x, 1), "y": round(bottom - h, 1), "w": round(bar_w, 1), "h": round(h, 1),
            "cx": round(x + bar_w / 2, 1), "label": label, "value": fmt(value),
        })
    return {
        "width": width, "height": height, "left": left, "right": right, "bottom": bottom,
        "grid": _grid(max_value, top, bottom), "bars": bars,
    }


def line_chart(labels, series, width=520, height=240):
    """Líneas de varias series: series = [(nombre, [valores...]), ...]."""
    left, right, top, bottom = 44, width - 12, 16, height - 30
    max_value = _nice_max(max((v for _, values in series for v in values), default=0))
    step = (right - left) / max(len(labels) - 1, 1)
    xs = [round(left + step * i, 1) for i in range(len(labels))]
    lines = []
    for n, (name, values) in enumerate(series):
        points = [(x, round(bottom - (bottom - top) * v / max_value, 1)) for x, v in zip(xs, values, strict=True)]
        path = " ".join(f"{x},{y}" for x, y in points)
        lines.append({
            "name": name, "color": n % SERIES_COLORS + 1, "points": path,
            "area": f"{xs[0]},{bottom} {path} {xs[-1]},{bottom}",
            "dots": [{"x": x, "y": y, "value": fmt(v)} for (x, y), v in zip(points, values, strict=True)],
        })
    return {
        "width": width, "height": height, "left": left, "right": right, "bottom": bottom,
        "grid": _grid(max_value, top, bottom),
        "labels": [{"x": x, "label": label} for x, label in zip(xs, labels, strict=True)],
        "lines": lines,
    }


def donut_chart(items):
    """Anillo de proporciones: items = [(etiqueta, valor), ...].

    Usa un círculo de circunferencia 100 para que cada segmento sea su
    porcentaje en stroke-dasharray.
    """
    total = sum(value for _, value in items)
    segments = []
    offset = 25.0  # Empieza arriba (las 12 en punto).
    for n, (label, value) in enumerate(items):
        pct = 100 * value / total if total else 0
        segments.append({
            "label": label, "value": fmt(value), "pct": round(pct), "color": n % SERIES_COLORS + 1,
            "dash": f"{pct:.2f} {100 - pct:.2f}", "offset": f"{offset:.2f}",
        })
        offset -= pct
    return {"total": fmt(total), "segments": segments}
