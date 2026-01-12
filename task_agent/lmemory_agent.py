import asyncio
import logging
import os
import uuid
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend, StateBackend, StoreBackend
from psycopg import Connection, AsyncConnection
from psycopg.rows import dict_row
from langgraph.store.postgres import PostgresStore
from langgraph.checkpoint.memory import MemorySaver  # short-termは今回はメモリでOK
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver # short-term永続化用
from langchain.chat_models import init_chat_model

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

os.environ["OPENAI_API_KEY"] = "your_openai_api_key_here"
DATABASE_URL = "postgresql://user:password@localhost:35432/agent_store"
ASSISTANT_ID = "boj-research-agent"  # 重要：固定

# -----------------------------
# 長期記憶（Long-term memory）
# -----------------------------
# PostgresStore は「/memories/...」など “StoreBackend にルーティングされたパス” を永続化するためのストア。
# ここに保存された内容はスレッド(thread_id)を跨いで参照でき、プロセス再起動後も残る。
conn = Connection.connect(DATABASE_URL, autocommit=True)
store = PostgresStore(conn)
store.setup()

print("store=", type(store), getattr(store, "conn", None))

# モデルプロファイルの定義（OpenAI用）
custom_profile = {
    "structured_output": False,
    # ...
}


async def create_longterm_deep_agent(model_id: str = "anthropic"):

    model = init_chat_model(
        model="gpt-5-mini",
        temperature=0.1,
        max_tokens=4000,
        profile=custom_profile
    )

    # -----------------------------
    # 短期記憶（Short-term memory）
    # -----------------------------
    # checkpointer は「会話スレッド(thread)の状態」を保存・復元する仕組み（会話履歴/途中状態など）。
    # ここを永続化すると、同じ thread_id を指定すれば、プロセス再起動後でも “前回の続き” として再開できる。
    #
    # ただし、今は MemorySaver() なので “メモリ上のみ” 保存され、プロセス終了で消える（=短期は永続化されない）。
    # checkpointer = MemorySaver()
    # Use the async Postgres saver so async methods like `aget_tuple` are implemented
    async_conn = await AsyncConnection.connect(DATABASE_URL, autocommit=True, prepare_threshold=0, row_factory=dict_row)
    checkpointer = AsyncPostgresSaver(async_conn)
    await checkpointer.setup()

    agent = create_deep_agent(
        model=model,

        # 長期記憶のストア（/memories/ を永続化したいので store を渡す）
        store=store,

        # CompositeBackend のルーティング：
        # - default=StateBackend(rt) は “スレッド内の一時ファイル/状態” を保持（短期・揮発）。
        # - routes={"/memories/": StoreBackend(rt)} は /memories/ 配下だけ PostgresStore に永続化（長期）。
        backend=lambda rt: CompositeBackend(
            default=StateBackend(rt),
            routes={"/memories/": StoreBackend(rt)},
        ),

        # ★短期記憶の保存先（現在は MemorySaver = 揮発）
        checkpointer=checkpointer,

        # ここで「好みは /memories/user_preferences.txt に保存し、会話開始で読む」という運用方針を与える。
        # ※ユーザーが毎回「保存して」と言わなくても、この方針に従って保存するように誘導できる。
        system_prompt=(
            "When users share stable preferences or facts, save them to "
            "/memories/user_preferences.txt. "
            "At the start of each conversation, read /memories/user_preferences.txt."
        ),
    )

    return agent

lt_deep_agent = asyncio.run(create_longterm_deep_agent())  # Ensure async function is called properly


# テスト用コード：長期記憶の保存と読み取り
async def test_agent_memory():
    # 1回目（thread1）: 保存
    config1 = {"configurable": {"thread_id": str(uuid.uuid4()), "assistant_id": ASSISTANT_ID}}
    agent = await create_longterm_deep_agent()  # Ensure the agent is created
    await agent.ainvoke(
        {"messages": [{"role": "user", "content": "私の好み: ずんだもん口調。これを /memories/user_preferences.txt に保存して。"}]},
        config=config1,
    )

    # 2回目（thread2）: 読み取り（別スレッド）
    # 長期記憶（/memories）は別スレッドでも読める設計なので、ここは uuid でも問題ない。
    # ただし「前回の会話の続き（短期状態）を復元したい」なら、thread_id を同じにする必要がある。
    config2 = {"configurable": {"thread_id": str(uuid.uuid4()), "assistant_id": ASSISTANT_ID}}
    out = await agent.ainvoke(
        {"messages": [{"role": "user", "content": "私の好みを教えて。忘れてしまっていますか？"}]},
        config=config2,
    )

    print("Agent Response:", out)

if __name__ == "__main__":
    asyncio.run(test_agent_memory())

# Ensure the file ends with a newline