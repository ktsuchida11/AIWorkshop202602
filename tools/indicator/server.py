import os
import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from dotenv import load_dotenv

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.jwt import JWTVerifier

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("econ-mcp")

load_dotenv()

# -----------------------------
# Configuration (ENV)
# -----------------------------
FMP_API_KEY = os.getenv("FMP_API_KEY", "").strip()
if not FMP_API_KEY:
    raise RuntimeError("FMP_API_KEY is required (set env var).")

# Primary (stable) endpoint (documented)
FMP_STABLE_URL = os.getenv(
    "FMP_STABLE_URL",
    "https://financialmodelingprep.com/stable/economic-calendar",
).strip()

# Fallback (legacy) endpoint (widely used in examples; keep as escape hatch)
FMP_LEGACY_URL = os.getenv(
    "FMP_LEGACY_URL",
    "https://financialmodelingprep.com/api/v3/economic_calendar",
).strip()

# JWT settings (as you indicated)
JWT_JWKS_URI = os.getenv("JWT_JWKS_URI", "").strip()
JWT_ISSUER = os.getenv("JWT_ISSUER", "").strip()
JWT_AUDIENCE = os.getenv("JWT_AUDIENCE", "").strip()

if not (JWT_JWKS_URI and JWT_ISSUER and JWT_AUDIENCE):
    raise RuntimeError("JWT_JWKS_URI / JWT_ISSUER / JWT_AUDIENCE are required.")

auth = JWTVerifier(
    jwks_uri=JWT_JWKS_URI,
    issuer=JWT_ISSUER,
    audience=JWT_AUDIENCE,
)

mcp = FastMCP(
    name="EconomicCalendarMCP",
    instructions=(
        "Fetch economic calendar events by date range and countries.\n"
        "Inputs: start_date, end_date, countries(optional).\n"
        "Note: No 'importance/impact' filtering is supported in this server."
    ),
    auth=auth,
)

# -----------------------------
# Helpers
# -----------------------------
def parse_yyyy_mm_dd(s: str) -> date:
    # strict ISO date (YYYY-MM-DD)
    return date.fromisoformat(s)

def parse_datetime_loose(s: str) -> datetime:
    """
    FMP may return 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM:SS' or ISO-like.
    Normalize to datetime for sorting.
    """
    s = (s or "").strip()
    if not s:
        # put empty timestamps at end
        return datetime.max
    # Try ISO first
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        pass
    # Try common patterns
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt
        except ValueError:
            continue
    # fallback: push to end
    return datetime.max

# Country normalization: accept "JP", "JPN", "Japan", "日本" etc.
COUNTRY_ALIASES: Dict[str, str] = {
    "JP": "Japan",
    "JPN": "Japan",
    "日本": "Japan",
    "JAPAN": "Japan",
    "US": "United States",
    "USA": "United States",
    "UNITED STATES": "United States",
    "米国": "United States",
    "GB": "United Kingdom",
    "UK": "United Kingdom",
    "UNITED KINGDOM": "United Kingdom",
    "DE": "Germany",
    "GERMANY": "Germany",
    "FR": "France",
    "FRANCE": "France",
    "CN": "China",
    "CHN": "China",
    "CHINA": "China",
    "AU": "Australia",
    "AUS": "Australia",
    "AUSTRALIA": "Australia",
    "CA": "Canada",
    "CAN": "Canada",
    "CANADA": "Canada",
}

def normalize_countries(countries: Optional[Sequence[str]]) -> Optional[List[str]]:
    if not countries:
        return None
    out: List[str] = []
    for c in countries:
        if not c:
            continue
        key = c.strip()
        if not key:
            continue
        alias_key = key.upper()
        out.append(COUNTRY_ALIASES.get(alias_key, key))
    # de-dup while preserving order
    seen = set()
    deduped = []
    for c in out:
        k = c.lower()
        if k in seen:
            continue
        seen.add(k)
        deduped.append(c)
    return deduped or None

def chunk_date_range(start: date, end: date, chunk_days: int = 31) -> List[Tuple[date, date]]:
    """
    Split [start, end] into <= chunk_days chunks (inclusive).
    """
    if end < start:
        raise ValueError("end_date must be >= start_date")
    chunks: List[Tuple[date, date]] = []
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur, nxt))
        cur = nxt + timedelta(days=1)
    return chunks

async def fetch_fmp_calendar(
    client: httpx.AsyncClient,
    base_url: str,
    start: date,
    end: date,
) -> List[Dict[str, Any]]:
    """
    Fetch events for a chunk. Use from/to/apikey as typical calendar query params.
    """
    params = {
        "from": start.isoformat(),
        "to": end.isoformat(),
        "apikey": FMP_API_KEY,
    }
    r = await client.get(base_url, params=params)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        raise ValueError(f"Unexpected response type: {type(data)}")
    # Ensure dict list
    out: List[Dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item)
    return out

async def fetch_events_with_fallback(start: date, end: date) -> List[Dict[str, Any]]:
    """
    Prefer stable endpoint, fallback to legacy if stable fails (compatibility).
    """
    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            return await fetch_fmp_calendar(client, FMP_STABLE_URL, start, end)
        except Exception as e:
            logger.warning("Stable endpoint failed; fallback to legacy. error=%s", repr(e))
            return await fetch_fmp_calendar(client, FMP_LEGACY_URL, start, end)

def project_event_fields(e: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a compact, MCP-friendly payload (JSON-serializable) and
    intentionally excludes any 'importance/impact' filtering logic.
    """
    # Common keys seen in economic calendar feeds
    keys = [
        "date",
        "country",
        "event",
        "currency",
        "actual",
        "forecast",
        "previous",
        "unit",
    ]
    out = {k: e.get(k) for k in keys if k in e or k == "date"}
    # Keep raw id fields if present (optional)
    for k in ("id", "updated", "created"):
        if k in e:
            out[k] = e.get(k)
    return out

# -----------------------------
# Tool
# -----------------------------
@mcp.tool
async def get_economic_events(
    start_date: str,
    end_date: str,
    countries: Optional[List[str]] = None,
    max_items: int = 5000,
) -> List[Dict[str, Any]]:
    """
    Get economic calendar events within [start_date, end_date], optionally filtered by countries.

    - start_date/end_date: "YYYY-MM-DD"
    - countries: examples ["Japan", "JP", "United States", "US"] (importance/impact is NOT supported)
    - max_items: safety cap
    """
    start = parse_yyyy_mm_dd(start_date)
    end = parse_yyyy_mm_dd(end_date)
    want_countries = normalize_countries(countries)

    chunks = chunk_date_range(start, end, chunk_days=31)

    all_events: List[Dict[str, Any]] = []
    # Fetch chunked to reduce failure risk on wide ranges
    for (cs, ce) in chunks:
        events = await fetch_events_with_fallback(cs, ce)
        all_events.extend(events)

    # Filter by country (case-insensitive)
    if want_countries:
        want = {c.lower() for c in want_countries}
        filtered = []
        for e in all_events:
            c = str(e.get("country", "")).strip().lower()
            # Some feeds may return full names while input is code; we normalized input to names,
            # but keep a second pass that also matches alias table values.
            if c in want:
                filtered.append(e)
        all_events = filtered

    # Sort by date/time if available
    all_events.sort(key=lambda e: parse_datetime_loose(str(e.get("date", ""))))

    # Safety cap + field projection
    compact = [project_event_fields(e) for e in all_events[: max_items or 5000]]
    return compact

# -----------------------------
# Run (Streamable HTTP)
# -----------------------------
if __name__ == "__main__":

    # Requirement: start with transport="streamable-http".
    # Some environments use transport="http" to mean Streamable HTTP.
    mcp.run(
            transport="streamable-http",
            host="0.0.0.0",
            port=5555,
            path="/mcp"
        )
