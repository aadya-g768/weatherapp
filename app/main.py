from __future__ import annotations

from datetime import datetime
from datetime import date
from datetime import timedelta
import asyncio
from math import asin
from math import cos
from math import radians
from math import sin
from math import sqrt
from pathlib import Path
import sqlite3
import os
from typing import Any, Dict
from uuid import uuid4

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI()

app.mount("/static", StaticFiles(directory="app/static"), name="static")

templates = Jinja2Templates(directory="app/templates")

OPEN_METEO_GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FLOOD_URL = "https://flood-api.open-meteo.com/v1/flood"
NOMINATIM_SEARCH_URL = "https://nominatim.openstreetmap.org/search"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
OSRM_ROUTE_URL = "https://router.project-osrm.org/route/v1/driving"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

HEAVY_WEATHER_CODES = {63, 65, 67, 73, 75, 81, 82, 86, 95, 96, 99}
SOCIAL_TABS = ("Help", "Experiences", "Feedback", "Questions")
SOCIAL_DB_PATH = Path("app") / "social.db"

ASSISTANT_SYSTEM_PROMPT = (
    "You are a concise assistant for a weather and flood-risk web app. "
    "Answer clearly, avoid markdown tables, and keep responses practical. "
    "If users ask safety-related flood questions, include high-level preparedness steps and suggest local official alerts."
)


def _db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(SOCIAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_social_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _init_social_db() -> None:
    with _db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tab TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                likes INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_replies (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                likes INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(post_id) REFERENCES social_posts(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS social_post_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                post_id INTEGER NOT NULL,
                user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(post_id, user_id),
                FOREIGN KEY(post_id) REFERENCES social_posts(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_posts_tab ON social_posts(tab)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_replies_post_id ON social_replies(post_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_social_post_likes_post_id ON social_post_likes(post_id)")
        _ensure_social_column(conn, "social_posts", "likes", "INTEGER NOT NULL DEFAULT 0")
        _ensure_social_column(conn, "social_replies", "likes", "INTEGER NOT NULL DEFAULT 0")


def _resolve_social_user_id(request: Request, payload_user_id: str | None = None) -> tuple[str, bool]:
    provided = str(payload_user_id or "").strip()
    if provided:
        normalized = provided[:128]
        current_cookie = str(request.cookies.get("social_user_id") or "").strip()
        return normalized, current_cookie != normalized

    existing = str(request.cookies.get("social_user_id") or "").strip()
    if existing:
        return existing, False
    return uuid4().hex, True


def _load_social_posts(tab: str) -> list[Dict[str, Any]]:
    with _db_connect() as conn:
        post_rows = conn.execute(
            """
            SELECT p.id, p.message, p.created_at, p.likes, COUNT(r.id) AS reply_count
            FROM social_posts p
            LEFT JOIN social_replies r ON r.post_id = p.id
            WHERE p.tab = ?
            GROUP BY p.id, p.message, p.created_at, p.likes
            ORDER BY CASE WHEN COUNT(r.id) > 0 THEN 0 ELSE 1 END, datetime(p.created_at) DESC, p.id DESC
            """,
            (tab,),
        ).fetchall()

        post_ids = [int(row["id"]) for row in post_rows]
        replies_by_post: Dict[int, list[Dict[str, Any]]] = {post_id: [] for post_id in post_ids}

        if post_ids:
            placeholders = ",".join("?" for _ in post_ids)
            reply_rows = conn.execute(
                f"""
                SELECT id, post_id, message, created_at, likes
                FROM social_replies
                WHERE post_id IN ({placeholders})
                ORDER BY datetime(created_at) ASC, id ASC
                """,
                post_ids,
            ).fetchall()

            for row in reply_rows:
                replies_by_post[int(row["post_id"])].append(
                    {
                        "id": int(row["id"]),
                        "message": row["message"],
                        "created_at": row["created_at"],
                        "likes": int(row["likes"] or 0),
                    }
                )

        posts: list[Dict[str, Any]] = []
        for row in post_rows:
            post_id = int(row["id"])
            posts.append(
                {
                    "id": post_id,
                    "message": row["message"],
                    "created_at": row["created_at"],
                    "likes": int(row["likes"] or 0),
                    "replies": replies_by_post.get(post_id, []),
                }
            )

        return posts


@app.on_event("startup")
def _startup() -> None:
    _init_social_db()


def _parse_weather_payload(payload: Dict[str, Any], target_date: date) -> Dict[str, Any]:
    daily = payload.get("daily") or {}
    time_list = daily.get("time") or []
    if target_date.isoformat() not in time_list:
        return {
            "ok": False,
            "message": "No daily weather found for that date.",
        }

    index = time_list.index(target_date.isoformat())
    max_temp = (daily.get("temperature_2m_max") or [None])[index]
    min_temp = (daily.get("temperature_2m_min") or [None])[index]
    precipitation_sum = (daily.get("precipitation_sum") or [None])[index]
    wind_max = (daily.get("wind_speed_10m_max") or [None])[index]

    return {
        "ok": True,
        "date": target_date.isoformat(),
        "temperature_max_c": max_temp,
        "temperature_min_c": min_temp,
        "precipitation_mm": precipitation_sum,
        "wind_speed_max_kmh": wind_max,
    }


def _parse_daily_values(payload: Dict[str, Any], target_date: date, fields: list[str]) -> Dict[str, Any]:
    daily = payload.get("daily") or {}
    time_list = daily.get("time") or []
    target = target_date.isoformat()
    if target not in time_list:
        return {"ok": False, "message": "No daily data available for that date."}

    index = time_list.index(target)
    parsed: Dict[str, Any] = {"ok": True, "date": target}
    for field in fields:
        values = daily.get(field) or []
        parsed[field] = values[index] if index < len(values) else None
    return parsed


def _parse_daily_series(payload: Dict[str, Any], fields: list[str]) -> Dict[str, Any]:
    daily = payload.get("daily") or {}
    time_list = daily.get("time") or []
    if not time_list:
        return {"ok": False, "message": "No daily data available for this period."}

    days: list[Dict[str, Any]] = []
    for index, day_value in enumerate(time_list):
        day_payload: Dict[str, Any] = {"date": day_value}
        for field in fields:
            values = daily.get(field) or []
            day_payload[field] = values[index] if index < len(values) else None
        days.append(day_payload)

    return {"ok": True, "days": days}


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * earth_radius_km * asin(sqrt(a))


def _overpass_element_coords(element: Dict[str, Any]) -> tuple[float, float] | None:
    if "lat" in element and "lon" in element:
        return float(element["lat"]), float(element["lon"])
    center = element.get("center") or {}
    if "lat" in center and "lon" in center:
        return float(center["lat"]), float(center["lon"])
    return None


def _is_high_risk(level: str | None, score: float | int | None) -> bool:
    if level in {"High", "Very High", "Severe"}:
        return True
    if isinstance(score, (int, float)) and score >= 55:
        return True
    return False


async def _safe_fetch_water_proximity(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
) -> Dict[str, Any]:
    try:
        return await asyncio.wait_for(
            _fetch_water_body_proximity(client, latitude, longitude),
            timeout=10.0,
        )
    except (asyncio.TimeoutError, httpx.HTTPError):
        return {
            "found": False,
            "message": "Water proximity unavailable right now.",
            "nearest_river": None,
            "nearby_lakes": [],
        }


async def _safe_fetch_evacuation_routes(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
) -> list[Dict[str, Any]]:
    try:
        return await asyncio.wait_for(
            _fetch_evacuation_routes(client, latitude, longitude),
            timeout=12.0,
        )
    except (asyncio.TimeoutError, httpx.HTTPError):
        return []


def _assistant_fallback_response(message: str) -> str:
    text = message.strip().lower()
    if any(keyword in text for keyword in ("flood", "evac", "river", "risk")):
        return (
            "Flood risk is influenced by rain totals, recent multi-day rainfall, and river discharge. "
            "Use the Flood Risk page with an address to check current or historical risk, and follow your local emergency alerts for official guidance."
        )
    if any(keyword in text for keyword in ("weather", "forecast", "rain", "wind", "temperature")):
        return (
            "For weather details, open the Weather page, enter an address and date, then submit to see max/min temperature, precipitation, and wind speed."
        )
    if any(keyword in text for keyword in ("social", "post", "reply", "comment")):
        return (
            "Use the Social page to post in Help, Experiences, Feedback, or Questions, and reply or like community messages."
        )
    return (
        "I can help with this app's weather lookups, flood-risk checks, and social features. "
        "Ask me something like: 'How do I check flood risk for next week?'"
    )


async def _generate_assistant_reply(message: str) -> str:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return _assistant_fallback_response(message)

    payload = {
        "model": OPENAI_MODEL,
        "messages": [
            {"role": "system", "content": ASSISTANT_SYSTEM_PROMPT},
            {"role": "user", "content": message},
        ],
        "temperature": 0.4,
    }

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            response = await client.post(
                OPENAI_API_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
    except (httpx.HTTPError, ValueError):
        return _assistant_fallback_response(message)

    choices = data.get("choices") or []
    if not choices:
        return _assistant_fallback_response(message)

    first_choice = choices[0] or {}
    content = ((first_choice.get("message") or {}).get("content") or "").strip()
    return content or _assistant_fallback_response(message)


async def _fetch_water_body_proximity(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
) -> Dict[str, Any]:
    query = f"""
    [out:json][timeout:25];
    (
      nwr(around:5000,{latitude},{longitude})[\"natural\"=\"water\"];
      nwr(around:5000,{latitude},{longitude})[\"waterway\"~\"river|stream|canal\"];
    );
    out center 30;
    """
    try:
        response = await client.post(OVERPASS_URL, data={"data": query}, timeout=30.0)
        response.raise_for_status()
        elements = (response.json() or {}).get("elements") or []
    except httpx.HTTPError:
        return {
            "found": False,
            "message": "Water proximity service is temporarily unavailable.",
            "nearest_river": None,
            "nearby_lakes": [],
        }

    if not elements:
        return {
            "found": False,
            "message": "No nearby water body detected within 5 km.",
            "nearest_river": None,
            "nearby_lakes": [],
        }

    nearest: Dict[str, Any] | None = None
    nearest_river: Dict[str, Any] | None = None
    lakes: list[Dict[str, Any]] = []
    for element in elements:
        coords = _overpass_element_coords(element)
        if not coords:
            continue
        distance_km = _haversine_km(latitude, longitude, coords[0], coords[1])
        tags = element.get("tags") or {}
        waterway_type = tags.get("waterway")
        natural_type = tags.get("natural")
        water_type = tags.get("water")

        candidate = {
            "name": tags.get("name") or water_type or waterway_type or "Unnamed water body",
            "type": waterway_type or water_type or natural_type or "water",
            "distance_km": round(distance_km, 2),
            "latitude": coords[0],
            "longitude": coords[1],
        }
        if nearest is None or candidate["distance_km"] < nearest["distance_km"]:
            nearest = candidate

        if waterway_type in {"river", "stream", "canal"}:
            if nearest_river is None or candidate["distance_km"] < nearest_river["distance_km"]:
                nearest_river = {
                    "name": tags.get("name") or waterway_type,
                    "type": waterway_type,
                    "distance_km": candidate["distance_km"],
                    "latitude": candidate["latitude"],
                    "longitude": candidate["longitude"],
                }

        is_lake = water_type in {"lake", "reservoir", "pond", "lagoon"}
        if natural_type == "water" and is_lake:
            lakes.append(
                {
                    "name": tags.get("name") or water_type,
                    "type": water_type,
                    "distance_km": candidate["distance_km"],
                    "latitude": candidate["latitude"],
                    "longitude": candidate["longitude"],
                }
            )

    if not nearest:
        return {
            "found": False,
            "message": "No nearby water body detected within 5 km.",
            "nearest_river": None,
            "nearby_lakes": [],
        }

    lakes.sort(key=lambda item: item["distance_km"])

    return {
        "found": True,
        "nearest": nearest,
        "nearest_river": nearest_river,
        "nearby_lakes": lakes[:5],
    }


async def _fetch_evacuation_routes(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
) -> list[Dict[str, Any]]:
    query = f"""
    [out:json][timeout:25];
    (
      nwr(around:20000,{latitude},{longitude})[\"amenity\"~\"hospital|school|community_centre\"];
      nwr(around:20000,{latitude},{longitude})[\"emergency\"=\"shelter\"];
      nwr(around:20000,{latitude},{longitude})[\"building\"=\"shelter\"];
    );
    out center 80;
    """
    try:
        response = await client.post(OVERPASS_URL, data={"data": query}, timeout=30.0)
        response.raise_for_status()
        elements = (response.json() or {}).get("elements") or []
    except httpx.HTTPError:
        return []

    candidates: list[Dict[str, Any]] = []
    for element in elements:
        coords = _overpass_element_coords(element)
        if not coords:
            continue
        tags = element.get("tags") or {}
        name = tags.get("name") or tags.get("amenity") or tags.get("emergency") or "Safe destination"
        destination_type = tags.get("amenity") or tags.get("emergency") or tags.get("building") or "destination"
        distance_km = _haversine_km(latitude, longitude, coords[0], coords[1])
        candidates.append(
            {
                "name": name,
                "type": destination_type,
                "latitude": coords[0],
                "longitude": coords[1],
                "straight_line_km": round(distance_km, 2),
            }
        )

    candidates.sort(key=lambda item: item["straight_line_km"])
    top_candidates = candidates[:2]

    async def _route_for_destination(destination: Dict[str, Any]) -> Dict[str, Any]:
        try:
            route_response = await client.get(
                f"{OSRM_ROUTE_URL}/{longitude},{latitude};{destination['longitude']},{destination['latitude']}",
                params={
                    "overview": "simplified",
                    "geometries": "geojson",
                    "alternatives": "false",
                    "steps": "false",
                },
                timeout=8.0,
            )

            if route_response.status_code == 200:
                route_data = route_response.json()
                routes_data = route_data.get("routes") or []
                if routes_data:
                    primary_route = routes_data[0]
                    return {
                        "destination": destination["name"],
                        "destination_type": destination["type"],
                        "destination_latitude": destination["latitude"],
                        "destination_longitude": destination["longitude"],
                        "distance_km": round((primary_route.get("distance") or 0) / 1000, 2),
                        "duration_min": round((primary_route.get("duration") or 0) / 60, 1),
                        "straight_line_km": destination["straight_line_km"],
                        "route_geometry": (primary_route.get("geometry") or {}).get("coordinates"),
                    }
        except httpx.HTTPError:
            pass

        return {
            "destination": destination["name"],
            "destination_type": destination["type"],
            "destination_latitude": destination["latitude"],
            "destination_longitude": destination["longitude"],
            "distance_km": destination["straight_line_km"],
            "duration_min": None,
            "straight_line_km": destination["straight_line_km"],
            "route_geometry": None,
        }

    if not top_candidates:
        return []

    return list(await asyncio.gather(*[_route_for_destination(destination) for destination in top_candidates]))


def _risk_from_inputs(
    precipitation_mm: float | None,
    antecedent_precip_3day_mm: float | None,
    antecedent_precip_7day_mm: float | None,
    river_discharge: float | None,
    river_discharge_mean: float | None,
    river_discharge_max: float | None,
    weather_code: int | None,
    wind_speed_max_kmh: float | None,
) -> Dict[str, Any]:
    precip = precipitation_mm if precipitation_mm is not None else 0.0
    antecedent_3 = antecedent_precip_3day_mm if antecedent_precip_3day_mm is not None else 0.0
    antecedent_7 = antecedent_precip_7day_mm if antecedent_precip_7day_mm is not None else 0.0
    discharge = river_discharge if river_discharge is not None else 0.0
    discharge_mean = river_discharge_mean if river_discharge_mean is not None else 0.0
    discharge_max = river_discharge_max if river_discharge_max is not None else 0.0
    wind = wind_speed_max_kmh if wind_speed_max_kmh is not None else 0.0

    if precip < 5:
        precip_score = 4
    elif precip < 20:
        precip_score = 16
    elif precip < 50:
        precip_score = 30
    else:
        precip_score = 42

    if antecedent_3 >= 60 or antecedent_7 >= 120:
        antecedent_score = 28
    elif antecedent_3 >= 40 or antecedent_7 >= 80:
        antecedent_score = 22
    elif antecedent_3 >= 20 or antecedent_7 >= 45:
        antecedent_score = 12
    elif antecedent_3 >= 10 or antecedent_7 >= 25:
        antecedent_score = 6
    else:
        antecedent_score = 0

    if discharge < 20:
        discharge_score = 5
    elif discharge < 100:
        discharge_score = 16
    elif discharge < 300:
        discharge_score = 30
    else:
        discharge_score = 45

    ratio_score = 0
    if discharge_max and discharge_mean:
        ratio = discharge_max / max(1.0, discharge_mean)
        if ratio >= 2.2:
            ratio_score = 14
        elif ratio >= 1.7:
            ratio_score = 10
        elif ratio >= 1.3:
            ratio_score = 6

    weather_score = 12 if weather_code in HEAVY_WEATHER_CODES else 0

    if wind >= 70:
        wind_score = 10
    elif wind >= 45:
        wind_score = 7
    elif wind >= 25:
        wind_score = 4
    else:
        wind_score = 0

    total = min(100, precip_score + antecedent_score + discharge_score + ratio_score + weather_score + wind_score)

    if total < 30:
        level = "Low"
    elif total < 55:
        level = "Moderate"
    elif total < 75:
        level = "High"
    elif total < 90:
        level = "Very High"
    else:
        level = "Severe"

    return {
        "score": total,
        "level": level,
        "components": {
            "precipitation": precip_score,
            "antecedent_precipitation": antecedent_score,
            "river_discharge": discharge_score,
            "discharge_variability": ratio_score,
            "weather_severity": weather_score,
            "wind": wind_score,
        },
    }


async def _geocode_location(client: httpx.AsyncClient, location: str) -> Dict[str, Any]:
    fallback = await client.get(
        NOMINATIM_SEARCH_URL,
        params={
            "q": location,
            "format": "jsonv2",
            "limit": 1,
            "addressdetails": 1,
        },
        headers={"User-Agent": "weatherapp/1.0"},
        timeout=20.0,
    )
    fallback.raise_for_status()
    nominatim_results = fallback.json() or []
    if not nominatim_results:
        response = await client.get(
            OPEN_METEO_GEOCODE_URL,
            params={
                "name": location.strip(),
                "count": 1,
                "language": "en",
                "format": "json",
            },
            timeout=20.0,
        )
        response.raise_for_status()
        data = response.json()
        results = data.get("results") or []
        if not results:
            return {"ok": False, "message": "Location not found."}

        top = results[0]
        return {
            "ok": True,
            "name": top.get("name"),
            "country": top.get("country"),
            "latitude": top.get("latitude"),
            "longitude": top.get("longitude"),
            "timezone": top.get("timezone"),
        }

    top = nominatim_results[0]
    address_data = top.get("address") or {}
    display_name = top.get("display_name") or location

    return {
        "ok": True,
        "name": address_data.get("city")
        or address_data.get("town")
        or address_data.get("village")
        or address_data.get("county")
        or display_name,
        "country": address_data.get("country") or "Unknown",
        "latitude": float(top.get("lat")),
        "longitude": float(top.get("lon")),
        "timezone": None,
    }


async def _fetch_weather(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    target_date: date,
    timezone: str | None,
) -> Dict[str, Any]:
    response = await client.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,wind_speed_10m_max",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
            "timezone": timezone or "auto",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    return _parse_weather_payload(data, target_date)


async def _fetch_weather_daily_for_mode(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    target_date: date,
    timezone: str | None,
    mode: str,
) -> Dict[str, Any]:
    start_date = target_date - timedelta(days=6) if mode == "historical" else target_date
    endpoint = OPEN_METEO_ARCHIVE_URL if mode == "historical" else OPEN_METEO_FORECAST_URL
    response = await client.get(
        endpoint,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "precipitation_sum,weather_code,wind_speed_10m_max",
            "start_date": start_date.isoformat(),
            "end_date": target_date.isoformat(),
            "timezone": timezone or "auto",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    data = response.json()
    parsed = _parse_daily_values(
        data,
        target_date,
        ["precipitation_sum", "weather_code", "wind_speed_10m_max"],
    )
    if not parsed.get("ok"):
        return parsed

    daily = data.get("daily") or {}
    time_list = daily.get("time") or []
    precip_list = daily.get("precipitation_sum") or []
    target = target_date.isoformat()

    if target in time_list:
        index = time_list.index(target)
        start_3 = max(0, index - 2)
        start_7 = max(0, index - 6)

        precip_3 = [value for value in precip_list[start_3 : index + 1] if isinstance(value, (int, float))]
        precip_7 = [value for value in precip_list[start_7 : index + 1] if isinstance(value, (int, float))]

        parsed["antecedent_precip_3day_mm"] = round(sum(precip_3), 2)
        parsed["antecedent_precip_7day_mm"] = round(sum(precip_7), 2)
    else:
        parsed["antecedent_precip_3day_mm"] = None
        parsed["antecedent_precip_7day_mm"] = None

    return parsed


async def _fetch_flood_daily(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    target_date: date,
) -> Dict[str, Any]:
    response = await client.get(
        OPEN_METEO_FLOOD_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "river_discharge,river_discharge_mean,river_discharge_max",
            "start_date": target_date.isoformat(),
            "end_date": target_date.isoformat(),
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return _parse_daily_values(
        response.json(),
        target_date,
        ["river_discharge", "river_discharge_mean", "river_discharge_max"],
    )


async def _fetch_weather_daily_series(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
    timezone: str | None,
) -> Dict[str, Any]:
    response = await client.get(
        OPEN_METEO_FORECAST_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "precipitation_sum,weather_code,wind_speed_10m_max",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "timezone": timezone or "auto",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return _parse_daily_series(
        response.json(),
        ["precipitation_sum", "weather_code", "wind_speed_10m_max"],
    )


async def _fetch_flood_daily_series(
    client: httpx.AsyncClient,
    latitude: float,
    longitude: float,
    start_date: date,
    end_date: date,
) -> Dict[str, Any]:
    response = await client.get(
        OPEN_METEO_FLOOD_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "daily": "river_discharge,river_discharge_mean,river_discharge_max",
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
        timeout=20.0,
    )
    response.raise_for_status()
    return _parse_daily_series(
        response.json(),
        ["river_discharge", "river_discharge_mean", "river_discharge_max"],
    )


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/flood-risk", response_class=HTMLResponse)
async def flood_risk_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("flood.html", {"request": request})


@app.get("/social", response_class=HTMLResponse)
async def social_page(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("social.html", {"request": request, "tabs": SOCIAL_TABS})


@app.get("/api/social/posts")
async def get_social_posts(tab: str | None = None) -> JSONResponse:
    if tab:
        normalized_tab = tab.strip().title()
        if normalized_tab not in SOCIAL_TABS:
            return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)
        return JSONResponse({"ok": True, "tab": normalized_tab, "posts": _load_social_posts(normalized_tab)})

    tabs_payload: Dict[str, list[Dict[str, Any]]] = {}
    for tab_name in SOCIAL_TABS:
        tabs_payload[tab_name] = _load_social_posts(tab_name)

    return JSONResponse({"ok": True, "tabs": tabs_payload})


@app.post("/api/social/posts")
async def create_social_post(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid JSON body."}, status_code=400)

    tab_raw = str(payload.get("tab") or "").strip().title()
    message = str(payload.get("message") or "").strip()
    created_at_raw = str(payload.get("created_at") or "").strip()

    if tab_raw not in SOCIAL_TABS:
        return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)

    if not message:
        return JSONResponse({"ok": False, "message": "Message cannot be empty."}, status_code=400)

    if created_at_raw:
        try:
            datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return JSONResponse({"ok": False, "message": "created_at must be ISO 8601 format."}, status_code=400)

    created_at = created_at_raw or (datetime.utcnow().isoformat(timespec="seconds") + "Z")

    with _db_connect() as conn:
        cursor = conn.execute(
            "INSERT INTO social_posts(tab, message, created_at) VALUES(?, ?, ?)",
            (tab_raw, message, created_at),
        )
        post_id = int(cursor.lastrowid)

    post = {
        "id": post_id,
        "message": message,
        "created_at": created_at,
        "likes": 0,
        "replies": [],
    }

    return JSONResponse({"ok": True, "tab": tab_raw, "post": post, "posts": _load_social_posts(tab_raw)})


@app.post("/api/social/posts/update-time")
async def update_social_post_time(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid JSON body."}, status_code=400)

    tab_raw = str(payload.get("tab") or "").strip().title()
    post_id = payload.get("id")
    created_at = str(payload.get("created_at") or "").strip()

    if tab_raw not in SOCIAL_TABS:
        return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)

    if not isinstance(post_id, int):
        return JSONResponse({"ok": False, "message": "Post id must be an integer."}, status_code=400)

    if not created_at:
        return JSONResponse({"ok": False, "message": "created_at is required."}, status_code=400)

    try:
        datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return JSONResponse({"ok": False, "message": "created_at must be ISO 8601 format."}, status_code=400)

    with _db_connect() as conn:
        updated = conn.execute(
            "UPDATE social_posts SET created_at = ? WHERE id = ? AND tab = ?",
            (created_at, post_id, tab_raw),
        )

    if updated.rowcount:
        posts = _load_social_posts(tab_raw)
        post = next((item for item in posts if item.get("id") == post_id), None)
        return JSONResponse({"ok": True, "tab": tab_raw, "post": post, "posts": posts})

    return JSONResponse({"ok": False, "message": "Post not found."}, status_code=404)


@app.post("/api/social/replies")
async def create_social_reply(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid JSON body."}, status_code=400)

    tab_raw = str(payload.get("tab") or "").strip().title()
    message = str(payload.get("message") or "").strip()
    created_at_raw = str(payload.get("created_at") or "").strip()
    post_id = payload.get("post_id")

    if tab_raw not in SOCIAL_TABS:
        return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)

    if not isinstance(post_id, int):
        return JSONResponse({"ok": False, "message": "post_id must be an integer."}, status_code=400)

    if not message:
        return JSONResponse({"ok": False, "message": "Reply message cannot be empty."}, status_code=400)

    if created_at_raw:
        try:
            datetime.fromisoformat(created_at_raw.replace("Z", "+00:00"))
        except ValueError:
            return JSONResponse({"ok": False, "message": "created_at must be ISO 8601 format."}, status_code=400)

    created_at = created_at_raw or (datetime.utcnow().isoformat(timespec="seconds") + "Z")

    with _db_connect() as conn:
        post_exists = conn.execute(
            "SELECT id FROM social_posts WHERE id = ? AND tab = ?",
            (post_id, tab_raw),
        ).fetchone()

        if not post_exists:
            return JSONResponse({"ok": False, "message": "Post not found."}, status_code=404)

        cursor = conn.execute(
            "INSERT INTO social_replies(post_id, message, created_at) VALUES(?, ?, ?)",
            (post_id, message, created_at),
        )
        reply_id = int(cursor.lastrowid)

    reply = {
        "id": reply_id,
        "message": message,
        "created_at": created_at,
        "likes": 0,
    }

    posts = _load_social_posts(tab_raw)
    post = next((item for item in posts if item.get("id") == post_id), None)
    return JSONResponse({"ok": True, "tab": tab_raw, "post": post, "reply": reply})


@app.post("/api/social/posts/like")
async def like_social_post(request: Request) -> JSONResponse:
    _init_social_db()

    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid JSON body."}, status_code=400)

    tab_raw = str(payload.get("tab") or "").strip().title()
    post_id = payload.get("post_id")

    if tab_raw not in SOCIAL_TABS:
        return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)

    if not isinstance(post_id, int):
        return JSONResponse({"ok": False, "message": "post_id must be an integer."}, status_code=400)

    user_id, should_set_cookie = _resolve_social_user_id(request, str(payload.get("client_id") or "").strip())
    now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"

    with _db_connect() as conn:
        post_row = conn.execute(
            "SELECT id, likes FROM social_posts WHERE id = ? AND tab = ?",
            (post_id, tab_raw),
        ).fetchone()
        if not post_row:
            return JSONResponse({"ok": False, "message": "Post not found."}, status_code=404)

        try:
            conn.execute(
                """
                INSERT INTO social_post_likes(post_id, user_id, created_at)
                VALUES(?, ?, ?)
                """,
                (post_id, user_id, now_iso),
            )
        except sqlite3.IntegrityError:
            response = JSONResponse(
                {
                    "ok": False,
                    "tab": tab_raw,
                    "post_id": post_id,
                    "likes": int(post_row["likes"] or 0),
                    "message": "You already liked this comment.",
                },
                status_code=409,
            )
            if should_set_cookie:
                response.set_cookie(
                    key="social_user_id",
                    value=user_id,
                    max_age=31536000,
                    httponly=True,
                    samesite="lax",
                )
            return response

        conn.execute(
            "UPDATE social_posts SET likes = likes + 1 WHERE id = ? AND tab = ?",
            (post_id, tab_raw),
        )

        likes_row = conn.execute(
            "SELECT likes FROM social_posts WHERE id = ? AND tab = ?",
            (post_id, tab_raw),
        ).fetchone()

    likes = int(likes_row["likes"]) if likes_row else 0
    response = JSONResponse({"ok": True, "tab": tab_raw, "post_id": post_id, "likes": likes, "posts": _load_social_posts(tab_raw)})
    if should_set_cookie:
        response.set_cookie(
            key="social_user_id",
            value=user_id,
            max_age=31536000,
            httponly=True,
            samesite="lax",
        )
    return response


@app.post("/api/social/replies/like")
async def like_social_reply(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid JSON body."}, status_code=400)

    tab_raw = str(payload.get("tab") or "").strip().title()
    post_id = payload.get("post_id")
    reply_id = payload.get("reply_id")

    if tab_raw not in SOCIAL_TABS:
        return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)

    if not isinstance(post_id, int):
        return JSONResponse({"ok": False, "message": "post_id must be an integer."}, status_code=400)

    if not isinstance(reply_id, int):
        return JSONResponse({"ok": False, "message": "reply_id must be an integer."}, status_code=400)

    with _db_connect() as conn:
        updated = conn.execute(
            """
            UPDATE social_replies
            SET likes = likes + 1
            WHERE id = ?
              AND post_id = ?
              AND EXISTS (
                SELECT 1
                FROM social_posts p
                WHERE p.id = social_replies.post_id AND p.tab = ?
              )
            """,
            (reply_id, post_id, tab_raw),
        )
        if not updated.rowcount:
            return JSONResponse({"ok": False, "message": "Reply not found."}, status_code=404)

        likes_row = conn.execute(
            "SELECT likes FROM social_replies WHERE id = ? AND post_id = ?",
            (reply_id, post_id),
        ).fetchone()

    likes = int(likes_row["likes"]) if likes_row else 0
    return JSONResponse(
        {
            "ok": True,
            "tab": tab_raw,
            "post_id": post_id,
            "reply_id": reply_id,
            "likes": likes,
            "posts": _load_social_posts(tab_raw),
        }
    )


@app.delete("/api/social/posts")
async def delete_social_post(tab: str, post_id: int) -> JSONResponse:
    normalized_tab = tab.strip().title()
    if normalized_tab not in SOCIAL_TABS:
        return JSONResponse({"ok": False, "message": "Invalid tab."}, status_code=400)

    posts_before = _load_social_posts(normalized_tab)
    deleted = next((item for item in posts_before if item.get("id") == post_id), None)
    if not deleted:
        return JSONResponse({"ok": False, "message": "Post not found."}, status_code=404)

    with _db_connect() as conn:
        conn.execute(
            "DELETE FROM social_posts WHERE id = ? AND tab = ?",
            (post_id, normalized_tab),
        )

    return JSONResponse({"ok": True, "tab": normalized_tab, "deleted": deleted, "posts": _load_social_posts(normalized_tab)})


@app.post("/api/weather")
async def weather(location: str = Form(...), date_str: str = Form(...)) -> JSONResponse:
    try:
        target_date = date.fromisoformat(date_str)
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid date format."}, status_code=400)

    async with httpx.AsyncClient() as client:
        geo = await _geocode_location(client, location.strip())
        if not geo.get("ok"):
            return JSONResponse({"ok": False, "message": geo.get("message")}, status_code=404)

        weather_data = await _fetch_weather(
            client,
            geo["latitude"],
            geo["longitude"],
            target_date,
            geo.get("timezone"),
        )
        if not weather_data.get("ok"):
            return JSONResponse({"ok": False, "message": weather_data.get("message")}, status_code=404)

        payload = {
            "ok": True,
            "location": {
                "name": geo.get("name"),
                "country": geo.get("country"),
                "latitude": geo.get("latitude"),
                "longitude": geo.get("longitude"),
            },
            "weather": weather_data,
        }
        return JSONResponse(payload)


@app.post("/api/assistant")
async def assistant(request: Request) -> JSONResponse:
    try:
        payload = await request.json()
    except ValueError:
        return JSONResponse({"ok": False, "message": "Invalid JSON body."}, status_code=400)

    message = str(payload.get("message") or "").strip()
    if not message:
        return JSONResponse({"ok": False, "message": "Message cannot be empty."}, status_code=400)

    if len(message) > 2000:
        return JSONResponse({"ok": False, "message": "Message is too long. Keep it under 2000 characters."}, status_code=400)

    reply = await _generate_assistant_reply(message)
    return JSONResponse({"ok": True, "reply": reply})


@app.post("/api/flood-risk")
async def flood_risk(
    address: str = Form(...),
    mode: str = Form(...),
    date_str: str | None = Form(default=None),
) -> JSONResponse:
    selected_mode = (mode or "").strip().lower()
    if selected_mode not in {"historical", "forecast"}:
        return JSONResponse({"ok": False, "message": "Mode must be historical or forecast."}, status_code=400)

    if selected_mode == "historical":
        if not date_str:
            return JSONResponse({"ok": False, "message": "Historical date is required."}, status_code=400)
        try:
            target_date = date.fromisoformat(date_str)
        except ValueError:
            return JSONResponse({"ok": False, "message": "Invalid historical date format."}, status_code=400)
        if target_date > date.today():
            return JSONResponse(
                {"ok": False, "message": "Historical date cannot be in the future."},
                status_code=400,
            )
    else:
        target_date = date.today()

    try:
        async with httpx.AsyncClient() as client:
            geo = await _geocode_location(client, address.strip())
            if not geo.get("ok"):
                return JSONResponse({"ok": False, "message": geo.get("message")}, status_code=404)

            if selected_mode == "forecast":
                end_date = target_date + timedelta(days=6)
                weather_series = await _fetch_weather_daily_series(
                    client,
                    geo["latitude"],
                    geo["longitude"],
                    target_date,
                    end_date,
                    geo.get("timezone"),
                )
                if not weather_series.get("ok"):
                    return JSONResponse({"ok": False, "message": weather_series.get("message")}, status_code=404)

                flood_series = await _fetch_flood_daily_series(
                    client,
                    geo["latitude"],
                    geo["longitude"],
                    target_date,
                    end_date,
                )
                if not flood_series.get("ok"):
                    return JSONResponse({"ok": False, "message": flood_series.get("message")}, status_code=404)

                flood_by_date = {entry.get("date"): entry for entry in flood_series.get("days", [])}
                precip_history: list[float] = []
                forecast_7days: list[Dict[str, Any]] = []

                for weather_day in weather_series.get("days", []):
                    day_date = weather_day.get("date")
                    flood_day = flood_by_date.get(day_date, {})
                    precipitation_value = weather_day.get("precipitation_sum")
                    precipitation_numeric = (
                        precipitation_value if isinstance(precipitation_value, (int, float)) else 0.0
                    )
                    precip_history.append(precipitation_numeric)

                    antecedent_3 = round(sum(precip_history[-3:]), 2)
                    antecedent_7 = round(sum(precip_history[-7:]), 2)

                    day_risk = _risk_from_inputs(
                        precipitation_mm=precipitation_value,
                        antecedent_precip_3day_mm=antecedent_3,
                        antecedent_precip_7day_mm=antecedent_7,
                        river_discharge=flood_day.get("river_discharge"),
                        river_discharge_mean=flood_day.get("river_discharge_mean"),
                        river_discharge_max=flood_day.get("river_discharge_max"),
                        weather_code=weather_day.get("weather_code"),
                        wind_speed_max_kmh=weather_day.get("wind_speed_10m_max"),
                    )

                    forecast_7days.append(
                        {
                            "date": day_date,
                            "weather": {
                                "precipitation_mm": precipitation_value,
                                "antecedent_precip_3day_mm": antecedent_3,
                                "antecedent_precip_7day_mm": antecedent_7,
                                "weather_code": weather_day.get("weather_code"),
                                "wind_speed_max_kmh": weather_day.get("wind_speed_10m_max"),
                            },
                            "flood": {
                                "river_discharge_m3s": flood_day.get("river_discharge"),
                                "river_discharge_mean_m3s": flood_day.get("river_discharge_mean"),
                                "river_discharge_max_m3s": flood_day.get("river_discharge_max"),
                            },
                            "risk": day_risk,
                        }
                    )

                if not forecast_7days:
                    return JSONResponse(
                        {"ok": False, "message": "No forecast data available for this location."},
                        status_code=404,
                    )

                water_proximity = await _safe_fetch_water_proximity(client, geo["latitude"], geo["longitude"])
                highest_risk_day = max(
                    forecast_7days,
                    key=lambda day: (day.get("risk") or {}).get("score", 0),
                )
                highest_risk = highest_risk_day.get("risk") or {}
                evacuation_routes: list[Dict[str, Any]] = []
                if _is_high_risk(highest_risk.get("level"), highest_risk.get("score")):
                    evacuation_routes = await _safe_fetch_evacuation_routes(client, geo["latitude"], geo["longitude"])

                first_day = forecast_7days[0]
                return JSONResponse(
                    {
                        "ok": True,
                        "mode": selected_mode,
                        "location": {
                            "name": geo.get("name"),
                            "country": geo.get("country"),
                            "latitude": geo.get("latitude"),
                            "longitude": geo.get("longitude"),
                        },
                        "date": first_day.get("date"),
                        "weather": first_day.get("weather"),
                        "flood": first_day.get("flood"),
                        "risk": first_day.get("risk"),
                        "water_proximity": water_proximity,
                        "evacuation_routes": evacuation_routes,
                        "evacuation_trigger": {
                            "high_risk_detected": _is_high_risk(highest_risk.get("level"), highest_risk.get("score")),
                            "highest_risk_day": highest_risk_day.get("date"),
                            "highest_risk_level": highest_risk.get("level"),
                            "highest_risk_score": highest_risk.get("score"),
                        },
                        "forecast_7days": forecast_7days,
                    }
                )

            weather_daily = await _fetch_weather_daily_for_mode(
                client,
                geo["latitude"],
                geo["longitude"],
                target_date,
                geo.get("timezone"),
                selected_mode,
            )
            if not weather_daily.get("ok"):
                return JSONResponse({"ok": False, "message": weather_daily.get("message")}, status_code=404)

            flood_daily = await _fetch_flood_daily(
                client,
                geo["latitude"],
                geo["longitude"],
                target_date,
            )
            if not flood_daily.get("ok"):
                return JSONResponse({"ok": False, "message": flood_daily.get("message")}, status_code=404)

            risk = _risk_from_inputs(
                precipitation_mm=weather_daily.get("precipitation_sum"),
                antecedent_precip_3day_mm=weather_daily.get("antecedent_precip_3day_mm"),
                antecedent_precip_7day_mm=weather_daily.get("antecedent_precip_7day_mm"),
                river_discharge=flood_daily.get("river_discharge"),
                river_discharge_mean=flood_daily.get("river_discharge_mean"),
                river_discharge_max=flood_daily.get("river_discharge_max"),
                weather_code=weather_daily.get("weather_code"),
                wind_speed_max_kmh=weather_daily.get("wind_speed_10m_max"),
            )

            water_proximity = await _safe_fetch_water_proximity(client, geo["latitude"], geo["longitude"])
            evacuation_routes: list[Dict[str, Any]] = []
            if _is_high_risk(risk.get("level"), risk.get("score")):
                evacuation_routes = await _safe_fetch_evacuation_routes(client, geo["latitude"], geo["longitude"])

            return JSONResponse(
                {
                    "ok": True,
                    "mode": selected_mode,
                    "location": {
                        "name": geo.get("name"),
                        "country": geo.get("country"),
                        "latitude": geo.get("latitude"),
                        "longitude": geo.get("longitude"),
                    },
                    "date": target_date.isoformat(),
                    "weather": {
                        "precipitation_mm": weather_daily.get("precipitation_sum"),
                        "antecedent_precip_3day_mm": weather_daily.get("antecedent_precip_3day_mm"),
                        "antecedent_precip_7day_mm": weather_daily.get("antecedent_precip_7day_mm"),
                        "weather_code": weather_daily.get("weather_code"),
                        "wind_speed_max_kmh": weather_daily.get("wind_speed_10m_max"),
                    },
                    "flood": {
                        "river_discharge_m3s": flood_daily.get("river_discharge"),
                        "river_discharge_mean_m3s": flood_daily.get("river_discharge_mean"),
                        "river_discharge_max_m3s": flood_daily.get("river_discharge_max"),
                    },
                    "risk": risk,
                    "water_proximity": water_proximity,
                    "evacuation_routes": evacuation_routes,
                    "evacuation_trigger": {
                        "high_risk_detected": _is_high_risk(risk.get("level"), risk.get("score")),
                        "highest_risk_day": target_date.isoformat(),
                        "highest_risk_level": risk.get("level"),
                        "highest_risk_score": risk.get("score"),
                    },
                }
            )
    except httpx.HTTPStatusError as exc:
        return JSONResponse(
            {
                "ok": False,
                "message": "Weather provider rejected the request for this date/address. Try a different date.",
                "details": str(exc),
            },
            status_code=502,
        )
    except httpx.RequestError:
        return JSONResponse(
            {"ok": False, "message": "Could not reach weather services. Please try again."},
            status_code=503,
        )
