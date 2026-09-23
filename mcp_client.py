from asyncio import coroutines
import typing_inspection
from mimetypes import init
from psycopg import connection_async
import os
import sys
import asyncio
from dotenv import load_dotenv
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_groq import ChatGroq

load_dotenv()

TAVILY_API_KEY = os.getenv('TAVILY_API_KEY')
AVIATION_STACK_API_KEY = os.getenv('AVIATIONSTACK_API_KEY')
OPENWEATHER_API_KEY = os.getenv('OPENWEATHER_API_KEY')
GROQ_API_KEY = os.getenv('GROQ_API_KEY')

# Preserve environment for uvx, but strip virtualenv/python paths
# to avoid binary/module mismatch (e.g., SRE module mismatch) between Python runtimes.
AVIATION_ENV = os.environ.copy()
for var in ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
    AVIATION_ENV.pop(var, None)

AVIATION_ENV["AVIATION_STACK_API_KEY"] = (
    AVIATION_STACK_API_KEY or ""
)

WEATHER_ENV = os.environ.copy()
WEATHER_ENV["OPENWEATHER_API_KEY"] = (
    OPENWEATHER_API_KEY or ""
)

#LLM
llm = ChatGroq(
    model='openai/gpt-oss-120b',
    api_key=GROQ_API_KEY
)

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
                "aviationstack-mcp",
            ],
            "env": AVIATION_ENV
        
    },
        "weather": {
            "transport": "stdio",
            "command": sys.executable,
            "args": [
            r"E:\Projects\DS\travel_guide\custom_weather_mcp_server.py"
            ],
            "env": WEATHER_ENV
    }
    }
) 

async def get_all_tools():
    """
    Load each MCP server sperately
    """
    all_tools = []

    for server_name in (
        'tavily',
        'aviationstack',
        'weather'
    ):
        try:
            tools = await client.get_tools(
                server_name=server_name
            )
            all_tools.extend(tools)

            print(
                f"\n Available MCP Tools from"
                f"{server_name} MCP: \n")

            for tool in tools:
                print(tool.name)

        except Exception as error:
            print(
                f"\n Count not connect to "
                f"{server_name} MCP: \n{error}\n"
            )
    return all_tools


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

    if isinstance(result, list) and len(result) > 0:
        first = result[0]
        if hasattr(first, "text"):
            return str(first.text)
        if isinstance(first, dict) and "text" in first:
            return str(first["text"])
    return str(result)

# The function can be used to call the tavily_search tool with a query in backend.py
async def tavily_mcp_search(query: str):
    await initalize_mcp()
    result = await search_tool.ainvoke(
        {
            "query": query
        }
    )

    if isinstance(result, list) and len(result) > 0:
        first = result[0]
        if hasattr(first, "text"):
            return str(first.text)
        if isinstance(first, dict) and "text" in first:
            return str(first["text"])
    return str(result)

#weather tool & forecast tool
weather_tool = None
forecast_tool = None
async def initialize_weather_tools():
    global weather_tool, forecast_tool

    if weather_tool is not None:
        return

    tools = await client.get_tools()

    weather_tool = next(
            tool
            for tool in tools
            if tool.name == "get_current_weather"
        )

    forecast_tool = next(
            tool
            for tool in tools
            if tool.name == "get_forecast"
        )

# get current weather
async def weather_mcp_search(city: str):

    await initialize_weather_tools()

    result = await weather_tool.ainvoke(
        {
            'city': city
        }
    )

    if isinstance(result, list) and len(result) > 0:
        first = result[0]
        if hasattr(first, "text"):
            return str(first.text)
        if isinstance(first, dict) and "text" in first:
            return str(first["text"])
    return str(result)

# get forecast weather
async def forecast_mcp_search(city: str):
    
    await initialize_weather_tools()

    result = await forecast_tool.ainvoke(
        {
            'city': city
        }
    )

    if isinstance(result, list) and len(result) > 0:
        first = result[0]
        if hasattr(first, "text"):
            return str(first.text)
        if isinstance(first, dict) and "text" in first:
            return str(first["text"])
    return str(result)

# Destination Extractor
def extract_destination(query: str) -> str:
    prompt = f"""
    Extract the primary destination CITY for travel weather and hotel planning.
    
    User Request: {query}

    Rules:
    1. If a specific city is mentioned (e.g. "Paris", "Kyoto", "New Delhi", "Tokyo", "Sigiriya"), return ONLY that city name.
    2. If only a country is mentioned (e.g. "India", "Japan", "Sri Lanka", "UAE"), return the primary major tourist/capital city (e.g. "New Delhi" for India, "Tokyo" for Japan, "Colombo" for Sri Lanka, "Dubai" for UAE).
    3. Return ONLY the city name. Do not include extra text, quotes, or punctuation.
    """
    try:
        response = llm.invoke(prompt)
        city = response.content.strip().replace('"', '').replace("'", "").split("\n")[0]
        return city
    except Exception as exc:
        return f"Destination extraction error: {exc}"
        
