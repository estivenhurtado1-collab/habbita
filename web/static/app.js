// Habitta ia — interacciones ligeras
document.querySelectorAll(".score-ring").forEach((el) => {
  const score = parseInt(el.dataset.score || "0", 10);
  if (score >= 65) el.style.background = "#16a34a";
  else if (score < 45) el.style.background = "#dc2626";
});

const topbarToggle = document.querySelector(".topbar-toggle");
const topbarMenu = document.getElementById("topbar-menu");
if (topbarToggle && topbarMenu) {
  topbarToggle.addEventListener("click", () => {
    const open = topbarMenu.classList.toggle("is-open");
    topbarToggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
}

/** Mapas Leaflet (inicio, favoritos, comparar). */
window.HabittaMaps = {
  initMap(containerId, markers) {
    if (typeof L === "undefined") {
      console.warn("HabittaMaps: Leaflet no cargó");
      return null;
    }
    const el = document.getElementById(containerId);
    if (!el || !markers?.length) return null;

    if (el._habittaMap) {
      el._habittaMap.remove();
      el._habittaMap = null;
    }

    const map = L.map(containerId, { scrollWheelZoom: true }).setView(
      [4.65, -74.06],
      12
    );
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    const bounds = [];
    markers.forEach((m) => {
      const isHome = !!m.is_home;
      const color = m.color || "#2563eb";
      const marker = L.circleMarker([m.lat, m.lng], {
        radius: isHome ? 13 : 11,
        color: "#fff",
        weight: 2,
        fillColor: color,
        fillOpacity: 0.95,
      }).addTo(map);

      if (isHome) {
        marker.bindPopup(
          `<b>Donde vives</b><br>${m.neighborhood || ""}<br><a href="/perfil">Editar en perfil</a>`
        );
        marker.bindTooltip("Donde vives", { permanent: false });
      } else {
        const priceTxt = m.price
          ? "$" + Number(m.price).toLocaleString("es-CO")
          : "Precio en portal";
        const detailUrl = m.id ? `/propiedad/${m.id}` : m.original_url || "#";
        marker.bindPopup(
          `<b>${m.title || "Inmueble"}</b><br>${m.neighborhood || ""}<br>${priceTxt}<br>Score: ${m.score ?? "—"}<br><a href="${detailUrl}">Ver detalle</a>`
        );
        marker.bindTooltip(m.neighborhood || "Favorito", { permanent: false });
      }
      bounds.push([m.lat, m.lng]);
    });

    if (bounds.length === 1) {
      map.setView(bounds[0], 14);
    } else if (bounds.length > 1) {
      map.fitBounds(bounds, { padding: [48, 48] });
    }

    const fixSize = () => {
      try {
        map.invalidateSize();
      } catch (e) {
        /* ignore */
      }
    };
    fixSize();
    setTimeout(fixSize, 100);
    setTimeout(fixSize, 400);

    el._habittaMap = map;
    return map;
  },

  initFromPage() {
    document.querySelectorAll("[data-habitta-map]").forEach((el) => {
      const srcId = el.getAttribute("data-markers-src");
      if (!srcId || !el.id) return;
      const src = document.getElementById(srcId);
      if (!src) return;
      let markers;
      try {
        markers = JSON.parse(src.textContent || "[]");
      } catch (err) {
        console.warn("HabittaMaps: JSON inválido", err);
        return;
      }
      this.initMap(el.id, markers);
    });
  },
};

window.habittaInitMaps = function habittaInitMaps() {
  if (typeof L === "undefined") return;
  window.HabittaMaps.initFromPage();
};
