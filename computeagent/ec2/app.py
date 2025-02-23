import json
from tools import start_ec2_instance, stop_ec2_instance, list_ec2_instances_by_name, send_whatsapp_message
from utils import extract_whatsapp_messages, extract_recipient
# import requests

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langchain_core.messages import RemoveMessage
import os


model = ChatOpenAI(model=os.getenv("MODEL_NAME"), temperature=0)
tools = [start_ec2_instance, stop_ec2_instance, list_ec2_instances_by_name, send_whatsapp_message]
tool_node = ToolNode(tools=tools)
model_with_tools  = model.bind_tools(tools)

def delete_messages(state, n=10):
    messages = state["messages"]

    if len(messages) <= n:
        return {"messages": []}  # No deletion needed

    last_to_delete_index = len(messages) - n - 1 # Identify the last message to be deleted
    last_to_delete = messages[last_to_delete_index]

    # If the last message to be deleted is an AIMessage, reduce the index by 1 to keep one extra message
    if isinstance(last_to_delete, AIMessage):
        last_to_delete_index -= 1  # Retain one extra message

    else:  # Handle consecutive ToolMessages
        while last_to_delete_index < len(messages) and isinstance(messages[last_to_delete_index], ToolMessage):
            last_to_delete_index += 1  # Expand deletion to include contiguous ToolMessages

    return {"messages": [RemoveMessage(id=m.id) for m in messages[:last_to_delete_index-1]]}

    
def should_continue(state: MessagesState) -> str:
    last_message = state['messages'][-1]
    if not last_message.tool_calls:
        return "delete_messages"
    return 'tools'

# Function to call the supervisor model
def call_model(state: MessagesState): 
    with open("agent_prompt.txt", "r", encoding="utf-8") as file:
        system_message = file.read()
        messages = state["messages"]
        if not any(isinstance(msg, SystemMessage) for msg in messages):
            # Create and prepend the system message
            system_msg = SystemMessage(content=system_message)
            messages.insert(0, system_msg)
        response = model_with_tools.invoke(messages)
        return {"messages": [response]}

def init_graph():
    with DynamoDBSaver.from_conn_info(table_name="whatsapp_checkpoint") as saver:
        graph = StateGraph(MessagesState)
        graph.add_node("agent", call_model)
        graph.add_node("tools", tool_node)
        graph.add_node(delete_messages)

        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", should_continue, ["tools", "delete_messages"])
        graph.add_edge("tools", "agent")
        graph.add_edge("delete_messages", END)
        app = graph.compile(checkpointer=saver)
        return app

app = init_graph()

def lambda_handler(event, context):

    messages = []
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
                ("human", f"Message recieved from Whatsapp user {recipeint}:  {message}"),
            ]
        }
        response = app.invoke(input_message, config)
        print(response)
        return





