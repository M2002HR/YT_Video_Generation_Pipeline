// Runs before first paint and is external so the Studio's strict CSP permits it.
try {
  const stored = localStorage.getItem("studio.theme");
  const theme = stored === "light" || stored === "dark"
    ? stored
    : matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
} catch {
  document.documentElement.dataset.theme = "dark";
}

// If a deploy races an already-open tab, refresh once into the newly emitted
// index rather than leaving a stale Vite chunk as a generic "Failed to fetch".
(function () {
  var recoveryKey = "studio.asset-recovery";
  function recover() {
    try {
      if (sessionStorage.getItem(recoveryKey)) return;
      sessionStorage.setItem(recoveryKey, "1");
    } catch {}
    var separator = location.search ? "&" : "?";
    location.replace(location.pathname + location.search + separator + "studio_recover=" + Date.now() + location.hash);
  }
  window.addEventListener("vite:preloadError", function (event) {
    event.preventDefault();
    recover();
  });
  window.addEventListener("error", function (event) {
    var target = event.target;
    var url = target && (target.src || target.href);
    if (url && /\/assets\//.test(url)) recover();
  }, true);
  window.addEventListener("load", function () {
    try { sessionStorage.removeItem(recoveryKey); } catch {}
  });
}());
