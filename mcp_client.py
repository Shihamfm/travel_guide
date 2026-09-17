import os
import asyncio
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient

load_dotenv()

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
AVIATIONSTACK_API_KEY = os.getenv('AVIATIONSTACK_API_KEY')

client = MultiServerMCPClient(
    {
        "tavily": {
            "transport": "streamable_http",
            "url": f"https://mcp.tavily.com/mcp/?tavilyApiKey={TAVILY_API_KEY}"

    },
       
        "aviationstack": {
        "transport": "stdio",
        "command": "uvx",
        "args": [
        "aviationstack-mcp"
        ],
        "env": {
        "AVIATION_STACK_API_KEY": AVIATIONSTACK_API_KEY
      }
    }
    }
) 

async def get_all_tools():
    tools = await client.get_tools()
    print("\n Available MCP Tools \n")

    for tool in tools:
        print(tool.name)


#tavily and aviation_search tools
search_tool = None
aviation_tool = {}

async def initalize_mcp():
    global search_tool
    global aviation_tool

    if search_tool is not None and aviation_tool:
        return

    tools = await client.get_tools()

    print("\n Available MCP Tools \n")

    for tool in tools:
        print(tool.name)

    search_tool = next(
        tool
        for tool in tools
        if tool.name == "tavily_search"
    )

    aviation_tool = {
        tool.name: tool
        for tool in tools
        if tool.name != "tavily_search"
    }

async def avaiation_mcp_call(
        tool_name: str, 
        tool_args: dict = None
        ):

    tools = await client.get_tools()

    tool = next(
        t for t in tools
        if t.name == tool_name
    )

    result = await tool.ainvoke(
        tool_args or {}
    )

    return result

# The function can be used to call the tavily_search tool with a query in backend.py
async def tavily_mcp_search(query: str):
    await initalize_mcp()
    result = await search_tool.ainvoke(
        {
            "query": query
        }
    )

    return result







