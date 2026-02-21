
import asyncio
import logging

from langchain_openai import ChatOpenAI
from langchain_aws import ChatBedrock
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient 

from langgraph.checkpoint.memory import InMemorySaver

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ToolStrategy
from pydantic import BaseModel, Field
from typing import List, Optional, Literal

from lib.tools import init_local_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# モデルプロファイルの定義（OpenAI用）
# 構造化出力を有効にする例 defaultはFalse
custom_profile = {
    "structured_output": True,
    # ...
}


class SourceRef(BaseModel):
    doc_id: str = Field(..., description="RAGに登録されたドキュメントID")
    url: Optional[str] = None
    resource: Optional[str] = None  # "minutes" | "press"
    published_filename: Optional[str] = None


class MarketInstrument(BaseModel):
    name: str
    ticker: Optional[str] = None
    instrument_type: Optional[str] = None  # e.g., "JPY-Bond", "Equity", "FX"
    price: Optional[float] = None
    change_abs: Optional[float] = None
    change_pct: Optional[float] = None
    timestamp: Optional[str] = None  # ISO8601
    data_source: Optional[str] = None


class Finding(BaseModel):
    title: str
    detail: str
    severity: Optional[Literal["low","medium","high"]] = None
    confidence: Optional[float] = None  # 0..1


class MarketAnalysisReport(BaseModel):
    report_id: str
    meeting_date: Optional[str] = None  # 例: "2025-12-01"（会合日）
    created_at: str  # JST ISO8601 (必須)
    author: Optional[str] = None

    # High-level
    summary: str
    top_findings: List[Finding]

    # Quantitative snapshot
    market_snapshot: List[MarketInstrument]

    # Time-series/visuals: list of URLs or filepaths for charts
    charts: Optional[List[str]] = None

    # Recommendations / action items
    recommendations: Optional[List[str]] = None

    # Backing sources: BOJ doc ids, press, and external sources
    sources: List[SourceRef]

    # Raw extracted items for traceability (optional)
    raw_text_snippets: Optional[List[str]] = None

    # Confidence and notes on missing data or failures
    overall_confidence: Optional[float] = None
    notes: Optional[str] = None


# システムプロンプト
system_prompt = """
あなたの責務は日銀の金融政策決定会合があったときの金融マーケットの情報を調査して結果をファイル出力することです。
- 日本銀行の議事要旨と会見の内容を保存した内容を検索できます。
- 市場データツールを利用することで、過去のおよび現在の金融マーケット情報を取得できます。
- 必要な情報が集まったと判断したら調査は終了して下さい
- response_formatのMarketAnalysisReportに従い、マーケット分析レポートを作成してください。
  * Web検索が拒否された場合、Web検索を中止してレポート作成してください。
  * レポート保存を拒否された場合、レポート作成を中止し、内容をユーザーに直接伝えて下さい。
"""

# 2024年の日銀のレポート情報を取得してください。
# 2024年の12月のレポートの内容と、その当時の為替レートの変動をしらべて表示してください


async def create_structured_agent(model_id: str = "anthropic"):

    if "gpt" in model_id.lower():
        # モデルの設定

        model = init_chat_model(
            model="gpt-5-mini",
            temperature=0.1,
            max_tokens=4000,
            profile=custom_profile
        )

        print(f"Using OpenAI model: {model_id}")

    else:
        # ReActエージェントを利用する場合に、Bedrockモデルだと制限の緩和をしないと動作しないため、直接ChatBedrockを利用するか制限の緩和を行う
        model = ChatBedrock(
            credentials_profile_name="mra_dev",
            region_name="ap-northeast-1",
            system_prompt=system_prompt,
            model_id="apac.anthropic.claude-3-7-sonnet-20250219-v1:0",
            model_kwargs={
                "max_tokens": 4000,
                "temperature": 0.1
            },
            streaming=True,
        )

        print(f"Using Bedrock model: {model_id}")

    client = MultiServerMCPClient(
        {
            "boj-minutes-rag": {
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "-m", "mcp_server.boj_minutes_rag"],
            },
            "market-data": {
                "transport": "stdio",
                "command": "uv",
                "args": ["run", "-m", "mcp_server.market_data"],
            },
        }
    )

    mcp_tools = await client.get_tools()
    logger.info(f"Loaded MCP tools: {[tool.name for tool in mcp_tools]}")

    local_tools = await init_local_tools()
    logger.info(f"Loaded local tools: {[tool.name for tool in local_tools]}")

    tools = mcp_tools + local_tools

    agent = create_agent(
            model=model,
            tools=tools,
            checkpointer=InMemorySaver(),
            system_prompt=system_prompt,
            response_format=ToolStrategy(MarketAnalysisReport),
        )

    return agent

structured_agent = asyncio.run(create_structured_agent("gpt"))
