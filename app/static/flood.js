const form = document.querySelector("#flood-form");
const statusEl = document.querySelector("#status");
const resultEl = document.querySelector("#result");
const modeEl = document.querySelector("#mode");
const dateFieldEl = document.querySelector("#date-field");
const dateInputEl = document.querySelector("#date-input");
const submitButtonEl = form.querySelector("button[type='submit']");
const dateInputName = dateInputEl.getAttribute("name");
const evacMapEl = document.querySelector("#evac-map");

let isSubmitting = false;
let evacuationMap;
let evacuationLayer;

const setStatus = (message) => {
  statusEl.textContent = message;
};

const clearResult = () => {
  resultEl.innerHTML = "";
  evacMapEl.hidden = true;
  if (evacuationLayer && evacuationMap) {
    evacuationLayer.clearLayers();
  }
};

const ensureMap = () => {
  if (!window.L) {
    return null;
  }

  if (!evacuationMap) {
    evacuationMap = L.map(evacMapEl).setView([0, 0], 2);
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(evacuationMap);
    evacuationLayer = L.layerGroup().addTo(evacuationMap);
  }

  return evacuationMap;
};

const renderEvacuationMap = (data) => {
  if (!Array.isArray(data.evacuation_routes) || data.evacuation_routes.length === 0) {
    evacMapEl.hidden = true;
    return;
  }

  const map = ensureMap();
  if (!map || !evacuationLayer) {
    return;
  }

  evacMapEl.hidden = false;
  evacuationLayer.clearLayers();

  const points = [];
  const originLat = data.location?.latitude;
  const originLon = data.location?.longitude;

  if (originLat != null && originLon != null) {
    const origin = L.marker([originLat, originLon]).bindPopup("Current location");
    evacuationLayer.addLayer(origin);
    points.push([originLat, originLon]);
  }

  data.evacuation_routes.forEach((route) => {
    const lat = route.destination_latitude;
    const lon = route.destination_longitude;
    if (lat != null && lon != null) {
      const marker = L.marker([lat, lon]).bindPopup(
        `${route.destination}<br/>${route.distance_km} km${route.duration_min != null ? ` • ${route.duration_min} min` : ""}`
      );
      evacuationLayer.addLayer(marker);
      points.push([lat, lon]);
    }

    if (Array.isArray(route.route_geometry) && route.route_geometry.length > 1) {
      const latLngs = route.route_geometry
        .filter((pair) => Array.isArray(pair) && pair.length === 2)
        .map((pair) => [pair[1], pair[0]]);
      if (latLngs.length > 1) {
        evacuationLayer.addLayer(
          L.polyline(latLngs, {
            color: "#0b3d91",
            weight: 4,
            opacity: 0.75,
          })
        );
      }
    }
  });

  if (points.length > 0) {
    map.fitBounds(points, { padding: [20, 20] });
    setTimeout(() => map.invalidateSize(), 0);
  }
};

const updateModeUi = () => {
  const isHistorical = modeEl.value === "historical";
  dateFieldEl.hidden = !isHistorical;
  dateInputEl.required = isHistorical;
  if (isHistorical) {
    dateInputEl.setAttribute("name", dateInputName);
  } else {
    dateInputEl.removeAttribute("name");
    dateInputEl.value = "";
  }
};

const renderResult = (data) => {
  const riskLevel = (data.risk?.level || "").toLowerCase().replace(/\s+/g, "-");
  const nearestRiverText = data.water_proximity?.nearest_river
    ? `${data.water_proximity.nearest_river.name} (${data.water_proximity.nearest_river.type}) - ${data.water_proximity.nearest_river.distance_km} km`
    : "n/a";

  const lakesText = Array.isArray(data.water_proximity?.nearby_lakes) && data.water_proximity.nearby_lakes.length
    ? data.water_proximity.nearby_lakes
        .slice(0, 3)
        .map((lake) => `${lake.name} (${lake.distance_km} km)`)
        .join(", ")
    : "n/a";

  const card = document.createElement("div");
  card.className = "result-card";
  card.innerHTML = `
    <div class="result-title">${data.location.name}, ${data.location.country}</div>
    <div>Mode: ${data.mode} • Date: ${data.date}</div>
    <div class="result-grid">
      <div class="result-item risk-level risk-${riskLevel}">⚠️ Risk level: ${data.risk.level}</div>
      <div class="result-item">📊 Risk score: ${data.risk.score}/100</div>
      <div class="result-item">🌧️ Precipitation: ${data.weather.precipitation_mm ?? "n/a"} mm</div>
      <div class="result-item">🕒 3-day precipitation: ${data.weather.antecedent_precip_3day_mm ?? "n/a"} mm</div>
      <div class="result-item">📆 7-day precipitation: ${data.weather.antecedent_precip_7day_mm ?? "n/a"} mm</div>
      <div class="result-item">☁️ Weather code: ${data.weather.weather_code ?? "n/a"}</div>
      <div class="result-item">💨 Wind max: ${data.weather.wind_speed_max_kmh ?? "n/a"} km/h</div>
      <div class="result-item">🌊 River discharge: ${data.flood.river_discharge_m3s ?? "n/a"} m³/s</div>
      <div class="result-item">📈 Discharge mean: ${data.flood.river_discharge_mean_m3s ?? "n/a"} m³/s</div>
      <div class="result-item">📉 Discharge max: ${data.flood.river_discharge_max_m3s ?? "n/a"} m³/s</div>
      <div class="result-item">💧 Water proximity: ${data.water_proximity?.found ? `${data.water_proximity.nearest.name} (${data.water_proximity.nearest.type}) - ${data.water_proximity.nearest.distance_km} km` : data.water_proximity?.message ?? "n/a"}</div>
      <div class="result-item">🏞️ Nearest river: ${nearestRiverText}</div>
      <div class="result-item">🟦 Nearby lakes: ${lakesText}</div>
    </div>
  `;

  const nodes = [card];

  if (Array.isArray(data.evacuation_routes) && data.evacuation_routes.length > 0) {
    const routesCard = document.createElement("div");
    routesCard.className = "result-card";
    const routesItems = data.evacuation_routes
      .map(
        (route) => `
      <div class="result-item">
        <strong>🚨 ${route.destination}</strong> (${route.destination_type})<br />
        📍 Distance: ${route.distance_km} km<br />
        ${route.duration_min != null ? `⏱️ ETA: ${route.duration_min} min` : "⏱️ ETA: n/a"}
      </div>
    `
      )
      .join("");

    routesCard.innerHTML = `
      <div class="result-title">Evacuation Routes (High Risk)</div>
      <div class="result-grid">${routesItems}</div>
    `;
    nodes.push(routesCard);
  }

  if (Array.isArray(data.forecast_7days) && data.forecast_7days.length > 0) {
    const outlook = document.createElement("div");
    outlook.className = "result-card";
    const outlookItems = data.forecast_7days
      .map(
        (day) => `
      <div class="result-item">
        <strong>📅 ${day.date}</strong><br />
        ⚠️ Risk: ${day.risk.level} (${day.risk.score}/100)<br />
        🌧️ Precipitation: ${day.weather.precipitation_mm ?? "n/a"} mm<br />
        💨 Wind max: ${day.weather.wind_speed_max_kmh ?? "n/a"} km/h<br />
        🌊 River discharge: ${day.flood.river_discharge_m3s ?? "n/a"} m³/s
      </div>
    `
      )
      .join("");

    outlook.innerHTML = `
      <div class="result-title">Next 7 Days Forecast Outlook</div>
      <div class="result-grid">${outlookItems}</div>
    `;
    nodes.push(outlook);
  }

  resultEl.replaceChildren(...nodes);
  renderEvacuationMap(data);
};

modeEl.addEventListener("change", updateModeUi);
updateModeUi();

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (isSubmitting) {
    return;
  }

  isSubmitting = true;
  submitButtonEl.disabled = true;
  clearResult();
  setStatus("Calculating flood risk...");

  const formData = new FormData(form);

  try {
    const response = await fetch("/api/flood-risk", {
      method: "POST",
      body: formData,
    });
    const contentType = response.headers.get("content-type") || "";
    let data;
    if (contentType.includes("application/json")) {
      data = await response.json();
    } else {
      const text = await response.text();
      data = { ok: false, message: text || "Server error." };
    }

    if (!response.ok || !data.ok) {
      setStatus(data.message || "Unable to calculate flood risk.");
      return;
    }

    setStatus("Flood risk forecast ready.");
    renderResult(data);
  } catch (error) {
    setStatus("Network error. Try again in a moment.");
  } finally {
    isSubmitting = false;
    submitButtonEl.disabled = false;
  }
});
