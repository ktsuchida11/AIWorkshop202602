
import asyncio
import re
import logging

from langchain_openai import ChatOpenAI
from langchain_aws import ChatBedrock
from langchain.chat_models import init_chat_model
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware, \
                                        SummarizationMiddleware, \
                                        PIIMiddleware, \
                                        ModelCallLimitMiddleware, \
                                        ToolCallLimitMiddleware
from langgraph.checkpoint.memory import InMemorySaver

from lib.tools import init_local_tools

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# システムプロンプト
system_prompt = """
あなたの責務はユーザからのリクエストを調査し、調査結果をファイル出力することです。
- ユーザーのリクエスト調査にWeb検索が必要であれば、Web検索ツールを使ってください。
- 必要な情報が集まったと判断したら検索は終了して下さい。
- 検索は最大2回までとしてください。
- ファイル出力はHTML形式(.html)に変換して保存してください。
  * Web検索が拒否された場合、Web検索を中止してレポート作成してください。
  * レポート保存を拒否された場合、レポート作成を中止し、内容をユーザーに直接伝えて下さい。
"""


def detect_ssn(content: str) -> list[dict[str, str | int]]:
    """Detect SSN with validation.
    SSNとは、米国の社会保障番号（Social Security Number）のことで、9桁の数字で構成されています。
    フォーマットは通常 "XXX-XX-XXXX" の形をとります。
    ただし、SSNにはいくつかの制約があり、以下のような番号は無効とされています。
    - 最初の3桁が "000", "666", または "900" から "999" の範囲に

    Returns a list of dictionaries with 'text', 'start', and 'end' keys.
    """

    matches = []
    pattern = r"\d{3}-\d{2}-\d{4}"
    for match in re.finditer(pattern, content):
        ssn = match.group(0)
        # Validate: first 3 digits shouldn't be 000, 666, or 900-999
        first_three = int(ssn[:3])
        if first_three not in [0, 666] and not (900 <= first_three <= 999):
            matches.append({
                "text": ssn,
                "start": match.start(),
                "end": match.end(),
            })
    return matches


async def create_middleware_agent(model_id: str = "anthropic"):

    tools = await init_local_tools()

    if "gpt" in model_id.lower():
        # モデルの設定

        model = ChatOpenAI(
            model="gpt-5-mini",
            temperature=0.1,
            max_tokens=4000
        )

        print(f"Using OpenAI model: {model_id}")

    else:
        # ReActエージェントを利用する場合に、Bedrockモデルだと制限の緩和をしないと動作しないため、直接ChatBedrockを利用するか制限の緩和を行う
        model = ChatBedrock(
            credentials_profile_name="mra_dev",
            region_name="ap-northeast-1",
            model_id="apac.anthropic.claude-3-7-sonnet-20250219-v1:0",
            model_kwargs={
                "max_tokens": 4000,
                "temperature": 0.1
            },
            streaming=True,
        )

        print(f"Using Bedrock model: {model_id}")

    # PII ミドルウェアの設定
    email_filter = PIIMiddleware("email", strategy="redact", apply_to_input=True)
    credit_card_filter = PIIMiddleware("credit_card", strategy="mask", apply_to_input=True)
    # tool call の制限ミドルウェア
    global_limiter = ToolCallLimitMiddleware(thread_limit=20, run_limit=10)
    search_limiter = ToolCallLimitMiddleware(tool_name="web_search", thread_limit=5, run_limit=3)
    database_limiter = ToolCallLimitMiddleware(tool_name="query_database", thread_limit=10)

    agent = create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
            checkpointer=InMemorySaver(),
            middleware=[
                HumanInTheLoopMiddleware(
                    interrupt_on={
                        # File 書き込み → approve / deny のみ、内容と保存先を確認してから実行
                        "write_file": {
                            "allowed_decisions": ["approve", "deny"],
                            "description": "ファイル書き込みを行います。内容と保存先を確認してください。",
                        },
                        # Web 検索 → approve / deny のみ、内容を確認してから実行
                        "web_search": {
                            "allowed_decisions": ["approve", "deny"],
                            "description": "外部 Web 検索を行います。クエリ内容と検索目的を確認してください。",
                        },
                        # Safe operation, no approval needed
                        "read_data": False,
                    },
                    description_prefix="Tool execution pending approval",
                ),
                # SummarizationMiddleware expects different parameter names
                # (see langchain.agents.middleware.summarization.SummarizationMiddleware)
                # パラメータはしてしたモデルに合わせて修正する必要がある
                # https://docs.langchain.com/oss/python/langchain/middleware/built-in#summarization
                SummarizationMiddleware(
                    model="gpt-4o-mini",
                    max_tokens_before_summary=4000,
                    messages_to_keep=20,
                ),
                # セキュリティに関連情報を問い合わせに含めないようにするためのミドルウェア
                # 予約されているチェックは email, credit_cart, ip, mac_address, url
                # ストラテジーには block (ブロック) 、redact（リダクション）、hash(ハッシュ)、 mask (マスク) がある
                # apply_to_input:モデルの実行前をチェックするかどうかを設定できる, TYPE: bool, DEFAULT: True
                # apply_to_output:モデルの実行結果をチェックするかどうかを設定できる, TYPE: bool, DEFAULT: False
                # apply_to_tool_results:ツールの実行結果をチェックするかどうかを設定できる, TYPE: bool, DEFAULT: False
                email_filter,
                credit_card_filter,
                # PII detection method1 正規表現で特定の値を検出した場合にブロックする
                PIIMiddleware(
                    "api_key",
                    detector=r"sk-[a-zA-Z0-9]{32}",
                    strategy="block",
                    apply_to_input=True
                ),
                # SSN カスタム検出器を利用した例
                PIIMiddleware(
                    "ssn",
                    detector=detect_ssn,
                    strategy="mask",
                    apply_to_input=True
                ),
                ModelCallLimitMiddleware(
                    thread_limit=10,
                    run_limit=3,
                    exit_behavior="end",
                ),
                global_limiter,
                search_limiter,
            ]
        )

    return agent

middleware_agent = asyncio.run(create_middleware_agent("gpt"))
