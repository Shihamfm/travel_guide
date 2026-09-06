from tools.tavily_tool import tavily_research 


if __name__ == "__main__":
    result = tavily_research("Best hotels in Sri Lanka")
    print(result)