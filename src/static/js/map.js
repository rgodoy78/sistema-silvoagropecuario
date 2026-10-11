// Mapa de predios y potreros (Leaflet). Lee los datos de un <script type="application/json">
// y, si hay un polígono en edición, permite dibujarlo: clic agrega un punto, arrastrar lo mueve
// y clic derecho (o mantener presionado en el celular) lo elimina.
(function () {
  const el = document.querySelector("[data-map]");
  if (!el || !window.L) return;
  const data = JSON.parse(document.getElementById(el.dataset.map).textContent);
  const map = L.map(el, { scrollWheelZoom: false, zoomSnap: 0.5 });

  if (el.dataset.key) {
    L.tileLayer(
      "https://ibasemaps-api.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}?token=" +
        encodeURIComponent(el.dataset.key),
      { maxZoom: 19, attribution: "Powered by Esri · Esri, Maxar, Earthstar Geographics y la comunidad de usuarios SIG" }
    ).addTo(map);
  } else {
    el.classList.add("map-blank");
  }

  const toLatLngs = (polygon) => polygon.coordinates.map((ring) => ring.map(([lon, lat]) => [lat, lon]));
  const bounds = L.latLngBounds([]);
  const fmt = (n) => n.toLocaleString("es-CL", { maximumFractionDigits: 1 });

  if (data.farm) {
    const layer = L.polygon(toLatLngs(data.farm.boundary), { className: "map-farm", interactive: false }).addTo(map);
    bounds.extend(layer.getBounds());
  }
  data.paddocks.forEach((p) => {
    const layer = L.polygon(toLatLngs(p.boundary), { className: "map-paddock" }).addTo(map);
    const detail = [p.heads + (p.heads === 1 ? " cabeza" : " cabezas"), p.area ? fmt(p.area) + " ha" : null];
    layer.bindTooltip(`<strong>${escapeHtml(p.name)}</strong><br>${detail.filter(Boolean).join(" · ")}`, {
      permanent: true, direction: "center", className: "map-label",
    });
    bounds.extend(layer.getBounds());
  });

  if (data.edit) startEditor(data.edit.boundary);

  if (bounds.isValid()) map.fitBounds(bounds, { padding: [24, 24] });
  else map.setView([-38.5, -72.5], 6); // Centro-sur de Chile

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function areaHa(points) {
    // Misma fórmula de área esférica que livestock/geo.py.
    const R = 6378137, rad = Math.PI / 180;
    let sum = 0;
    for (let i = 0; i < points.length; i++) {
      const a = points[i], b = points[(i + 1) % points.length];
      sum += (b.lng - a.lng) * rad * (2 + Math.sin(a.lat * rad) + Math.sin(b.lat * rad));
    }
    return Math.abs((sum * R * R) / 2) / 10000;
  }

  function startEditor(boundary) {
    const input = document.querySelector("[data-map-input]");
    const areaEl = document.querySelector("[data-map-area]");
    let points = boundary ? toLatLngs(boundary)[0].slice(0, -1).map((p) => L.latLng(p)) : [];
    const shape = L.polygon([], { className: "map-edit", interactive: false }).addTo(map);
    const handles = L.layerGroup().addTo(map);
    const icon = L.divIcon({ className: "map-vertex", iconSize: [16, 16] });

    function sync() {
      shape.setLatLngs(points);
      const ring = points.map((p) => [Number(p.lng.toFixed(7)), Number(p.lat.toFixed(7))]);
      input.value = points.length >= 3 ? JSON.stringify({ type: "Polygon", coordinates: [[...ring, ring[0]]] }) : "";
      areaEl.textContent = points.length >= 3 ? fmt(areaHa(points)) + " ha" : "—";
    }

    function redraw() {
      handles.clearLayers();
      points.forEach((point, i) => {
        const marker = L.marker(point, { draggable: true, icon }).addTo(handles);
        marker.on("drag", (e) => { points[i] = e.target.getLatLng(); sync(); });
        marker.on("contextmenu", () => { points.splice(i, 1); redraw(); });
      });
      sync();
    }

    map.on("click", (e) => { points.push(e.latlng); redraw(); });
    document.querySelector("[data-map-undo]")?.addEventListener("click", () => { points.pop(); redraw(); });
    document.querySelector("[data-map-clear]")?.addEventListener("click", () => { points = []; redraw(); });
    redraw();
    if (points.length) bounds.extend(L.latLngBounds(points));
  }
})();
