"""Geometría de gráficos SVG calculada en el servidor.

Los gráficos se dibujan con SVG y atributos de presentación (sin estilos ni
scripts inline), así respetan la CSP estricta y no necesitan JavaScript.
Las plantillas están en templates/core/charts/.

Estilo ejecutivo: marcas finas, grilla tenue, etiquetas solo donde aportan,
un color por serie en orden fijo (.series-1 ... .series-4 en app.css, paleta
validada para daltonismo) y una tabla con los datos bajo cada gráfico.
"""

import math

SERIES_COLORS = 4
BAR = 18  # Grosor de barras y columnas (px de viewBox, máximo 24).
END_RADIUS = 4  # Extremo redondeado de la barra; la base queda recta.


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


def _column_path(x, bottom, w, h):
    """Columna con el extremo superior redondeado y la base recta."""
    r = min(END_RADIUS, h, w / 2)
    if h <= 0:
        return ""
    top = bottom - h
    return (
        f"M{x:.1f},{bottom:.1f} V{top + r:.1f} Q{x:.1f},{top:.1f} {x + r:.1f},{top:.1f} "
        f"H{x + w - r:.1f} Q{x + w:.1f},{top:.1f} {x + w:.1f},{top + r:.1f} V{bottom:.1f} Z"
    )


def column_chart(labels, values, width=680, height=230, integer=False):
    """Columnas verticales de una serie. Etiqueta solo el máximo y el último valor."""
    left, right, top, bottom = 40, width - 8, 20, height - 26
    max_value = _nice_max(max(values, default=0), integer=integer)
    slot = (right - left) / max(len(values), 1)
    peak = max(values, default=0)
    columns = []
    for i, (label, value) in enumerate(zip(labels, values, strict=True)):
        h = (bottom - top) * value / max_value
        x = left + slot * i + (slot - BAR) / 2
        columns.append({
            "path": _column_path(x, bottom, BAR, h), "cx": round(x + BAR / 2, 1), "y": round(bottom - h, 1),
            "hit_x": round(left + slot * i, 1), "hit_w": round(slot, 1),
            "label": label, "value": fmt(value),
            "show_value": value > 0 and (value == peak or i == len(values) - 1),
        })
    return {
        "width": width, "height": height, "left": left, "right": right, "top": top, "bottom": bottom,
        "grid": _grid(max_value, top, bottom), "columns": columns,
        "rows": [(label, fmt(value)) for label, value in zip(labels, values, strict=True)],
    }


def hbar_chart(labels, values):
    """Barras horizontales ordenadas de mayor a menor, valor al final de la fila.

    Cada fila es HTML con una barra SVG de ancho relativo (0-100), así se
    adapta a cualquier pantalla sin achicar el texto.
    """
    pairs = sorted(zip(labels, values, strict=True), key=lambda p: p[1], reverse=True)
    max_value = max((v for _, v in pairs), default=0) or 1
    return {
        "bars": [
            {"label": label, "value": fmt(value), "pct": round(100 * value / max_value, 1)} for label, value in pairs
        ],
    }


def line_chart(labels, series, width=680, height=260):
    """Líneas de varias series en la misma unidad: series = [(nombre, [valores...]), ...].

    Sin marcadores por punto: solo un punto al final de cada línea. Cada mes
    tiene una zona invisible con el detalle en su tooltip.
    """
    left, right, top, bottom = 44, width - 16, 16, height - 26
    max_value = _nice_max(max((v for _, values in series for v in values), default=0))
    step = (right - left) / max(len(labels) - 1, 1)
    xs = [round(left + step * i, 1) for i in range(len(labels))]
    lines = []
    for n, (name, values) in enumerate(series):
        points = [(x, round(bottom - (bottom - top) * v / max_value, 1)) for x, v in zip(xs, values, strict=True)]
        lines.append({
            "name": name, "color": n % SERIES_COLORS + 1,
            "points": " ".join(f"{x},{y}" for x, y in points),
            "end_x": points[-1][0], "end_y": points[-1][1],
        })
    hits = []
    for i, (x, label) in enumerate(zip(xs, labels, strict=True)):
        detail = " · ".join(f"{name}: {fmt(values[i])}" for name, values in series)
        hits.append({"x": round(x - step / 2, 1), "w": round(step, 1), "cx": x, "title": f"{label} — {detail}"})
    return {
        "width": width, "height": height, "left": left, "right": right, "top": top, "bottom": bottom,
        "grid": _grid(max_value, top, bottom),
        "labels": [{"x": x, "label": label} for x, label in zip(xs, labels, strict=True)],
        "lines": lines, "hits": hits,
        "head": [name for name, _ in series],
        "rows": [(label, [fmt(values[i]) for _, values in series]) for i, label in enumerate(labels)],
    }


def stacked_bar(items, width=520, height=14, gap=2):
    """Barra 100 % apilada (parte del todo) con 2 px de separación entre tramos."""
    total = sum(value for _, value in items)
    usable = width - gap * max(len(items) - 1, 0)
    x = 0.0
    segments = []
    for n, (label, value) in enumerate(items):
        w = usable * value / total if total else 0
        segments.append({
            "label": label, "value": fmt(value), "pct": round(100 * value / total) if total else 0,
            "color": n % SERIES_COLORS + 1, "x": round(x, 1), "w": round(w, 1),
        })
        x += w + gap
    return {"width": width, "height": height, "total": fmt(total), "segments": segments}


def sparkline(values, width=120, height=32):
    """Tendencia mínima para un indicador: línea gris y último punto destacado."""
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1
    step = width / max(len(values) - 1, 1)
    pts = [(round(i * step, 1), round(height - 3 - (height - 6) * (v - lo) / span, 1)) for i, v in enumerate(values)]
    return {"width": width, "height": height, "points": " ".join(f"{x},{y}" for x, y in pts),
            "end_x": pts[-1][0], "end_y": pts[-1][1]}
