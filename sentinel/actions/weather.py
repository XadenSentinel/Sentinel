"""Météo via Open-Meteo (gratuit, sans clé d'API). Ville réglable dans les paramètres."""
from __future__ import annotations

import json
import logging
import time
import urllib.parse
import urllib.request

from ..nlu import normalize
from ..replies import R, join

log = logging.getLogger("sentinel.weather")

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
CACHE_SECONDS = 600

# Codes météo WMO -> texte français (utilisable au milieu d'une phrase)
WMO = {
    0: "ciel dégagé", 1: "plutôt dégagé", 2: "partiellement nuageux", 3: "couvert",
    45: "brouillard", 48: "brouillard givrant",
    51: "bruine légère", 53: "bruine", 55: "forte bruine", 56: "bruine verglaçante", 57: "bruine verglaçante",
    61: "pluie faible", 63: "pluie", 65: "forte pluie", 66: "pluie verglaçante", 67: "pluie verglaçante",
    71: "neige faible", 73: "neige", 75: "forte neige", 77: "grains de neige",
    80: "averses faibles", 81: "averses", 82: "fortes averses", 85: "averses de neige", 86: "fortes averses de neige",
    95: "orage", 96: "orage avec grêle", 99: "orage avec forte grêle",
}


def describe_code(code: int) -> str:
    return WMO.get(int(code), "temps variable")


def symbol(code: int) -> str:
    """Petit pictogramme pour le HUD."""
    code = int(code)
    if code in (0, 1):
        return "☀"
    if code == 2:
        return "⛅"
    if code == 3:
        return "☁"
    if code in (45, 48):
        return "≋"
    if code in (71, 73, 75, 77, 85, 86):
        return "❄"
    if code >= 95:
        return "⚡"
    return "☂"


class WeatherError(Exception):
    def __init__(self, kind: str, city: str = "") -> None:
        super().__init__(kind)
        self.kind, self.city = kind, city


def _deg(n: int) -> str:
    return f"moins {abs(n)}" if n < 0 else str(n)


class Weather:
    def __init__(self, cfg) -> None:
        self.cfg = cfg
        self._geo: dict[str, tuple[float, float, str]] = {}
        self._cache: dict[str, tuple[float, dict]] = {}

    # ------------------------------------------------------------------ réseau
    @staticmethod
    def _get_json(url: str, params: dict) -> dict:
        req = urllib.request.Request(url + "?" + urllib.parse.urlencode(params),
                                     headers={"User-Agent": "Sentinel-assistant/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def _locate(self, city: str) -> tuple[float, float, str]:
        key = normalize(city)
        if key in self._geo:
            return self._geo[key]
        try:
            data = self._get_json(GEO_URL, {"name": city, "count": 1, "language": "fr", "format": "json"})
        except Exception as exc:
            raise WeatherError("network") from exc
        results = data.get("results") or []
        if not results:
            raise WeatherError("city_unknown", city)
        r = results[0]
        self._geo[key] = (float(r["latitude"]), float(r["longitude"]), r.get("name") or city)
        return self._geo[key]

    # ------------------------------------------------------------------ données
    def fetch(self, city: str | None = None, force: bool = False) -> dict:
        city = (city or self.cfg["weather_city"] or "").strip()
        if not city:
            raise WeatherError("no_city")
        key = normalize(city)
        cached = self._cache.get(key)
        if cached and not force and time.time() - cached[0] < CACHE_SECONDS:
            return cached[1]
        lat, lon, name = self._locate(city)
        try:
            raw = self._get_json(FORECAST_URL, {
                "latitude": lat, "longitude": lon, "timezone": "auto", "forecast_days": 2,
                "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
                "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            })
            data = self.parse(raw, name)
        except WeatherError:
            raise
        except Exception as exc:
            log.exception("météo indisponible")
            raise WeatherError("network") from exc
        self._cache[key] = (time.time(), data)
        return data

    @staticmethod
    def parse(raw: dict, city: str) -> dict:
        cur, day = raw["current"], raw["daily"]

        def d(field: str, i: int):
            values = day.get(field) or []
            return values[i] if len(values) > i else None

        def rnd(x):
            return None if x is None else int(round(x))

        return {
            "city": city,
            "temp": rnd(cur["temperature_2m"]), "feels": rnd(cur.get("apparent_temperature")),
            "code": int(cur["weather_code"]), "desc": describe_code(cur["weather_code"]),
            "wind": rnd(cur.get("wind_speed_10m")),
            "tmax": rnd(d("temperature_2m_max", 0)), "tmin": rnd(d("temperature_2m_min", 0)),
            "rain": rnd(d("precipitation_probability_max", 0)),
            "tomorrow": {
                "code": int(d("weather_code", 1) or 0), "desc": describe_code(d("weather_code", 1) or 0),
                "tmax": rnd(d("temperature_2m_max", 1)), "tmin": rnd(d("temperature_2m_min", 1)),
                "rain": rnd(d("precipitation_probability_max", 1)),
            },
        }

    # ------------------------------------------------------------ phrase parlée
    def answer(self, city: str | None = None, when: str = "today") -> str:
        try:
            data = self.fetch(city)
        except WeatherError as exc:
            if exc.kind == "no_city":
                return R(self.cfg, "weather_no_city")
            if exc.kind == "city_unknown":
                return R(self.cfg, "weather_city_unknown", ville=exc.city)
            return R(self.cfg, "weather_error")
        if when == "tomorrow":
            t = data["tomorrow"]
            msg = R(self.cfg, "weather_tomorrow", ville=data["city"], desc=t["desc"],
                    tmax=_deg(t["tmax"]) if t["tmax"] is not None else "?",
                    tmin=_deg(t["tmin"]) if t["tmin"] is not None else "?")
            rain = t["rain"]
        else:
            msg = R(self.cfg, "weather", ville=data["city"], temp=_deg(data["temp"]), desc=data["desc"],
                    tmax=_deg(data["tmax"]) if data["tmax"] is not None else "?",
                    tmin=_deg(data["tmin"]) if data["tmin"] is not None else "?")
            rain = data["rain"]
        if rain is not None and rain >= 40:
            msg = join(msg, R(self.cfg, "weather_rain", pluie=rain))
        return msg
