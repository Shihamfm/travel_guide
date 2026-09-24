# Agentic AI Travel Guide System

An enterprise-grade, multi-agent travel planning system designed to streamline complex travel logistics. By leveraging Model Context Protocol (MCP), dynamic supervisor routing, and human-in-the-loop validation, this architecture automates the end-to-end trip planning process while ensuring safety, relevance, and human oversight.

---

## 🎯 Business Problem

Travel planning is notoriously fragmented. Users manually juggle flight aggregators, hotel booking platforms, weather forecasts, and budgeting tools to piece together an itinerary. Traditional conversational bots fail at this because they either lack access to real-time, domain-specific tools or execute rigid, hardcoded workflows that break when trip constraints change.

**The Solution:** 
This Agentic AI setup transitions from static conversational agents to a dynamic, specialized multi-agent architecture. A centralized Supervisor Agent understands the nuanced intent of a user's request, evaluates constraints, and dynamically routes tasks to specialized domain agents (Flight, Hotel, Weather, Budget, Itinerary). These agents execute tasks autonomously via Model Context Protocol (MCP) tool integrations, update a shared state, and compile a comprehensive plan that pauses for human approval before finalization.

---

## 🚀 Key System Architecture & Features

*   **Dynamic Supervisor Agent:** Eliminates rigid, hardcoded workflow DAGs. The supervisor evaluates user intent and dynamically spins up only the necessary specialized agents required for the task.
*   **Model Context Protocol (MCP) Integration:** Pluggable, secure tool access. Specialist agents interface with external data sources (AviationStack for flights, Tavily for hotels, custom API for weather) using standardized MCP endpoints.
*   **Centralized Shared State (`TravelState`):** All agents read from and write to a single source of truth, ensuring the Itinerary Agent is aware of the Budget Agent's constraints and the Flight Agent's scheduled arrivals.
*   **Input Guardrails:** Proactive validation blocks unsafe, irrelevant, or malformed requests *before* incurring LLM or API inference costs.
*   **Human-in-the-Loop (HITL) Checkpoint:** Forces the workflow to pause, allowing users to review the generated itinerary, approve it, or provide natural language feedback to request changes, looping back to the relevant specialist agents.

---
## Diagram of System Architecture

---

![System Architecture](static\image\system_architecture.jpg)


## 🛠️ Prerequisites

To run this project locally, ensure you have the following configured:

* **Python Environment:** Python 3.10 or higher.

* **LLM Access:** Access to Llama 3 (via local Ollama, Groq, or an API provider) to act as the reasoning engine for the Supervisor, Budget, and Itinerary agents.

* **API Keys:** Active developer accounts and API keys for external data tools:

    * AviationStack (Flight Data)
    * Tavily (Search/Hotel Data)
    * Weather (Forecast)

## ⚙️ Installation & Setup
1. Clone the Repository
```
git clone [https://github.com/Shihamfm/travel_guide.git](https://github.com/Shihamfm/travel_guide.git)
cd travel_guide
```

2. Configure Virtual Environment
```
uv init # initiate uv
# change the python version
uv venv # create the virtual environment

# activate the virtual environment
.venv\Scripts\activate
```

3. Install Dependencies
```
uv add -r requriements.txt
```

4. Environment Variables Configuration
Copy the example environment file and populate it with your specific API keys.

```
cp .env.example .env
```
Update .env with:
```
GROQ_API_KEY = "<groq api key>"
AVIATIONSTACK_API_KEY = "<aviation stack api key>"
DEFAULT_ORIGIN_IATA = "<default origin iata>"
TAVILY_API_KEY = "<tavily api key>"
OPENWEATHER_API_KEY = "<open weather api key>"
DATABASE_URL = "<supabase database url>"

LANGSMITH_TRACING=true
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
LANGSMITH_API_KEY= <langsmith_api_key> 
LANGSMITH_PROJECT="travel-agent"    
```

5. Execution
Run the main application to trigger the agentic workflow.
```
python app.py
```
