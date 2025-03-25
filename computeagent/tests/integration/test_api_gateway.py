# @! create function to call aws api gateway with post request using api key 
#  
import requests
import os
from langchain_core.messages import utils

data = {
    "provider": "openai",    
    "model_name": "gpt-4o",  
    "params": {              
        "temperature": 0.7,
        "max_tokens": 100
    },
     "messages": [{"content": "talk with me about sports", "role": "human"}]
}

api_key = os.environ.get('API_GW_KEY')
api_url = os.environ.get('API_GW_URL')
def call_api_gateway(api_url, api_key, data):
    headers = {
        'x-api-key': api_key,
        'Content-Type': 'application/json'
    }
    response = requests.post(api_url, headers=headers, json=data)
    return response.json()



from langchain_core.messages import  HumanMessage, AIMessage
from langchain_core.tools import tool

from langgraph.prebuilt import ToolNode

@tool
def get_weather(location: str):
    """Call to get the current weather."""
    if location.lower() in ["sf", "san francisco"]:
        return "It's 60 degrees and foggy."
    else:
        return "It's 90 degrees and sunny."

# @! create tool to add two numbers 

@tool
def add_numbers(num1: int, num2: int):
    """Add two numbers."""
    return num1 + num2
@tool

def get_coolest_cities():
    """Get a list of coolest cities"""
    return "nyc, sf"

from langgraph_utils import json_to_structured_tools, create_tools_json
import json
tools = [get_weather, get_coolest_cities, add_numbers]
tool_node = ToolNode(tools)
tools_json = create_tools_json(tools)

data["tools"] = tools_json
data["messages"] = utils.convert_to_openai_messages([HumanMessage(content="What's 27 plus 343 ?", role="human")])
print(data)
print(json_to_structured_tools(tools_json))

response = call_api_gateway(api_url, api_key, data)
print(response)
ai_message = AIMessage(**response)

print(tool_node.invoke({"messages": [ai_message]}))