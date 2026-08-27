"""India-first weather: Celsius, IST, Indian city names."""

from __future__ import annotations

import re
from typing import Any

import requests

DEFAULT_PLACE = "New Delhi"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SEC = 8.0
INDIA_TZ = "Asia/Kolkata"

_ALIASES = {
    "delhi": "New Delhi",
    "new delhi": "New Delhi",
    "delhi ncr": "New Delhi",
    "delhi nc": "New Delhi",
    "delhi n c r": "New Delhi",
    "ncr": "New Delhi",
    "ncr delhi": "New Delhi",
    "dilli": "New Delhi",
    "india": "New Delhi",
    "दिल्ली": "New Delhi",
    "नई दिल्ली": "New Delhi",
    "mumbai": "Mumbai",
    "bombay": "Mumbai",
    "मुंबई": "Mumbai",
    "bengaluru": "Bengaluru",
    "bangalore": "Bengaluru",
    "बेंगलुरु": "Bengaluru",
    "बैंगलोर": "Bengaluru",
    "chennai": "Chennai",
    "madras": "Chennai",
    "चेन्नई": "Chennai",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "कोलकाता": "Kolkata",
    "hyderabad": "Hyderabad",
    "हैदराबाद": "Hyderabad",
    "pune": "Pune",
    "पुणे": "Pune",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
    "kanpur": "Kanpur",
    "nagpur": "Nagpur",
    "indore": "Indore",
    "bhopal": "Bhopal",
    "patna": "Patna",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "thiruvananthapuram": "Thiruvananthapuram",
    "trivandrum": "Thiruvananthapuram",
    "chandigarh": "Chandigarh",
    "gurugram": "Gurugram",
    "gurgaon": "Gurugram",
    "noida": "Noida",
    "ghaziabad": "Ghaziabad",
    "faridabad": "Faridabad",
    "surat": "Surat",
    "vadodara": "Vadodara",
    "baroda": "Vadodara",
    "visakhapatnam": "Visakhapatnam",
    "vizag": "Visakhapatnam",
    "coimbatore": "Coimbatore",
    "madurai": "Madurai",
    "mysore": "Mysuru",
    "mysuru": "Mysuru",
    "varanasi": "Varanasi",
    "banaras": "Varanasi",
    "amritsar": "Amritsar",
    "srinagar": "Srinagar",
    "guwahati": "Guwahati",
    "ranchi": "Ranchi",
    "raipur": "Raipur",
    "dehradun": "Dehradun",
    "shimla": "Shimla",
    "goa": "Panaji",
    "panaji": "Panaji",
    "pondicherry": "Puducherry",
    "puducherry": "Puducherry",
}

_WMO = {
    0: "clear skies",
    1: "mainly clear skies",
    2: "partly cloudy skies",
    3: "overcast skies",
    45: "fog",
    48: "fog",
    51: "light drizzle",
    53: "drizzle",
    55: "heavy drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow",
    80: "light showers",
    81: "showers",
    82: "heavy showers",
    85: "snow showers",
    86: "snow showers",
    95: "thunderstorms",
    96: "thunderstorms with hail",
    99: "thunderstorms with hail",
}


def normalize_place(raw: str) -> str:
    text = " ".join(raw.lower().split())
    text = text.replace(", india", "").replace(" india", "").strip(" ,")
    # STT: "Delhi NC" / "Delhi N.C.R."
    text = re.sub(r"\bn\.?\s*c\.?\s*r\.?\b", "ncr", text)
    text = re.sub(r"\bn\.?\s*c\.?\b", "nc", text)
    text = " ".join(text.split())
    return _ALIASES.get(text, raw.strip() or DEFAULT_PLACE)


def describe_code(code: int) -> str:
    return _WMO.get(int(code), "mixed conditions")


def _degrees(value: Any) -> int:
    return int(round(float(value)))


def _geocode(place: str) -> tuple[float, float, str] | None:
    params = {"name": place, "count": 5, "language": "en"}
    try:
        india = requests.get(
            GEOCODE_URL,
            params={**params, "country": "IN"},
            timeout=TIMEOUT_SEC,
        )
        india.raise_for_status()
        hits = (india.json() or {}).get("results") or []
        if not hits:
            world = requests.get(GEOCODE_URL, params=params, timeout=TIMEOUT_SEC)
            world.raise_for_status()
            hits = (world.json() or {}).get("results") or []
    except (requests.RequestException, ValueError, TypeError):
        return None
    if not hits:
        return None
    first = hits[0]
    try:
        lat = float(first["latitude"])
        lon = float(first["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    label = str(first.get("name") or place).strip() or place
    admin = str(first.get("admin1") or "").strip()
    if admin and admin.casefold() != label.casefold():
        label = f"{label}, {admin}"
    return lat, lon, label


def fetch_forecast(place: str = "") -> dict[str, Any]:
    """Current conditions plus today/tomorrow for an Indian city."""
    query = normalize_place(place or DEFAULT_PLACE)
    located = _geocode(query)
    if located is None:
        raise LookupError(f"I couldn't find {query}.")
    lat, lon, label = located
    response = requests.get(
        FORECAST_URL,
        params={
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,weather_code,relative_humidity_2m",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "timezone": INDIA_TZ,
            "forecast_days": 2,
        },
        timeout=TIMEOUT_SEC,
    )
    response.raise_for_status()
    payload = response.json()
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    highs = daily.get("temperature_2m_max") or []
    lows = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    return {
        "place": label,
        "temp_c": _degrees(current.get("temperature_2m")),
        "condition": describe_code(int(current.get("weather_code") or 0)),
        "humidity": int(current.get("relative_humidity_2m") or 0),
        "high_c": _degrees(highs[0]) if highs else None,
        "low_c": _degrees(lows[0]) if lows else None,
        "tomorrow_high_c": _degrees(highs[1]) if len(highs) > 1 else None,
        "tomorrow_low_c": _degrees(lows[1]) if len(lows) > 1 else None,
        "tomorrow_condition": describe_code(int(codes[1])) if len(codes) > 1 else "",
    }


def speak_forecast(data: dict[str, Any], language: str | None = None) -> str:
    from friday.language.bilingual import user_language

    lang = (language or user_language() or "en").split("-", 1)[0].lower()
    if lang == "hi":
        return _speak_forecast_hi(data)
    place = str(data.get("place") or DEFAULT_PLACE)
    temp = data.get("temp_c")
    condition = str(data.get("condition") or "mixed conditions")
    parts = [
        f"In {place} it is {temp} degrees Celsius with {condition}."
    ]
    high = data.get("high_c")
    low = data.get("low_c")
    if high is not None and low is not None:
        parts.append(f"Today's high is {high} and the low is {low}.")
    tomorrow_high = data.get("tomorrow_high_c")
    tomorrow_low = data.get("tomorrow_low_c")
    if tomorrow_high is not None and tomorrow_low is not None:
        extra = str(data.get("tomorrow_condition") or "").strip()
        if extra:
            parts.append(
                f"Tomorrow, {extra}, {tomorrow_high} high and {tomorrow_low} low."
            )
        else:
            parts.append(
                f"Tomorrow, {tomorrow_high} high and {tomorrow_low} low."
            )
    return " ".join(parts)


def _speak_forecast_hi(data: dict[str, Any]) -> str:
    place = str(data.get("place") or DEFAULT_PLACE)
    temp = data.get("temp_c")
    condition = str(data.get("condition") or "mixed conditions")
    parts = [
        f"{place} में अभी {temp} डिग्री सेल्सियस है, {condition}."
    ]
    high = data.get("high_c")
    low = data.get("low_c")
    if high is not None and low is not None:
        parts.append(f"आज अधिकतम {high} और न्यूनतम {low} है.")
    tomorrow_high = data.get("tomorrow_high_c")
    tomorrow_low = data.get("tomorrow_low_c")
    if tomorrow_high is not None and tomorrow_low is not None:
        extra = str(data.get("tomorrow_condition") or "").strip()
        if extra:
            parts.append(
                f"कल {extra}, अधिकतम {tomorrow_high} और न्यूनतम {tomorrow_low}."
            )
        else:
            parts.append(
                f"कल अधिकतम {tomorrow_high} और न्यूनतम {tomorrow_low}."
            )
    return " ".join(parts)
