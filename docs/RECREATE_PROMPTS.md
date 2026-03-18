# Recreate Prompt Pack

Use the prompts below in order with a coding assistant (in a fresh workspace) to recreate this app end-to-end.

---

## 0) Project setup

### Prompt 1
Create a Python FastAPI web app called `weatherapp` with this structure:
- `app/main.py`
- `app/templates/index.html`
- `app/static/app.js`
- `app/static/styles.css`
- `requirements.txt`
- `README.md`
Use minimal boilerplate and ensure it runs with `uvicorn app.main:app --reload`.

### Prompt 2
Set up dependencies in `requirements.txt` for FastAPI app + templates + HTTP client:
- fastapi
- uvicorn
- httpx
- jinja2
- python-multipart

---

## 1) Weather feature (address + date)

### Prompt 3
Build a weather page that takes `address/location` and `date` input and returns daily weather output using Open-Meteo forecast API.
Requirements:
- `GET /` renders HTML form
- `POST /api/weather` accepts form fields and returns JSON
- Geocode location first, then fetch weather
- Return max temp, min temp, precipitation sum, max wind

### Prompt 4
Create frontend JS for weather page:
- submit form with `fetch` to `/api/weather`
- render response in a result card
- show error message when API fails

### Prompt 5
Style the page with modern card layout in `styles.css`.

### Prompt 6
Fix 422 form mismatch issues by ensuring the date field name in HTML matches backend parameter exactly (`date_str`).

---

## 2) Flood-risk feature (new page)

### Prompt 7
Add a new page `/flood-risk` and a new API route `/api/flood-risk`.
Input requirements:
- `address`
- mode: `historical` or `forecast`
- date input only when mode is `historical`
Output requirements:
- flood risk score and level
- weather and flood metrics used in calculation

### Prompt 8
Integrate Open-Meteo services for flood risk:
- Forecast API for current mode weather
- Archive API for historical mode weather
- Flood API for river discharge metrics
Use: precipitation, weather_code, wind_speed_10m_max, river_discharge, river_discharge_mean, river_discharge_max.

### Prompt 9
Create `app/templates/flood.html` and `app/static/flood.js`.
Frontend behavior:
- address input
- mode selector
- show/hide historical date field based on mode
- ensure historical date field is not submitted in forecast mode
- submit to `/api/flood-risk`
- render risk score, risk level, and metric cards

### Prompt 9A
For `forecast` mode in flood risk, return and render a 7-day outlook (today + next 6 days) including per-day weather, flood, and risk values.
Keep `historical` mode as single-day output.
Use clear icons in result cards for risk, precipitation, wind, river/lake proximity, and evacuation details.

---

## 3) Risk model improvements

### Prompt 10
Implement a flood risk scoring function (0-100) that combines:
- same-day precipitation
- river discharge magnitude
- discharge variability (`max/mean`)
- severe weather codes
- wind contribution
Return both total score and component breakdown.

### Prompt 11
Improve historical mode realism:
- fetch 7-day weather window ending at selected historical date
- compute 3-day and 7-day antecedent precipitation
- include antecedent precipitation contribution in risk score

### Prompt 12
Ensure known heavy weather codes are treated as severe contributors, including snow/rain storm classes.

### Prompt 12A
Add water-body proximity detection for the selected location (nearest water body name/type/distance) using OSM/Overpass data, and include it in `/api/flood-risk` response.

Extend proximity payload to include:
- nearest river
- nearby lakes/ponds list sorted by distance

### Prompt 12B
If flood risk is high (or worse), generate evacuation route suggestions to nearby shelters/schools/hospitals and return distance/ETA. Use routing API (e.g., OSRM) with graceful fallback if route ETA is unavailable.

### Prompt 12C
Add an interactive evacuation map on the flood page using OpenStreetMap + Leaflet. Show:
- current location marker
- destination markers for evacuation routes
- route polylines when geometry is available
- hide map when no evacuation routes are returned

---

## 4) Geocoding reliability fixes

### Prompt 13
Fix address geocoding ambiguity.
Use Nominatim as primary address geocoder and Open-Meteo geocoding as fallback.
Return normalized location object with name/country/lat/lon/timezone.

### Prompt 14
Verify that `Snohomish, Washington` resolves to Washington state coordinates (not Washington DC).

---

## 5) Error handling and stability

### Prompt 15
Fix generic “network error” behavior.
Backend:
- reject future dates for historical mode with clear 400 error
- catch upstream HTTP errors and return controlled JSON message
- catch request/network exceptions and return 503 JSON
Frontend:
- parse non-JSON responses safely
- show returned message instead of generic network error

### Prompt 16
Prevent duplicate result rendering on flood page:
- disable submit button during request
- guard against double submit
- replace previous result card instead of appending repeatedly

---

## 6) Navigation and theme customization

### Prompt 17
Replace page-to-page inline links with a shared top navigation bar on both pages:
- Flood Risk Forecast (first)
- Weather (second)

### Prompt 18
Update theme:
- page background navy blue
- improve readability with light text on dark background
- keep card/container text dark for contrast
- make link colors lighter (not default purple)

### Prompt 19
Change primary button color (e.g., “Get weather”) from orange to dark blue.

### Prompt 20
Add cache-busting to stylesheet URL in templates (for example `styles.css?v=2`) so visual changes appear immediately.

---

## 7) Documentation

### Prompt 21
Write a detailed `README.md` with:
- app purpose
- stack
- project structure
- step-by-step build summary
- routes
- risk model explanation
- setup/run/troubleshooting

### Prompt 22
Create a separate architecture document at `docs/ARCHITECTURE.md` including:
- high-level design
- component map
- sequence/data flow diagrams
- error handling strategy
- extension points

### Prompt 23
Create a `docs/RECREATE_PROMPTS.md` file containing all prompts used to rebuild the app in order.

---

## 8) Validation prompts

### Prompt 24
Run and validate:
- weather page request returns 200 + expected fields
- flood page works for forecast mode
- flood forecast response contains 7-day outlook entries
- historical mode rejects future date
- historical date input is hidden/not submitted in forecast mode
- historical mode for `Snohomish, Washington` on `2025-12-18` returns elevated risk (not low)
- flood response includes water-body proximity
- high-risk scenarios include evacuation routes in the response/UI

### Prompt 25
Do a final pass to ensure no syntax errors and all links/routes work.

---

## 9) AI assistant feature

### Prompt 26
Add an AI assistant to the weather page UI where users can type questions and receive responses.
Requirements:
- add a chat panel and input form to `app/templates/index.html`
- implement frontend chat logic in `app/static/app.js`
- call backend endpoint `/api/assistant` with JSON `{ message }`
- render both user and assistant chat bubbles in the page

### Prompt 27
Implement backend route `POST /api/assistant` in `app/main.py`.
Requirements:
- validate JSON input with a required `message`
- return `{ ok: true, reply: "..." }` on success
- support OpenAI Chat Completions via `OPENAI_API_KEY` and optional `OPENAI_MODEL`
- if key is missing or upstream call fails, return a useful built-in fallback response

### Prompt 28
Update docs (`README.md`, `docs/ARCHITECTURE.md`) to include assistant route, environment variables, and behavior.

---

## Optional one-shot prompt

If you want a single command-style prompt instead of step-by-step:

Build a FastAPI weather + flood risk web app with two pages (`/` and `/flood-risk`).
Weather page takes address+date and returns daily weather from Open-Meteo.
Flood page takes address + mode (`forecast` or `historical` + date for historical), uses Open-Meteo Forecast/Archive/Flood APIs, computes explainable 0-100 flood risk score (including antecedent precipitation), and returns risk level + components.
In forecast mode, return a 7-day daily outlook; in historical mode, return single-day output only.
Include nearest water-body proximity and evacuation route suggestions when risk is high.
Use Nominatim primary geocoding with Open-Meteo fallback.
Add robust backend/ frontend error handling, prevent duplicate submits, and reject future historical dates.
Implement navy theme, readable contrast, top nav bar (Flood Risk Forecast first), dark blue primary buttons, and light link colors.
Provide detailed `README.md` and `docs/ARCHITECTURE.md`.
