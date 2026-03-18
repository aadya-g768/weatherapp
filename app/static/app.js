const form = document.querySelector("#weather-form");
const statusEl = document.querySelector("#status");
const resultEl = document.querySelector("#result");

const setStatus = (message) => {
  statusEl.textContent = message;
};

const clearResult = () => {
  resultEl.innerHTML = "";
};

const renderResult = (payload) => {
  const location = payload.location;
  const weather = payload.weather;

  const card = document.createElement("div");
  card.className = "result-card";
  card.innerHTML = `
    <div class="result-title">${location.name}, ${location.country}</div>
    <div>Forecast for ${weather.date}</div>
    <div class="result-grid">
      <div class="result-item">Max temp: ${weather.temperature_max_c}°C</div>
      <div class="result-item">Min temp: ${weather.temperature_min_c}°C</div>
      <div class="result-item">Precipitation: ${weather.precipitation_mm} mm</div>
      <div class="result-item">Max wind: ${weather.wind_speed_max_kmh} km/h</div>
    </div>
  `;

  resultEl.appendChild(card);
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearResult();
  setStatus("Fetching forecast...");

  const formData = new FormData(form);

  try {
    const response = await fetch("/api/weather", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok || !data.ok) {
      setStatus(data.message || "Unable to fetch weather.");
      return;
    }

    setStatus("Forecast ready.");
    renderResult(data);
  } catch (error) {
    setStatus("Network error. Try again in a moment.");
  }
});
