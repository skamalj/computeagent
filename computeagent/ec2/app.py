import json
from tools import tool_list
from utils import extract_whatsapp_messages, extract_recipient
# import requests

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph,  START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage,  HumanMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langgraph_utils import call_model, create_tools_json
import os
from prunablemessagestate import PrunableStateFactory

model_name = model=os.getenv("MODEL_NAME")
provider_name = os.getenv("PROVIDER_NAME")

model = ChatOpenAI(model=model_name, temperature=0)
tool_node = ToolNode(tools=tool_list)
model_with_tools  = model.bind_tools(tool_list)
    
def should_continue(state) -> str:
    last_message = state['messages'][-1]
    if not last_message.tool_calls:
        return END
    return 'tools'

# Function to call the supervisor model
def call_gw_model(state): 
    with open("agent_prompt.txt", "r", encoding="utf-8") as file:
        system_message = file.read()
        messages = state["messages"]
        system_msg = SystemMessage(content=system_message)

        if isinstance(messages[0], SystemMessage):
            messages[0]=system_msg
        else:
            messages.insert(0, system_msg)

        json_tools = create_tools_json(tool_list)
        response = call_model(model_name, provider_name, messages, json_tools)
        #response = model_with_tools.invoke(messages)
        return {"messages": [response]}

def init_graph():
    with DynamoDBSaver.from_conn_info(table_name="whatsapp_checkpoint", max_write_request_units=100,max_read_request_units=100) as saver:
        graph = StateGraph(PrunableMessagesState)
        #graph.add_node("delete_orphan_messages",remove_orphan_ai_messages)
        graph.add_node("agent", call_gw_model)
        graph.add_node("tools", tool_node)
        #.add_node(delete_messages)

        #graph.add_edge(START, "delete_orphan_messages")
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", should_continue, ["tools", END])
        graph.add_edge("tools", "agent")
        #graph.add_edge("delete_messages", END)
        app = graph.compile(checkpointer=saver)
        return app

min_number_of_messages_to_keep = int(os.environ.get("MSG_HISTORY_TO_KEEP", 10))
max_number_of_messages_to_keep = int(os.environ.get("DELETE_TRIGGER_COUNT", 15))    
PrunableMessagesState = PrunableStateFactory.create_prunable_state(min_number_of_messages_to_keep, max_number_of_messages_to_keep)   

app = init_graph()

def lambda_handler(event, context):

    
    for record in event["Records"]:
        body = json.loads(record["body"])  # SQS message body

        # Ignore delivery status updates
        changes = body.get("entry", [])[0].get("changes", [])
        for change in changes:
            value = change.get("value", {})
            if "statuses" in value:  # If it's a delivery status, ignore it
                print("Received delivery status update, ignoring...")
                return
                
        message = extract_whatsapp_messages(body)
        recipeint = extract_recipient(body)
        config = {"configurable": {"thread_id": recipeint}}
        print(f"Message recieved from {recipeint}:  {message}")
        input_message = {
            "messages": [
                HumanMessage(f"Message recieved from Whatsapp user {recipeint}:  {message}"),
            ]
        }
        response = app.invoke(input_message, config)
        print(response)
        return





