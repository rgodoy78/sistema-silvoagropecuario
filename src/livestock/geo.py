"""Geometría de predios y potreros: polígonos GeoJSON (lon, lat en WGS84).

Sin PostGIS: los límites se guardan como GeoJSON en un JSONField y la
superficie se calcula con la fórmula de área esférica (la misma de Turf.js y
OpenLayers), suficientemente precisa para predios agrícolas.
"""

import io
import math
import zipfile

from defusedxml import ElementTree

EARTH_RADIUS_M = 6378137.0
MAX_VERTICES = 5000


class GeometryError(ValueError):
    pass


def _ring_area_m2(ring):
    area = 0.0
    for (lon1, lat1), (lon2, lat2) in zip(ring, ring[1:], strict=False):
        area += math.radians(lon2 - lon1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(area * EARTH_RADIUS_M**2 / 2)


def area_ha(polygon):
    """Superficie en hectáreas de un Polygon GeoJSON (anillo exterior menos los huecos)."""
    rings = polygon["coordinates"]
    m2 = _ring_area_m2(rings[0]) - sum(_ring_area_m2(r) for r in rings[1:])
    return round(m2 / 10_000, 2)


def clean_polygon(data):
    """Valida y normaliza un Polygon GeoJSON. Acepta también Feature con geometría Polygon."""
    if isinstance(data, dict) and data.get("type") == "Feature":
        data = data.get("geometry")
    if not isinstance(data, dict) or data.get("type") != "Polygon":
        raise GeometryError("La geometría debe ser un polígono.")
    rings = data.get("coordinates")
    if not isinstance(rings, list) or not rings:
        raise GeometryError("El polígono no tiene coordenadas.")
    clean_rings, total = [], 0
    for ring in rings:
        if not isinstance(ring, list):
            raise GeometryError("Coordenadas no válidas.")
        points = []
        for point in ring:
            try:
                lon, lat = float(point[0]), float(point[1])
            except (TypeError, ValueError, IndexError) as e:
                raise GeometryError("Coordenadas no válidas.") from e
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise GeometryError("Coordenadas fuera de rango.")
            points.append([round(lon, 7), round(lat, 7)])
        if points and points[0] != points[-1]:
            points.append(points[0])
        if len(points) < 4:
            raise GeometryError("Un polígono necesita al menos 3 puntos.")
        total += len(points)
        clean_rings.append(points)
    if total > MAX_VERTICES:
        raise GeometryError(f"El polígono tiene demasiados puntos (máximo {MAX_VERTICES}).")
    polygon = {"type": "Polygon", "coordinates": clean_rings}
    if area_ha(polygon) <= 0:
        raise GeometryError("El polígono no tiene superficie.")
    return polygon


def contains(polygon, lon, lat):
    """Punto dentro del anillo exterior (ray casting)."""
    ring = polygon["coordinates"][0]
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:], strict=False):
        if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def centroid(polygon):
    ring = polygon["coordinates"][0][:-1]
    return sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)


KML_NS = "{http://www.opengis.net/kml/2.2}"


def polygons_from_kml(data):
    """Polígonos [(nombre, Polygon GeoJSON)] de un archivo KML o KMZ (Google Earth)."""
    if data[:2] == b"PK":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as kmz:
                names = [n for n in kmz.namelist() if n.lower().endswith(".kml")]
                if not names:
                    raise GeometryError("El KMZ no contiene un archivo KML.")
                info = kmz.getinfo(names[0])
                if info.file_size > 20 * 1024 * 1024:
                    raise GeometryError("El KML es demasiado grande.")
                data = kmz.read(info)
        except zipfile.BadZipFile as e:
            raise GeometryError("El archivo KMZ está dañado.") from e
    try:
        root = ElementTree.fromstring(data)
    except Exception as e:  # defusedxml rechaza entidades y XML malformado
        raise GeometryError("No se pudo leer el archivo KML.") from e
    ns = KML_NS if root.tag.startswith(KML_NS) else ""
    found = []
    for placemark in root.iter(f"{ns}Placemark"):
        name = (placemark.findtext(f"{ns}name") or "").strip()
        for poly in placemark.iter(f"{ns}Polygon"):
            rings = []
            for boundary in (f"{ns}outerBoundaryIs", f"{ns}innerBoundaryIs"):
                for b in poly.findall(boundary):
                    text = b.findtext(f".//{ns}coordinates") or ""
                    try:
                        ring = [[float(v) for v in c.split(",")[:2]] for c in text.split() if "," in c]
                    except ValueError as e:
                        raise GeometryError("Coordenadas no válidas en el KML.") from e
                    if ring:
                        rings.append(ring)
            if rings:
                found.append((name, clean_polygon({"type": "Polygon", "coordinates": rings})))
    if not found:
        raise GeometryError("El archivo no contiene polígonos.")
    return found
