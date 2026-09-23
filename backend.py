from langchain_core.messages import content
from langgraph.types import interrupt, Command
from pydantic.v1.typing import resolve_annotations
from langgraph import constants
import asyncio
import os
import json
from dotenv import load_dotenv
from typing import TypedDict, Annotated, Any
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
from mcp_client import avaiation_mcp_call, tavily_mcp_search, extract_destination, weather_mcp_search, forecast_mcp_search




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

    # Supervisor + guardrail state
    guardrail_allowed: bool
    guardrail_reason: str
    selected_agents: list[str]
    trip_constraints: dict[str, Any]
    supervisor_reasoning: str

    # Original specialist results
    flight_results: str
    hotel_results: str
    weather_results: str
    itinerary: str
    
    # New budget + HITL state
    budget_results: str
    approval_request: str
    approved: bool
    human_feedback: str
    final_response: str
    
    llm_calls: int

# Shared helpers
KNOWN_AGENT = {
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent"
}

AGENT_ORDER = [
    "flight_agent",
    "hotel_agent",
    "weather_agent",
    "budget_agent",
    "itinerary_agent"
]

def _llm_text(system_prompt: str, user_prompt: str) -> str:
    response = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt)
        ]
    )

    return response.content

def _trim_context(text: Any, max_chars: int = 1200) -> str:
    """Helper to bound context string lengths to prevent Groq TPM rate limits."""
    if not text:
        return ""
    text_str = str(text).strip()
    if len(text_str) <= max_chars:
        return text_str
    return text_str[:max_chars] + "\n...[context trimmed for token limits]..."
    
def _json_from_llm(text: str) -> dict:
    """Extract the first complete JSON object return by the model"""
    start = text.find("{")
    end = text.find("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("The model did not return a JSON object.")

    return json.loads(text[start:end+1])

def _empty_constraints() -> dict[str: Any]:
    return {
        "destination": "",
        "origin": "",
        "duration": "",
        "budget": "",
        "travel_style": "",
        "special_preferences": [],
    }

# Supervisor Agent + Input
def supervisor_agent(state: TravelState):
    query = state['user_query']
    llm_calls = state.get('llm_calls', 0)

    guardrail_prompt = f"""
Determine whether the following request belongs to travel planning or travel
information. Valid requests can include destinations, flights, hotels, weather,
budgets, visas, transportation, sightseeing, food, packing, or itineraries.

Block clearly unrelated requests and requests asking for harmful or illegal
instructions. Do not block a valid travel request merely because some details
are missing.

Return strict JSON only.
{{
    "allowed": true,
    "reason": ""
}}

User request:
{query}
"""
    # Fail open on parser/model errors so a temporary JSON-format issue does not
    # break the original travel-planning behavior.
    try:
        guardrail_raw = _llm_text(
            "You are the input guardrail for a travel-planning application. "
            "Return strict JSON only.",
            guardrail_prompt,
        )

        guardrail_results = _json_from_llm(guardrail_raw)
        allowed = bool(guardrail_results.get("allowed", True))
        guardrail_reason = str(guardrail_results.get("reason", "")).strip()
        llm_calls += 1
    
    except Exception as exc:
        print(f"Guardrail fallback used: {exc}")
        allowed = True
        guardrail_reason = "Guardrail validation fallback allowed the request."
    
    if not allowed:
        reason = guardrail_reason or (
            "TripMate AI can only help with travel-planning requests. "
            "Please ask about a destination, flight, hotel, weather, budget, "
            "or itinerary." 
            )
        return {
            "guardrail_allowed": False,
            "guardrail_reason": reason,
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": reason,
            "final_response": reason,
            "messages": [AIMessage(content=f"Guardrail blocked request: {reason}")],
            "llm_calls": llm_calls,
        }

    supervisor_prompt = f"""
You are the supervisor of a multi-agent travel-planning system.
Choose only the specialist agents needed for the request.

Available agents:
- flight_agent: flights, airports, airlines, routes, airfare, or booking advice
- hotel_agent: hotels, accommodation, neighborhoods, or places to stay
- weather_agent: weather, climate, season, forecast, or packing advice
- budget_agent: cost, affordability, price limits, or budget feasibility
- itinerary_agent: creates the integrated travel plan and must always be included

Return strict JSON only using this schema:
{{
  "selected_agents": ["flight_agent", "hotel_agent", "weather_agent", "budget_agent", "itinerary_agent"],
  "trip_constraints": {{
    "destination": "",
    "origin": "",
    "duration": "",
    "budget": "",
    "travel_style": "",
    "special_preferences": []
  }},
  "reasoning": ""
}}

User request:
{query}
"""

    try:
        supervisor_raw = _llm_text(
            "You route work to travel specialist agents. Return strict JSON only.",
            supervisor_prompt,
        )
        parsed = _json_from_llm(supervisor_raw)
        requested_agents = parsed.get("selected_agents", [])
        selected_agents = [
            name for name in AGENT_ORDER
            if name in requested_agents and name in KNOWN_AGENT
        ]

        # The itinerary agent integrates whichever specialist results were selected
        if "itinerary_agent" not in selected_agents:
            selected_agents.append("itinerary_agent")

        constraints = _empty_constraints()
        parsed_constraints = parsed.get("trip_constraints", [])
        if isinstance(parsed_constraints, dict):
            constraints.update(parsed_constraints)
        
        reasoning = str(parsed.get("reasoning", "")).strip()
        llm_calls += 1
        
    except Exception as exc: 
        print(f"Supervisor fallback used {exc}")
        selected_agents = AGENT_ORDER.copy()
        constraints = _empty_constraints()
        reasoning = (
            "Supervisor parsing failed, so the original full travel workflow "
            "was selected as a safe fallback."
        )

    return {
        "guardrail_allowed": True,
        "guardrail_reason": guardrail_reason,
        "selected_agents": selected_agents,
        "trip_constraints": constraints,
        "supervisor_reasoning": reasoning,
        "messages": [AIMessage(content="Supervisor created the agent plan.")],
        "llm_calls": llm_calls
    }


# Guardrail blocked response
def guardrail_blocked_agent(state: TravelState):
    reason = state.get("final_response") or state.get("guardrail_reason") or (
        "This request was blocked by travel input guardrail"
    )
    return {
        "final_response": reason,
        "messages": AIMessage(content=reason)
    } 


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
            airport_data = str(airports)[:200],
            airline_data = str(airlines)[:200]
        )

        response = llm.invoke([
            SystemMessage(
                content="You are an expert travel flight planner"
            ),
            HumanMessage(content=prompt)
        ])
        flight_data = _trim_context(response.content, 1200)

    except Exception as e:
        flight_data = f"flight information unavailable: {e}"

    return {
        "flight_results": flight_data,
        "messages": [AIMessage(content="Flight recommendation generated")],
        "llm_calls": state.get("llm_calls", 0) + 1
    }


# HOTEL AGENT
def hotel_agent(state: TravelState):
    constraints = state.get('trip_constraints', {})
    dest = constraints.get('destination') or extract_destination(state['user_query'])
    query = f"Best hotels and accommodation in {dest}"
    
    try: 
        raw_text = asyncio.run(tavily_mcp_search(query))
        
        # Inline Tavily search result parsing & markdown formatting
        try:
            data = json.loads(raw_text)
            if isinstance(data, dict) and "results" in data:
                formatted = [f"### 🏨 Hotel & Accommodation Research for {dest}\n"]
                for idx, res in enumerate(data["results"][:4], 1):
                    title = res.get("title", f"Hotel Result {idx}")
                    content = res.get("content", "").strip()
                    url = res.get("url", "")
                    link_str = f" [Link]({url})" if url else ""
                    formatted.append(f"**{idx}. {title}**{link_str}\n{content}\n")
                hotel_results = "\n".join(formatted)
            else:
                hotel_results = f"### 🏨 Hotel Recommendations for {dest}\n\n" + str(raw_text)
        except Exception:
            hotel_results = f"### 🏨 Hotel Recommendations for {dest}\n\n" + str(raw_text)

        hotel_results = _trim_context(hotel_results, 1200)

    except Exception as exc:
        print(
            f"HOTEL AGENT MCP ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        hotel_results = (
            f"Live hotel search is temporarily unavailable for {dest}. "
            "Provide general accommodation and neighborhood "
            "guidance based on the destination and clearly "
            "label it as non-live advice."
        ) 

    return {
        'hotel_results': hotel_results,
        'messages': [
            AIMessage(content="Hotel information fetched")
        ],
        'llm_calls': state.get('llm_calls', 0) + 1
    }

# WEATHER AGENT
def weather_agent(state: TravelState):
    constraints = state.get('trip_constraints', {})
    city = constraints.get('destination') or extract_destination(state["user_query"])
    if "," in city:
        city = city.split(",")[0].strip()

    try:
        current_raw = asyncio.run(weather_mcp_search(city))
        forecast_raw = asyncio.run(forecast_mcp_search(city))
        
        # Inline OpenWeather result parsing & markdown formatting
        lines = [f"### 🌤️ Weather Analysis for {city.title()}\n"]
        
        try:
            cur_json = json.loads(current_raw)
            if isinstance(cur_json, dict) and "temperature_c" in cur_json:
                temp = cur_json.get("temperature_c")
                humidity = cur_json.get("humidity")
                cond = cur_json.get("condition")
                wind = cur_json.get("wind_speed")
                lines.append(f"**Current Conditions:** {cond.title() if cond else 'N/A'}")
                lines.append(f"- 🌡️ **Temperature:** {temp}°C")
                lines.append(f"- 💧 **Humidity:** {humidity}%")
                lines.append(f"- 💨 **Wind Speed:** {wind} m/s\n")
            else:
                lines.append(f"Current Weather: {current_raw}\n")
        except Exception:
            lines.append(f"Current Weather: {current_raw}\n")

        try:
            fc_json = json.loads(forecast_raw)
            if isinstance(fc_json, dict) and "forecast" in fc_json:
                lines.append("**Upcoming Forecast:**")
                for item in fc_json["forecast"][:4]:
                    dt = item.get("datetime", "")
                    t = item.get("temperature", "")
                    w = item.get("weather", "")
                    lines.append(f"- `{dt}`: {t}°C, {w}")
            else:
                lines.append(f"Forecast: {forecast_raw}")
        except Exception:
            lines.append(f"Forecast: {forecast_raw}")

        weather_results = "\n".join(lines)
        weather_results = _trim_context(weather_results, 800)
    except Exception as exc:
        print(
            f"WEATHER AGENT MCP ERROR: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

        weather_results = (
            f"Live weather information for {city} is temporarily unavailable. "
            "Provide general weather guidance based on the destination "
            "and clearly label it as non-live advice."
        )
    
    return {
        "weather_results": weather_results,
        "messages": [
            AIMessage(content="Weather information fetched")
        ],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# BUDGET AGENT
def budget_agent(state: TravelState):
    prompt = f"""
    Analyze whether the trip is realistic for the user's budget.

    User Query: {state['user_query']}
    Trip Constraints: {state.get('trip_constraints', {})}
    Flight Results: {_trim_context(state.get('flight_results', ''))}
    Hotel Results: {_trim_context(state.get('hotel_results', ''))}
    Weather Results: {_trim_context(state.get('weather_results', ''))}
    
    Return:
    1. Estimated cost categories
    2. Budget risk areas
    3. Money-saving suggestions
    4. Overall feasibility

    If exact live prices are unavailable, clearly label estimates as approximate.
    """
    response = _llm_text(
        system_prompt="You are a budget analysis expert for travel plans",
        user_prompt=prompt
    )
    return {
        "budget_results": _trim_context(response, 1200),
        "messages": [AIMessage(content="Budget Assessment generated")],
        "llm_calls": state.get("llm_calls", 0) + 1
    }

# ITINERARY AGENT
def itinerary_agent(state: TravelState):
    prompt = f"""
Create a complete travel itinerary.

User Query: {state['user_query']}
Trip Constraints: {state.get('trip_constraints', {})}
Flight Results: {_trim_context(state.get('flight_results', ''))}
Hotel Results: {_trim_context(state.get('hotel_results', ''))}
Weather Results: {_trim_context(state.get('weather_results', ''))}
Budget Results: {_trim_context(state.get('budget_results', ''))}

Make the itinerary practical, budget aware, and easy to follow.
Create a clear draft that is ready for human review.
"""

    response = _llm_text(
        system_prompt="You are an expert travel planner.",
        user_prompt=prompt
    )

    approval_request = (
        "Please review the generated draft itinerary. Approve it to create the "
        "final polished plan, or provide feedback for revision."
    )

    return {
        'itinerary': _trim_context(response, 2000),
        'approval_request': approval_request,
        'messages': [AIMessage(content="Draft itinerary created for human review.")],
        'llm_calls': state.get('llm_calls',0) + 1
    }

# HUMAN IN THE LOOP APPROVAL
def human_approval_agent(state:TravelState):
    # Do not wrap interrupt() in try/except. LangGraph uses it to pause execution.human_approval_agent

    review = interrupt(
        {
            "question": "Do you approve this itinerary?",
            "draft_itinerary": state.get("itinerary", ""),
            "approval_request": state.get("approval_request", ""),
            "selected_agents": state.get("selected_agents", []),
            "supervisor_reasoning": state.get("supervisor_reasoning", ""),
            "expected_response": {
                "approved": True,
                "feedback": "Optional revision feedback",
            },
        }
    )

    approved = bool(review.get('approved', False))
    human_feedback = str(review.get('feedback', "")).strip()

    return {
        'approved': approved,
        'human_feedback': human_feedback,
        'messages': [AIMessage(content="Human approval step completed")],
    }

# Dynamic Supervisor Routing
ROUTE_MAP = {
    "guardrail_blocked": "guardrail_blocked",
    "flight_agent": "flight_agent",
    "hotel_agent": "hotel_agent",
    "weather_agent": "weather_agent",
    "budget_agent": "budget_agent",
    "itinerary_agent": "itinerary_agent",
}

def _selected_agents(state: TravelState) -> list[str]:
    selected = state.get("selected_agents", [])
    return [agent for agent in AGENT_ORDER if agent in selected]

def route_from_supervisor(state: TravelState):
    if not state.get("guardrail_allowed", True):
        return "guardrail_blocked"
    
    selected  = _selected_agents(state)
    return selected[0] if selected else "itinerary_agent"

def route_after_agent(current_agent: str):
    def route(state: TravelState):
        selected = _selected_agents(state)
        current_index = AGENT_ORDER.index(current_agent)

        for next_agent in AGENT_ORDER[current_index + 1:]:
            if next_agent in selected:
                return next_agent
        
        return "itinerary_agent"
    return route


# FINAL RESPONSE AGENT
def final_agent(state: TravelState):

    if state.get('approved', False):
        review_instruction = f"""
        The user approved the draft. Preserve its decision while polishing it.
        """
    else:
        review_instruction = f"""
The user requested a revision. Apply this feedback carefully:
{state.get('human_feedback', '') or 'Improve the draft before finalizing it.'}
"""

    final_prompt = f"""
Generate the final travel response for the user.

Human Review: {review_instruction}
User Request: {state['user_query']}
Trip Constraints: {state.get('trip_constraints', {})}
Flight: {_trim_context(state.get('flight_results', ''))}
Hotel Results: {_trim_context(state.get('hotel_results', ''))}
Weather Results: {_trim_context(state.get('weather_results', ''))}
Budget Results: {_trim_context(state.get('budget_results', ''))}
Draft_Itinerary: {_trim_context(state.get('itinerary', ''), 1500)}


Format the final answer beautifully using these sections:
1. Trip Summary
2. Flight Information
3. Hotel Suggestions
4. Weather Information
5. Day-by-Day Itinerary
6. Estimated Budget
7. Final Recommendations

Important:
- Be clear and practical.
- Mention that live flight API may not provide ticket prices if pricing is unavailable.
- Include weather-based travel advice.
- Keep the response useful for real travel planning.
- Incorporate the human feedback when revision was requested.
"""
    response = llm.invoke([
            SystemMessage(content='You are a professional AI travel booking assistant'),
            HumanMessage(content=final_prompt)
        ])
    
    return {
        'final_response': response.content,
        'messages': [response],
        'llm_calls': state.get('llm_calls',0) + 1
    }

# BUILD GRAPH
graph = StateGraph(TravelState)

graph.add_node('supervisor', supervisor_agent)
graph.add_node('guardrail_blocked', guardrail_blocked_agent)
graph.add_node('flight_agent', flight_agent)
graph.add_node('hotel_agent', hotel_agent)
graph.add_node('weather_agent', weather_agent)
graph.add_node('budget_agent', budget_agent)
graph.add_node('itinerary_agent', itinerary_agent)
graph.add_node('human_approval', human_approval_agent)
graph.add_node('final_agent', final_agent)

graph.add_edge(START, 'supervisor')
graph.add_conditional_edges('supervisor', route_from_supervisor, ROUTE_MAP)
graph.add_conditional_edges('flight_agent', route_after_agent('flight_agent'), ROUTE_MAP)
graph.add_conditional_edges('hotel_agent', route_after_agent('hotel_agent'), ROUTE_MAP)
graph.add_conditional_edges('weather_agent', route_after_agent('weather_agent'), ROUTE_MAP)
graph.add_conditional_edges('budget_agent', route_after_agent('budget_agent'), ROUTE_MAP)

graph.add_edge('itinerary_agent', 'human_approval')
graph.add_edge('human_approval', 'final_agent')
graph.add_edge('final_agent', END)
graph.add_edge('guardrail_blocked', END)

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


# FastAPI-facing helpers
def _interrupt_payload(result: dict[str, Any]) -> dict[str, Any] | None: 
    interrupts = result.get("__interrupt__", [])
    if not interrupts:
        return None
    
    first_interrupt = interrupts[0]
    payload = getattr(first_interrupt, "value", first_interrupt)
    return payload if isinstance(payload, dict) else {"value": payload}

def _serialize_result(
    result: dict[str, Any],
    thread_id: str,) -> dict[str, Any]:

    messages = result.get("message", [])
    last_message = messages[-1].content if messages else ""
    answer = result.get('final_response') or last_message
    interrupt_payload = _interrupt_payload(result)

    if interrupt_payload:
        answer = interrupt_payload.get("draft_itinerary") or result.get(
            "itinerary", ""
        )
    
    return {
        "thread_id": thread_id,
        "answer": answer,
        "requires_approval": interrupt_payload is not None,
        "approval_request": (
            interrupt_payload.get("approval_request", "")
            if interrupt_payload
            else result.get("approval_request", "")
        ),
        "flight_results": result.get('flight_results', ""),
        "hotel_results": result.get("hotel_results", ""),
        "weather_results": result.get("weather_results", ""),
        "budget_results": result.get("budget_results", ""),
        "itinerary": (
            interrupt_payload.get("draft_itinerary", "")
            if interrupt_payload
            else result.get("itinerary", "")
        ),
        "selected_agents": result.get("selected_agents", []),
        "trip_constraints": result.get("trip_constraints", {}),
        "supervisor_reasoning": result.get("supervisor_reasoning", ""),
        "guardrail_allowed": result.get("guardrail_allowed", True),
        "guardrail_reason": result.get("guardrail_reason", ""),
        "approved": result.get("approved"),
        "human_feedback": result.get("human_feedback", ""),
        "llm_calls": result.get("llm_calls", 0),
    }



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
            "guardrail_allowed": True,
            "guardrail_reason": "",
            "selected_agents": [],
            "trip_constraints": _empty_constraints(),
            "supervisor_reasoning": "",
            "flight_results": "",
            "hotel_results": "",
            "weather_results": "",
            "budget_results": "",
            "itinerary": "",
            "approval_request": "",
            "approved": False,
            "human_feedback": "",
            "final_response": "",
            "llm_calls": 0,
        },
        config=config
    )

    return _serialize_result(result, thread_id)


def resume_travel_agent(
    thread_id: str,
    approved: bool,
    feedback: str = "",
):
    """Resume the paused LangGraph thread after human review."""
    if not thread_id:
        raise ValueError("thread_id is required to resume a travel plan.")

    config = {"configurable": {"thread_id": thread_id}}
    result = travel_graph.invoke(
        Command(
            resume={
                "approved": approved,
                "feedback": feedback.strip(),
            }
        ),
        config=config,
    )

    return _serialize_result(result, thread_id)
