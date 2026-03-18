# Weather + Flood Risk App

This project is a FastAPI web app with three user-facing pages:

- Weather page: enter address + date to get daily weather.
- Flood Risk page: enter address + mode (`historical` date or `current forecast`) to compute flood risk.
- Social page: post community updates in tabs (Questions, Experiences, Feedback, Help) with replies.
- Weather page AI assistant: ask questions and receive assistant responses in-page.

---

## 1) What the app does

The app combines weather and flood datasets to produce practical outputs for a given location:

1. Resolve address to coordinates (latitude/longitude)
2. Fetch weather data (forecast or historical)
3. Fetch flood river-discharge data
4. Compute a flood-risk score and level
5. Return results to the browser

Main capabilities:

- Address-based geocoding (not just city names)
- Historical and current-forecast flood-risk modes
- Defensive backend validation and error handling
- Simple frontend UX with navigation between Weather and Flood Risk pages
- Social posting/replies persisted in SQLite (`app/social.db`)
- AI assistant endpoint at `/api/assistant` with OpenAI support via environment variable

---

## 2) Tech stack used

- Backend: FastAPI + Uvicorn
- HTTP client: httpx (async)
- Templates: Jinja2
- Frontend: vanilla HTML/CSS/JavaScript
- Data providers:
	- Open-Meteo Forecast API
	- Open-Meteo Historical Archive API
	- Open-Meteo Flood API
	- Nominatim geocoding (address fallback)

Dependencies are listed in `requirements.txt`.

---

## 3) Project structure

```
weatherapp/
├─ app/
│  ├─ main.py                  # FastAPI app, routes, API integration, risk scoring
│  ├─ templates/
│  │  ├─ index.html            # Weather page
│  │  └─ flood.html            # Flood risk page
│  └─ static/
│     ├─ app.js                # Weather page frontend logic
│     ├─ flood.js              # Flood page frontend logic
│     └─ styles.css            # Shared styling/theme
├─ requirements.txt
└─ README.md
```

---

## 4) Build process (step-by-step)

### Step A: Base weather app

- Created FastAPI app and mounted static/template directories.
- Added `GET /` route to render weather form.
- Added `POST /api/weather` to:
	- parse date input
	- geocode location
	- call Open-Meteo forecast endpoint
	- return JSON payload for frontend display

### Step B: Frontend weather page

- Built a simple HTML form for address/date input.
- Added JavaScript to call `/api/weather` and render result cards.
- Added CSS for layout and card styling.

### Step C: Flood-risk feature

- Added new page route `GET /flood-risk`.
- Added API route `POST /api/flood-risk`.
- Added `flood.html` + `flood.js` with:
	- address input
	- mode selector (`forecast` or `historical`)
	- conditional date input for historical mode
	- risk result rendering

### Step D: Data integration for risk

- Weather inputs fetched from:
	- Forecast API for current mode
	- Archive API for historical mode
- Flood inputs fetched from Flood API (`river_discharge`, `river_discharge_mean`, `river_discharge_max`)
- Added multi-day precipitation context (3-day and 7-day sums) for historical realism.

### Step E: Address reliability improvements

- Fixed geocoding issues where addresses were resolved incorrectly.
- Implemented Nominatim-first address geocoding with Open-Meteo geocoding fallback.

### Step F: Stability and UX fixes

- Fixed `422` form mismatch by aligning input field names.
- Prevented duplicate submissions on flood form.
- Improved frontend error parsing to avoid generic "network error" when server returns non-JSON.
- Added backend validation for future dates in historical mode.
- Added robust exception handling for external API failures.

### Step G: Theming updates

- Updated background to navy blue.
- Improved text contrast and container readability.
- Replaced inline page links with a top navigation bar.
- Changed action button color from orange to dark blue.

---

## 5) API routes in this app

### UI routes

- `GET /` → Weather page
- `GET /flood-risk` → Flood Risk page
- `GET /social` → Social page

### JSON/form routes

- `POST /api/weather`
	- Inputs: `location`, `date_str`
	- Output: weather metrics (max/min temp, precipitation, wind)

- `POST /api/flood-risk`
	- Inputs: `address`, `mode`, optional `date_str`
	- Output: weather + flood metrics + computed risk

- `GET /api/social/posts`
	- Inputs: optional `tab`
	- Output: posts + replies

- `POST /api/social/posts`
	- Inputs: `tab`, `message`, optional `created_at`

- `POST /api/social/replies`
	- Inputs: `tab`, `post_id`, `message`, optional `created_at`

- `POST /api/social/posts/update-time`
	- Inputs: `tab`, `id`, `created_at`

- `DELETE /api/social/posts`
	- Inputs: `tab`, `post_id`

- `POST /api/assistant`
	- JSON input: `message`
	- Output: assistant text response

---

## 6) Flood risk model used

Risk is computed as a composite score out of 100 based on:

- Same-day precipitation
- Antecedent precipitation (3-day / 7-day accumulation)
- River discharge magnitude
- Discharge variability (max vs mean)
- Severe weather codes
- Wind intensity

Score maps to levels:

- `Low`
- `Moderate`
- `High`
- `Very High`
- `Severe`

This is a heuristic model (engineering approximation), not an official hydrological warning model.

---

## 7) Known constraints

- Open-Meteo flood data is grid-based and may not perfectly match specific river channels.
- Historical mode cannot use future dates.
- Results depend on provider coverage and model availability for location/date.

---

## 8) Local setup and run

## Requirements

- Python 3.10+

## Install

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

If PowerShell blocks activation:

```bash
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

## Run

```bash
uvicorn app.main:app --reload
```

Optional AI config (PowerShell):

```bash
$env:OPENAI_API_KEY="your_api_key_here"
$env:OPENAI_MODEL="gpt-4o-mini"
```

If `OPENAI_API_KEY` is not set, the assistant still responds using built-in fallback guidance.

Open:

- Weather page: http://127.0.0.1:8000/
- Flood Risk page: http://127.0.0.1:8000/flood-risk

---

## 9) Troubleshooting

- If UI changes do not appear: hard refresh with `Ctrl+F5`.
- If you see location mismatch: try a fuller address (street, city, state/country).
- If historical request fails: ensure the date is not in the future.
- If provider request fails: retry with nearby location/date due to dataset coverage limits.

---

## 10) Additional Documentation

- Architecture document: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
