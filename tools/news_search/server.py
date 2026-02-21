import os
import logging
from datetime import datetime
from typing import Any, Dict, Optional
from dotenv import load_dotenv

load_dotenv()

import httpx
from fastmcp import FastMCP
from fastmcp.server.auth.providers.google import GoogleProvider
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware

# -----------------------------
# Logging
# -----------------------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("news-search-mcp")

# -----------------------------
# Configuration (ENV)
# -----------------------------
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "").strip()
if not NEWS_API_KEY:
    raise RuntimeError("NEWS_API_KEY is required (set env var).")

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
BASE_URL = os.getenv("BASE_URL", "http://localhost:7666").strip()

if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
    raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are required.")

# NewsAPI.org base URL
NEWS_API_BASE_URL = "https://newsapi.org/v2"

# GoogleProvider authentication
# jwt_signing_key is omitted: FastMCP derives a stable key from the Google Client Secret via PBKDF2
auth = GoogleProvider(
    client_id=GOOGLE_CLIENT_ID,
    client_secret=GOOGLE_CLIENT_SECRET,
    base_url=BASE_URL,
)

mcp = FastMCP(
    name="NewsSearchMCP",
    instructions=(
        "Search news articles using NewsAPI.org with Google OAuth2.0 authentication.\n"
        "Provides keyword search, top headlines, category filtering, and date range queries.\n"
        "Note: Free plan limited to 100 requests/day."
    ),
    auth=auth,
)

# -----------------------------
# Helpers
# -----------------------------


def parse_date(date_str: str) -> str:
    """
    Parse date string and return ISO format (YYYY-MM-DD).
    Accepts: YYYY-MM-DD, YYYY/MM/DD
    """
    try:
        # Try ISO format first
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # Try slash format
    try:
        dt = datetime.strptime(date_str, "%Y/%m/%d")
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass

    # If all fail, return as-is (NewsAPI will validate)
    return date_str


async def call_newsapi(
    endpoint: str,
    params: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Call NewsAPI.org with error handling.

    Args:
        endpoint: API endpoint (e.g., "everything", "top-headlines")
        params: Query parameters

    Returns:
        JSON response from NewsAPI

    Raises:
        Exception: On API errors (rate limit, invalid key, network issues)
    """
    url = f"{NEWS_API_BASE_URL}/{endpoint}"

    # Add API key to params
    params["apiKey"] = NEWS_API_KEY

    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            response = await client.get(url, params=params)
            response.raise_for_status()
            data = response.json()

            # Check NewsAPI status
            if data.get("status") == "error":
                error_code = data.get("code", "unknown")
                error_message = data.get("message", "Unknown error")
                raise Exception(f"NewsAPI error [{error_code}]: {error_message}")

            return data

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                raise Exception(
                    "Rate limit exceeded. NewsAPI free plan allows 100 requests/day. "
                    "Consider upgrading or implementing caching."
                )
            elif e.response.status_code == 401:
                raise Exception("Invalid NewsAPI key. Please check NEWS_API_KEY environment variable.")
            else:
                logger.error(f"NewsAPI HTTP error: {e.response.status_code} - {e.response.text}")
                raise Exception(f"NewsAPI HTTP error: {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error(f"NewsAPI request failed: {e}")
            raise Exception(f"NewsAPI request failed: {str(e)}")
        except Exception as e:
            logger.error(f"NewsAPI call failed: {e}")
            raise


# -----------------------------
# MCP Tools
# -----------------------------
@mcp.tool
async def search_news(
    query: str,
    language: str = "ja",
    sort_by: str = "publishedAt",
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Search news articles by keyword.

    Args:
        query: Search keywords (e.g., "人工知能", "気候変動")
        language: Language code (ja=Japanese, en=English, etc.)
        sort_by: Sort method - "publishedAt" (newest first), "relevancy", or "popularity"
        page_size: Number of results to return (1-100, default 20)

    Returns:
        Dictionary containing:
        - status: "ok" or "error"
        - totalResults: Total number of matching articles
        - articles: List of article objects with title, description, url, publishedAt, etc.

    Example:
        search_news("AI technology", language="en", page_size=10)
    """
    params = {
        "q": query,
        "language": language,
        "sortBy": sort_by,
        "pageSize": min(page_size, 100),
    }

    logger.info(f"Searching news: query='{query}', language={language}, sort_by={sort_by}")
    result = await call_newsapi("everything", params)

    return {
        "status": result.get("status"),
        "totalResults": result.get("totalResults", 0),
        "articles": result.get("articles", []),
    }


@mcp.tool
async def get_top_headlines(
    country: str = "jp",
    category: Optional[str] = None,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Get top news headlines from a country.

    Args:
        country: Country code (jp=Japan, us=USA, gb=UK, de=Germany, fr=France, etc.)
        category: Optional category - "business", "entertainment", "general",
                  "health", "science", "sports", "technology"
        page_size: Number of results to return (1-100, default 20)

    Returns:
        Dictionary containing:
        - status: "ok" or "error"
        - totalResults: Total number of matching articles
        - articles: List of article objects with title, description, url, publishedAt, etc.

    Example:
        get_top_headlines(country="us", category="technology", page_size=10)
    """
    params = {
        "country": country,
        "pageSize": min(page_size, 100),
    }

    if category:
        params["category"] = category

    logger.info(f"Getting top headlines: country={country}, category={category}")
    result = await call_newsapi("top-headlines", params)

    return {
        "status": result.get("status"),
        "totalResults": result.get("totalResults", 0),
        "articles": result.get("articles", []),
    }


@mcp.tool
async def search_news_by_date_range(
    query: str,
    from_date: str,
    to_date: str,
    language: str = "ja",
    sort_by: str = "publishedAt",
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Search news within a specific date range.

    Args:
        query: Search keywords
        from_date: Start date in YYYY-MM-DD format (e.g., "2024-01-01")
        to_date: End date in YYYY-MM-DD format (e.g., "2024-12-31")
        language: Language code (ja, en, etc.)
        sort_by: Sort method - "publishedAt", "relevancy", or "popularity"
        page_size: Number of results to return (1-100, default 20)

    Returns:
        Dictionary containing:
        - status: "ok" or "error"
        - totalResults: Total number of matching articles
        - articles: List of article objects with title, description, url, publishedAt, etc.

    Example:
        search_news_by_date_range("climate change", "2024-01-01", "2024-06-30", language="en")
    """
    params = {
        "q": query,
        "from": parse_date(from_date),
        "to": parse_date(to_date),
        "language": language,
        "sortBy": sort_by,
        "pageSize": min(page_size, 100),
    }

    logger.info(f"Searching news by date range: query='{query}', from={from_date}, to={to_date}")
    result = await call_newsapi("everything", params)

    return {
        "status": result.get("status"),
        "totalResults": result.get("totalResults", 0),
        "articles": result.get("articles", []),
    }


@mcp.tool
async def search_news_by_category(
    category: str,
    country: str = "jp",
    query: Optional[str] = None,
    page_size: int = 20,
) -> Dict[str, Any]:
    """
    Search news by category, optionally filtered by keyword.

    Args:
        category: Category - "business", "entertainment", "general",
                  "health", "science", "sports", "technology"
        country: Country code (jp, us, gb, etc.)
        query: Optional search keywords to filter within the category
        page_size: Number of results to return (1-100, default 20)

    Returns:
        Dictionary containing:
        - status: "ok" or "error"
        - totalResults: Total number of matching articles
        - articles: List of article objects with title, description, url, publishedAt, etc.

    Example:
        search_news_by_category("technology", country="us", query="artificial intelligence")
    """
    params = {
        "category": category,
        "country": country,
        "pageSize": min(page_size, 100),
    }

    if query:
        params["q"] = query

    logger.info(f"Searching news by category: category={category}, country={country}, query={query}")
    result = await call_newsapi("top-headlines", params)

    return {
        "status": result.get("status"),
        "totalResults": result.get("totalResults", 0),
        "articles": result.get("articles", []),
    }


# -----------------------------
# Run (Streamable HTTP)
# -----------------------------
if __name__ == "__main__":
    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "7666"))

    logger.info(f"Starting News Search MCP Server on {host}:{port}")
    logger.info("Google OAuth2.0 authentication enabled")
    logger.info("NewsAPI.org integration ready (free plan: 100 requests/day)")

    mcp.run(
        transport="streamable-http",
        host=host,
        port=port,
        path="/mcp",
        stateless_http=True,
        middleware=[
            Middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_methods=["*"],
                allow_headers=["*"],
            )
        ],
    )
