import asyncio
import operator
import boto3
import os
import json

from langchain.chat_models import init_chat_model
from langchain_tavily import TavilySearch
from langchain_core.tools import tool
from langchain_core.messages import AnyMessage, AIMessage, HumanMessage, SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_community.agent_toolkits import FileManagementToolkit
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel
from typing import Annotated, Dict, List, Union

from dotenv import load_dotenv
load_dotenv()


async def init_mcp_tools():

    with open("./task_agent/mcp_config.json", "r") as f:
        config = json.load(f)

    mcp_client = MultiServerMCPClient(config["mcpServers"])
    # MCPサーバーをLangChainツールとして取得
    tools = await mcp_client.get_tools()

    return tools


web_search = TavilySearch(max_results=2)
web_search.name = "web_search"

working_directory = "./filesystem"
# ローカルファイルを扱うツールキット
file_toolkit = FileManagementToolkit(
    root_dir=str(working_directory),
    selected_tools=["write_file"], # ファイル書き込みツールを指定
)

write_file = file_toolkit.get_tools()[0]


@tool
def send_aws_sns(text: str):
    """テキストをAWS SNSのトピックにPublishするツール"""
    topic_arn = os.getenv("SNS_TOPIC_ARN")
    sns_client = boto3.client('sns')
    sns_client.publish(TopicArn=topic_arn, Message=text)


async def init_local_tools():

    tools = await init_mcp_tools()

    tools.append(web_search)
    tools.append(write_file)

    return tools
