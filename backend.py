import asyncio
import os
from dotenv import load_dotenv
from typing import TypedDict, Annotated
import operator, uuid

import psycopg
from psycopg.rows import dict_row

from langchain_groq import ChatGroq
from langchain_core.messages import (
    AnyMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
)
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.postgres import PostgresSaver

# from tools.flight_tool import search_flights
# from tools.tavily_tool import tavily_research
from mcp_client import avaiation_mcp_call, tavily_mcp_search



load_dotenv()

def get_database_url():
    database_url = os.getenv('DATABASE_URL')

    if not database_url:
        raise ValueError(
            "DATABASE_URL is missing. Please add your Superbase External Database URL to .env"
        )

    if "sslmode=" not in database_url:
        separator = "&" if "?" in database_url else "?"
        database_url = f"{database_url}{separator}sslmode=require"

    return database_url

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
if not GROQ_API_KEY:
    raise ValueError(
        "GROQ_API_KEY is missing"
    )

# LLM
llm = ChatGroq(
    model='openai/gpt-oss-120b',
    api_key=GROQ_API_KEY
)

# STATE
class TravelState(TypedDict):
    messages: Annotated[list[AnyMessage], operator.add]
    user_query: str
    flight_results: str
    hotel_results: str
    itinerary: str
    llm_calls: str

# def flight_agent(state: TravelState):
#     query = state["user_query"]
#     flight_data = search_flights(query)

#     return{
#         'flight_results': flight_data,
#         'messages': [
#             AIMessage(content="Flight results fetched")
#         ],
#         'llm_calls': state.get('llm_calls',0) + 1
#     }


# Flight Tool Router Prompt
FLIGHT_AGENT_PROMPT = """
You are a travel flight expert.

User Query:
{query}

Airport Information:
{airport_data}

Airline Information:
{airline_data}

Generate:

1. Likely departure airport
2. Likely arrival airport
3. Airlines serving this route
4. Typical flight duration
5. Estimated airfare range
6. Peak season pricing warning
7. Booking advice

Return concise travel guidance.
"""

# FLIGHT AGENT
def flight_agent(state: TravelState):
    print("\n INSIDE FLIGHT AGENT \n")

    query = state["user_query"]

    try:

        airports = asyncio.run(
            avaiation_mcp_call(
                "list_airports"
            )
        )

        airlines = asyncio.run(
            avaiation_mcp_call(
                "list_airlines"
            )
        )

        print("\n AIRPORTS:", airports)
        print("\n AIRLINES:", airlines)

        prompt = FLIGHT_AGENT_PROMPT.format(
            query = query,
            airport_data = str(airports)[:50],
            airline_data = str(airlines)[:50]
        )

        response = llm.invoke([
            SystemMessage(
                content="You are an expert travel flight planner"
            ),
            HumanMessage(content=prompt)
        ])

        flight_data = response.content

    except Exception as e:

        flight_data = f"flight information unavailable: str{e}"

    return{
        "flight_results": flight_data,
        "message": [
            AIMessage(
                content="Flight recommendation generated"
            )
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }





# HOTEL AGENT
def hotel_agent(state: TravelState):
    query = f"Best hotels for {state['user_query']}"
    # hotel_results = tavily_research(query)
    hotel_results = asyncio.run(tavily_mcp_search(query))

    return{
        'hotel_results': hotel_results,
        'messages': [
                    AIMessage(content="Hotel information fetched")
                ],
                'llm_calls': state.get('llm_calls',0) + 1
    }


# ITINERARY AGENT
def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query: {state['user_query']}
Flight Results: {state['flight_results']}
Hotel Results: {state['hotel_results']}

Make the itinerary practical, budget aware, and easy to follow.
"""

    response = llm.invoke([
        SystemMessage(content='You are an expert travel planner.'),
        HumanMessage(content=prompt)
    ])

    return {
        'itinerary': response.content,
        'messages': [response],
        'llm_calls': state.get('llm_calls',0) + 1
    }


# FINAL RESPONSE AGENT
def final_agent(state: TravelState):
    final_prompt = f"""
Generate the final travel response from the user.

User Request: {state['user_query']}
Flight: {state['flight_results']}
Hotel: {state['hotel_results']}
Itinerary: {state['itinerary']}

Format the final answer beautifully using these sections:

1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Day-by-Day Itinerary
5. Estimated Budget
6. Final Recommendations

Important:
- Be clear and practical.
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- Keep the response useful for real travel planning.
"""
    response = llm.invoke([
            SystemMessage(content='You are a professional AI travel booking assistant'),
            HumanMessage(content=final_prompt)
        ])
    
    return {
        'messages': [response],
        'llm_calls': state.get('llm_calls',0) + 1
    }

# BUILD GRAPH
graph = StateGraph(TravelState)

graph.add_node('flight_agent', flight_agent)
graph.add_node('hotel_agent', hotel_agent)
graph.add_node('itinerary_agent', itinerary_agent)
graph.add_node('final_agent', final_agent)

graph.add_edge(START, 'flight_agent')
graph.add_edge('flight_agent', 'hotel_agent')
graph.add_edge('hotel_agent', 'itinerary_agent')
graph.add_edge('itinerary_agent', 'final_agent')
graph.add_edge('final_agent', END)

# POSTGRESQL Checkpointer
DATABASE_URL = get_database_url()

_conn = psycopg.connect(
    DATABASE_URL,
    autocommit=True,
    row_factory=dict_row
)
checkpointer = PostgresSaver(_conn)
checkpointer.setup()

travel_graph = graph.compile(checkpointer=checkpointer)

# FUNCTION FOR FASTAPI
def run_travel_agent(user_input: str, thread_id: str | None = None):
    if not thread_id:
        thread_id = f"user_{uuid.uuid4().hex}"

    config = {
        "configurable": {
            "thread_id": thread_id
        }
    }

    result = travel_graph.invoke(
        {
            "messages": [
                HumanMessage(content=user_input)
            ],
            "user_query": user_input,
            "flight_results": "",
            "hotel_results": "",
            "itinerary": "",
            "llm_calls": 0
        },
        config=config
    )
    final_answer = result['messages'][-1].content

    return{
        'thread_id': thread_id,
        'answer': final_answer,
        'flight_results': result.get('flight_results', ""),
        'hotel_results': result.get('hotel_results', ""),
        'itinerary': result.get ('itinerary', ""),
        'llm_calls': result.get('llm_calls')
    }