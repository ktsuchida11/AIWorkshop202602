import json
import os
import sys
import logging
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP, Context

import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# MCPサーバーの初期化
mcp = FastMCP("market-data")


def __get_indices_list_static() -> list[dict]:
    """
    静的なインデックスのリストを取得します。
    これは、実際のAPI呼び出しではなく、事前定義されたインデックスのリストを返します。

    Returns:
        list[dict]: インデックスのリスト。各インデックスは以下の情報を含む辞書です。
    """
    indices_list = [
        {
            "symbol": "^GSPC",
            "name": "S&P 500",
            "country": "United States",
            "category": "Equity Index",
            "type": "Index",
            "description": "Capitalization-weighted index of 500 leading U.S. companies."
        },
        {
            "symbol": "^DJI",
            "name": "Dow Jones Industrial Average",
            "country": "United States",
            "category": "Equity Index",
            "type": "Index",
            "description": "Price-weighted index of 30 large, publicly owned U.S. companies."
        },
        {
            "symbol": "^IXIC",
            "name": "NASDAQ Composite",
            "country": "United States",
            "category": "Equity Index",
            "type": "Index",
            "description": "Broad-based index of over 3,000 stocks listed on the NASDAQ exchange."
        },
        {
            "symbol": "^NYA",
            "name": "NYSE Composite Index",
            "country": "United States",
            "category": "Equity Index",
            "type": "Index",
            "description": "Market-cap weighted index of all common stocks listed on the NYSE."
        },
        {
            "symbol": "^XAX",
            "name": "NYSE American Composite Index",
            "country": "United States",
            "category": "Equity Index",
            "type": "Index",
            "description": "Index covering all securities listed on the NYSE American exchange."
        },
        {
            "symbol": "^BUK100P",
            "name": "FTSEurofirst 100 Price Index",
            "country": "Europe",
            "category": "Equity Index",
            "type": "Index",
            "description": "Price return index of the 100 largest pan-European blue-chip companies."
        },
        {
            "symbol": "^RUT",
            "name": "Russell 2000 Index",
            "country": "United States",
            "category": "Equity Index",
            "type": "Index",
            "description": "Index measuring the performance of the 2,000 smallest companies in the Russell 3000."
        },
        {
            "symbol": "^VIX",
            "name": "CBOE Volatility Index",
            "country": "United States",
            "category": "Volatility Index",
            "type": "Index",
            "description": "Market expectation of 30-day forward-looking volatility derived from S&P 500 option prices."
        },
        {
            "symbol": "^FTSE",
            "name": "FTSE 100",
            "country": "United Kingdom",
            "category": "Equity Index",
            "type": "Index",
            "description": "Capitalization-weighted index of the 100 largest companies on the London Stock Exchange."
        },
        {
            "symbol": "^GDAXI",
            "name": "DAX Performance-Index",
            "country": "Germany",
            "category": "Equity Index",
            "type": "Index",
            "description": "Blue-chip stock index consisting of the 40 major German companies trading on the Frankfurt Stock Exchange."
        },
        {
            "symbol": "^FCHI",
            "name": "CAC 40",
            "country": "France",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark French stock market index of 40 largest equities listed in Paris."
        },
        {
            "symbol": "^STOXX50E",
            "name": "EURO STOXX 50 Price Index",
            "country": "Eurozone",
            "category": "Equity Index",
            "type": "Index",
            "description": "Price index of 50 leading blue-chip stocks in the Eurozone."
        },
        {
            "symbol": "^N100",
            "name": "Euronext 100",
            "country": "Europe",
            "category": "Equity Index",
            "type": "Index",
            "description": "Index of 100 largest and most liquid stocks across the Euronext markets."
        },
        {
            "symbol": "^BFX",
            "name": "BEL 20",
            "country": "Belgium",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark of the 20 most capitalized and liquid Belgian stocks on Euronext Brussels."
        },
        {
            "symbol": "MOEX.ME",
            "name": "Moscow Exchange Index (MICEX-RTS)",
            "country": "Russia",
            "category": "Equity Index",
            "type": "Index",
            "description": "Composite index of the most liquid Russian stocks on the Moscow Exchange."
        },
        {
            "symbol": "^HSI",
            "name": "Hang Seng Index",
            "country": "Hong Kong",
            "category": "Equity Index",
            "type": "Index",
            "description": "Free-float adjusted market-cap weighted index of the largest companies on the Hong Kong Stock Exchange."
        },
        {
            "symbol": "^STI",
            "name": "Straits Times Index",
            "country": "Singapore",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark index of the top 30 companies listed on the Singapore Exchange."
        },
        {
            "symbol": "^AXJO",
            "name": "S&P/ASX 200",
            "country": "Australia",
            "category": "Equity Index",
            "type": "Index",
            "description": "Market-capitalization weighted and float-adjusted index of the 200 largest ASX-listed stocks."
        },
        {
            "symbol": "^AORD",
            "name": "All Ordinaries",
            "country": "Australia",
            "category": "Equity Index",
            "type": "Index",
            "description": "Index of the 500 largest companies listed on the Australian Securities Exchange."
        },
        {
            "symbol": "^BSESN",
            "name": "S&P BSE SENSEX",
            "country": "India",
            "category": "Equity Index",
            "type": "Index",
            "description": "Free-float market capitalization weighted index of 30 well-established and financially sound BSE stocks."
        },
        {
            "symbol": "^JKSE",
            "name": "IDX Composite",
            "country": "Indonesia",
            "category": "Equity Index",
            "type": "Index",
            "description": "Broad-based index of all stocks listed on the Indonesia Stock Exchange."
        },
        {
            "symbol": "^KLSE",
            "name": "FTSE Bursa Malaysia KLCI",
            "country": "Malaysia",
            "category": "Equity Index",
            "type": "Index",
            "description": "Capitalization-weighted index of the 30 largest companies on the Kuala Lumpur Stock Exchange."
        },
        {
            "symbol": "^NZ50",
            "name": "S&P/NZX 50 Index",
            "country": "New Zealand",
            "category": "Equity Index",
            "type": "Index",
            "description": "Free-float market capitalization index of the top 50 NZX-listed companies."
        },
        {
            "symbol": "^KS11",
            "name": "KOSPI Composite Index",
            "country": "South Korea",
            "category": "Equity Index",
            "type": "Index",
            "description": "Capitalization-weighted index of all common shares traded on the Korea Exchange."
        },
        {
            "symbol": "^TWII",
            "name": "TAIEX",
            "country": "Taiwan",
            "category": "Equity Index",
            "type": "Index",
            "description": "Price-weighted index of all listed common shares on the Taiwan Stock Exchange."
        },
        {
            "symbol": "^GSPTSE",
            "name": "S&P/TSX Composite",
            "country": "Canada",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark index of the largest companies on the Toronto Stock Exchange."
        },
        {
            "symbol": "^BVSP",
            "name": "IBOVESPA",
            "country": "Brazil",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark index of about 60 stocks that account for the majority of the trading on B3 (Brazil Stock Exchange)."
        },
        {
            "symbol": "^MXX",
            "name": "S&P/BMV IPC (Mexico)",
            "country": "Mexico",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark stock index of the Mexican Stock Exchange comprising 35 of the most liquid stocks."
        },
        {
            "symbol": "^IPSA",
            "name": "S&P IPSA",
            "country": "Chile",
            "category": "Equity Index",
            "type": "Index",
            "description": "Index of the 40 most traded stocks on the Santiago Stock Exchange."
        },
        {
            "symbol": "^MERV",
            "name": "MERVAL",
            "country": "Argentina",
            "category": "Equity Index",
            "type": "Index",
            "description": "Benchmark index of the Buenos Aires Stock Exchange comprising its most liquid stocks."
        },
        {
            "symbol": "^TA125.TA",
            "name": "TA-125 Index",
            "country": "Israel",
            "category": "Equity Index",
            "type": "Index",
            "description": "Market capitalization index of the 125 largest companies on the Tel Aviv Stock Exchange."
        },
        {
            "symbol": "^CASE30",
            "name": "EGX 30 Price Return Index",
            "country": "Egypt",
            "category": "Equity Index",
            "type": "Index",
            "description": "Price return index of the top 30 most active companies on the Egyptian Exchange."
        },
        {
            "symbol": "^JN0U.JO",
            "name": "FTSE/JSE Top 40 Index",
            "country": "South Africa",
            "category": "Equity Index",
            "type": "Index",
            "description": "Index of the 40 largest companies by market cap on the Johannesburg Stock Exchange."
        },
        {
            "symbol": "DX-Y.NYB",
            "name": "U.S. Dollar Index",
            "country": "United States",
            "category": "Currency Index",
            "type": "Index",
            "description": "Measures the value of the U.S. dollar relative to a basket of foreign currencies."
        },
        {
            "symbol": "^125904-USD-STRD",
            "name": "MSCI Europe",
            "country": "Europe",
            "category": "Equity Index",
            "type": "Index",
            "description": "Free-float adjusted market capitalization index of large- and mid-cap companies across 15 developed European markets."
        },
        {
            "symbol": "^XDB",
            "name": "British Pound Currency Index",
            "country": "United Kingdom",
            "category": "Currency Index",
            "type": "Index",
            "description": "Tracks performance of the British pound against a basket of global currencies."
        },
        {
            "symbol": "^XDE",
            "name": "Euro Currency Index",
            "country": "Eurozone",
            "category": "Currency Index",
            "type": "Index",
            "description": "Measures the strength of the euro relative to a basket of major world currencies."
        },
        {
            "symbol": "000001.SS",
            "name": "Shanghai Composite",
            "country": "China",
            "category": "Equity Index",
            "type": "Index",
            "description": "Capitalization-weighted index of all A-shares and B-shares listed on the Shanghai Stock Exchange."
        },
        {
            "symbol": "^N225",
            "name": "Nikkei 225",
            "country": "Japan",
            "category": "Equity Index",
            "type": "Index",
            "description": "Price-weighted index of 225 large, publicly owned Japanese companies traded on the Tokyo Stock Exchange."
        },
        {
            "symbol": "^XDN",
            "name": "Japanese Yen Currency Index",
            "country": "Japan",
            "category": "Currency Index",
            "type": "Index",
            "description": "Tracks the value of the Japanese yen against a basket of major international currencies."
        },
        {
            "symbol": "^XDA",
            "name": "Australian Dollar Currency Index",
            "country": "Australia",
            "category": "Currency Index",
            "type": "Index",
            "description": "Measures performance of the Australian dollar relative to a diversified basket of currencies."
        }

    ]

    return indices_list


@mcp.tool()
async def get_indices_list_yfinance(ctx: Context = None) -> str:
    """
    利用可能な商品（インデックス）のリストを取得します。
    必要なマーケットデータを取得するためのSymbolを検索するために使用します。
    ※ この関数は、S&P500やNASDAQなどのインデックスを取得します。
      get_time_series_data_yfinanceを利用するためのSymbolを取得するために使用します。

    戻り値:
       インデックスのリスト。(JSON形式)
        例:
        [
            {
                \"symbol\": index.symbol,
                \"name\": index.name,
                \"country\": index.country,
                \"type\": \"INDEX\", # 商品のタイプを\"INDEX\"に設定
                \"description\": index.isin
            },
        ]
    """
    try:
        await ctx.debug("Fetching indices list from static data...")
        logger.debug("Fetching indices list from static data...")
        results = __get_indices_list_static()

        if not results:
            await ctx.error("No indices found.")
            logger.error("No indices found.")
            return "No indices found."

        await ctx.debug(f"Fetched {len(results)} indices from static list.")
        logger.debug(f"Indices list: {results}")

        return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception as e:
        await ctx.error(f"Error fetching indices: {e}")
        logger.error(f"Error fetching indices: {e}")
        return []


@mcp.tool()
async def get_time_series_data_yfinance(
    symbol: str,
    interval: str = "1h",
    outputsize: int = 24,
    start_date: str = "",
    end_date: str = "",
    ctx: Context = None
) -> str:
    """
    S&P500やNASDAQなどのインデックス、商品市場、為替など指定されたシンボルとインターバルに基づいて、時系列データを取得します。
    * 石炭以外のマーケットデータを取得します。
    * 日足の場合は "1d"、時間足の場合は "1h" などを指定します。

    Args:
        symbol (str): データを取得する商品のシンボル。
        interval (str): データのインターバル デフォルト 1h（例: \"1m\", \"5m\", \"1h\",\"1d\"）。
        outputsize (int): 取得するデータポイントの数。
        start_date (str): データ取得の開始日（例: \"2023-01-01\"）。
        end_date (str): データ取得の終了日（例: \"2023-01-31\"）。

    Returns:
        時系列データのリスト。（JSON形式）
        例:
        {
            "meta": {
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "start_date": start_date,
                "end_date": end_date,
                "timezone": "Asia/Tokyo"
            },
            "values": [
                {
                    "timestamp": データポイントのタイムスタンプ,
                    "open": 始値,
                    "high": 高値,
                    "low": 安値,
                    "close": 終値,
                },
                ...
            ]
        }
    """
    try:

        results = {
            "meta": {
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "start_date": start_date,
                "end_date": end_date,
                "timezone": "Asia/Tokyo"
            },
            "values": []
        }

        if start_date and end_date:
            # 開始日と終了日が指定されている場合、期間を設定
            set_start_date = start_date
            set_end_date = end_date
        elif start_date:
            # 開始日のみ指定されている場合、終了日は現在の日付に設定
            set_start_date = start_date
            set_end_date = datetime.now().strftime("%Y-%m-%d")
        elif end_date:
            # 終了日のみ指定されている場合、開始日は1ヶ月前の日付に設定
            set_start_date = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
            set_end_date = end_date
        else:
            # 開始日と終了日が指定されていない場合、デフォルトの期間を設定 24時間分のデータを取得
            set_start_date = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
            set_end_date = (datetime.now() - timedelta(days=0)).strftime("%Y-%m-%d")

        # 時系列データを取得
        await ctx.info(f"Fetching time series data for symbol: {symbol}, interval: {interval}, "
                       f"outputsize: {outputsize}, start_date: {set_start_date}, end_date: {set_end_date}")
        logger.debug(f"Fetching time series data for symbol: {symbol}, interval: {interval}, "
                     f"outputsize: {outputsize}, start_date: {set_start_date}, end_date: {set_end_date}")

        time_series_data = yf.download(symbol, start=set_start_date, end=set_end_date, interval=interval, rounding=True)

        logger.debug(f"Time series data fetched successfully: {time_series_data}")
        records = []
        for dt, row in time_series_data.iterrows():
            # dt is the datetime index; if it's tz-aware, convert directly,
            # otherwise localize to UTC then convert to JST
            if dt.tzinfo is None:
                dt_jst = dt.tz_localize("UTC").tz_convert("Asia/Tokyo")
            else:
                dt_jst = dt.tz_convert("Asia/Tokyo")

            await ctx.debug(f"Datetime: {dt_jst}, Open: {row['Open']}, High: {row['High']}, Low: {row['Low']}, "
                            f"Close: {row['Close']}, Volume: {row['Volume']}")
            logger.debug(f"Datetime: {dt_jst}, Open: {row['Open'].iloc[-1]}, High: {row['High'].iloc[-1]}, "
                         f"Low: {row['Low'].iloc[-1]}, "
                         f"Close: {row['Close'].iloc[-1]}, Volume: {row['Volume'].iloc[-1]}")
            records.append({
                "datetime": dt_jst.strftime("%Y-%m-%d %H:%M:%S"),
                "open": row["Open"].iloc[-1],
                "high": row["High"].iloc[-1],
                "low": row["Low"].iloc[-1],
                "close": row["Close"].iloc[-1],
                "volume": row["Volume"].iloc[-1]
            })

        outputsize = len(records)
        df = pd.DataFrame(records)

        if df.empty:
            ctx.warning(f"No data found for symbol: {symbol} with interval: {interval}")
            logger.warning(f"No data found for symbol: {symbol} with interval: {interval}")
            return f"No data found for symbol: {symbol} with interval: {interval}"

        results = {
            "meta": {
                "symbol": symbol,
                "interval": interval,
                "outputsize": outputsize,
                "start_date": start_date,
                "end_date": end_date,
                "timezone": "Asia/Tokyo"
            },
            "values": df[["datetime", "open", "high", "low", "close", "volume"]].to_dict(orient="records")
        }

        ctx.debug(f"Fetched {len(results['values'])} data points for symbol: {symbol} with interval: {interval}")
        ctx.debug(f"Data range: {results['values']}")
        logger.debug(f"Fetched {len(results['values'])} data points for symbol: {symbol} with interval: {interval}")
        logger.debug(f"Data range: {results['values']}")
        return json.dumps(results, ensure_ascii=False, indent=2)
    except Exception as e:
        ctx.error(f"Error fetching time series data: {e}")
        logger.error(f"Error fetching time series data: {e}")
        return f"Error fetching time series data: {e}"

# --- ツール定義の終わり ---


# 単体テスト用の関数
def test():
    logger.info("単体テスト...")
    get_indices_list_yfinance()
    get_time_series_data_yfinance("^VIX", "1h", 24)


if __name__ == "__main__":

    try:
        mcp.run(transport="stdio")
    except Exception as e:
        logger.error(f"サーバー実行中にエラーが発生しました: {e}")
        sys.exit(1)
