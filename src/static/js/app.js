// Comportamientos mínimos del sitio. Archivo propio (CSP script-src 'self': sin scripts inline).
document.addEventListener("click", (event) => {
  if (event.target.closest("[data-print]")) window.print();
});
