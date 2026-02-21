
import asyncio
import logging
import os
from datetime import datetime, timedelta

import httpx
from langchain_openai import ChatOpenAI
from langchain_aws import ChatBedrock
from langchain.chat_models import init_chat_model
from langchain_mcp_adapters.client import MultiServerMCPClient

from langgraph.checkpoint.memory import MemorySaver  # short-termは今回はメモリでOK
from langgraph.store.postgres import PostgresStore
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver # short-term永続化用
from psycopg import Connection, AsyncConnection
from psycopg.rows import dict_row

from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend

from langchain.agents.middleware import HumanInTheLoopMiddleware
from langchain.agents.structured_output import ToolStrategy
from lib.tools import init_local_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# モデルプロファイルの定義（OpenAI用）
# 構造化出力を有効にする例 defaultはFalse
custom_profile = {
    "structured_output": False,
    # ...
}

# システムプロンプト（テンプレート）。呼び出し時に今日の日付を埋め込みます。
SYSTEM_PROMPT_TEMPLATE = """

###

あなたの責務は日銀の金融政策決定会合があったときの金融マーケットの情報を調査して結果をファイル出力することです。
- 日本銀行の議事要旨と会見の内容を保存した内容を検索できます。
- 市場データツールを利用することで、過去のおよび現在の金融マーケット情報を取得できます。
- 必要な情報が集まったと判断したら調査は終了して下さい
- 出力結果は日本語で翻訳してください。
- response_formatのMarketAnalysisReportに従い、マーケット分析レポートを作成してください。
    * Web検索が拒否された場合、Web検索を中止してレポート作成してください。
    * レポート保存を拒否された場合、レポート作成を中止し、内容をユーザーに直接伝えて下さい。

## 長期記憶ルール

このエージェントは長期記憶を使用し、以下を保存／参照します。保存は必要最小限にとどめ、プライバシーと同意を尊重してください。

- ユーザのプロフィール: 名前や好み、設定など。保存先パス例: `/memories/{assistant_id}/user_profile/`
- 会話の履歴: 会話の要約・重要な発言・タイムスタンプ。保存先パス例: `/memories/{assistant_id}/conversations/`
- ナレッジベース: 調査で得た事実・参照、外部ソースの要約。保存先パス例: `/memories/{assistant_id}/knowledge/`

保存と利用のルール:

1. 保存は明確な目的がある場合のみ行う（例: 個人化、継続的調査のための文脈保持）。
2. 機微な個人情報は保存しない、または保存前にユーザの同意を得る。
3. 応答生成時は関連するメモリを検索して参照するが、不要な情報漏洩を避けるため最小限を採用する。
4. 記憶の更新・削除要求があれば従う（ユーザ要求に基づく管理）。

参考: 長期記憶は `StoreBackend` 経由で `/memories/...` に保存され、必要時に検索・取得して応答に活用してください。詳細実装方針は https://docs.langchain.com/oss/python/deepagents/long-term-memory を参照。

##

今日の日付: {today}
"""

DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost:35432/agent_store")

# -----------------------------
# 長期記憶（Long-term memory）
# -----------------------------
# PostgresStore は「/memories/...」など “StoreBackend にルーティングされたパス” を永続化するためのストア。
# ここに保存された内容はスレッド(thread_id)を跨いで参照でき、プロセス再起動後も残る。
conn = Connection.connect(DATABASE_URL, autocommit=True)
store = PostgresStore(conn)
store.setup()


# If TTL is configured, start the sweeper thread so expired items are cleaned up
if getattr(store, "start_ttl_sweeper", None):
    try:
        store.start_ttl_sweeper()
        logger.info("PostgresStore TTL sweeper started")
    except Exception:
        logger.debug("PostgresStore TTL sweeper could not be started", exc_info=True)


async def _fetch_jwt_token() -> str:
    """JWT サーバからアクセストークンを取得する"""
    jwt_server_url = os.environ.get("JWT_SERVER_URL", "http://localhost:4444")
    username = os.environ.get("JWT_USERNAME", "alice")
    password = os.environ.get("JWT_PASSWORD", "password123")
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.post(
            f"{jwt_server_url}/login",
            json={"username": username, "password": password},
        )
        response.raise_for_status()
        return response.json()["token"]


async def create_origin_deep_agent(model_id: str = "anthropic", assistant_id: str = None):
    # テンプレートに今日の日付を埋め込む
    today = datetime.now().strftime("%Y-%m-%d")
    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(today=today, assistant_id=assistant_id)

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

    jwt_token = await _fetch_jwt_token()
    logger.info("JWT token acquired for indicator MCP server")

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
            # --- HTTP MCP（Docker / FastMCP） ---
            "youtube-transcribe": {
                "transport": "http",
                "url": "http://localhost:3333/mcp",
                "headers": {
                    "Authorization": "Bearer dev-alice-token"
                },
                "timeout": timedelta(seconds=120),

                # 2) 次のイベントが来るまで待つ時間（長時間処理で重要）
                #    例：10分チャンク×6=60分 + 余裕 => 80分など
                "sse_read_timeout": timedelta(minutes=80),
            },
            # --- HTTP MCP with JWT Bearer token ---
            "indicator": {
                "transport": "http",
                "url": "http://localhost:5555/mcp",
                "headers": {
                    "Authorization": f"Bearer {jwt_token}",
                },
                "timeout": timedelta(seconds=30),
                "sse_read_timeout": timedelta(minutes=5),
            },
            # --- HTTP MCP with Google OAuth2.0 ---
            "news-search": {
                "transport": "http",
                "url": "http://localhost:7666/mcp",
                "oauth": {
                    "provider": "google",
                    "client_id": os.getenv("GOOGLE_CLIENT_ID"),
                    "client_secret": os.getenv("GOOGLE_CLIENT_SECRET"),
                    "scopes": ["openid", "email", "profile"],
                },
                "timeout": timedelta(seconds=30),
                "sse_read_timeout": timedelta(minutes=5),
            },
        }
    )

    mcp_tools = await client.get_tools()
    logger.info(f"Loaded MCP tools: {[tool.name for tool in mcp_tools]}")

    local_tools = await init_local_tools()
    logger.info(f"Loaded local tools: {[tool.name for tool in local_tools]}")

    tools = mcp_tools + local_tools

    async_conn = await AsyncConnection.connect(DATABASE_URL, autocommit=True, prepare_threshold=0, row_factory=dict_row)
    checkpointer = AsyncPostgresSaver(async_conn)
    await checkpointer.setup()

    agent = create_deep_agent(
            model=model,
            tools=tools,
            checkpointer=checkpointer,  # Required for HumanInTheLoopMiddleware
            store=store,
            backend=lambda rt: CompositeBackend(
                default=StateBackend(rt),
                routes={"/memories/": StoreBackend(rt)}
            ),
            system_prompt=system_prompt,
            interrupt_on={
                # File 書き込み → approve / deny のみ、内容と保存先を確認してから実行
                "write_file": {
                    "allowed_decisions": ["approve", "deny"],
                    "description": "ファイル書き込みを行います。内容と保存先を確認してください。",
                }
            }

        )

    return agent
