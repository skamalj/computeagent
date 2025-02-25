import json
from tools import start_ec2_instance, stop_ec2_instance, list_ec2_instances_by_name, send_whatsapp_message, get_billing_data
from tools import list_rds_instances, start_rds_instance, stop_rds_instance
from utils import extract_whatsapp_messages, extract_recipient
# import requests

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph, MessagesState, START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langchain_core.messages import RemoveMessage
import os


model = ChatOpenAI(model=os.getenv("MODEL_NAME"), temperature=0)
tools = [start_ec2_instance, stop_ec2_instance, list_ec2_instances_by_name, send_whatsapp_message, get_billing_data]
tools += [list_rds_instances, start_rds_instance, stop_rds_instance]

tool_node = ToolNode(tools=tools)
model_with_tools  = model.bind_tools(tools)

def delete_messages(state, n=6):
    messages = state["messages"]

    if len(messages) <= n:
        return {"messages": []}  # No deletion needed

    messages_to_keep = messages[-n:]  # Keep last `n` messages
    messages_to_remove = messages[:-n]  # Messages to be removed

    # Step 1: Collect AIMessage IDs and tool call IDs
    ai_messages = [m for m in messages_to_remove if isinstance(m, AIMessage)]
    ai_message_ids = [m.id for m in ai_messages]  # AIMessage IDs for removal
    tool_call_ids = [
            tc.id 
            for msg in ai_messages 
            if hasattr(msg, "tool_calls") and msg.tool_calls 
            for tc in msg.tool_calls
        ]    # Tool call IDs

    # Step 2: Collect tool message IDs by checking tool_call_id
    tool_messages = [m for m in messages_to_remove if isinstance(m, ToolMessage) and m.tool_call_id in tool_call_ids]
    tool_message_ids = [m.id for m in tool_messages]  # Get IDs of tool messages to remove

    # Step 3: Identify human messages for removal
    human_messages = [m for m in messages_to_remove if isinstance(m, HumanMessage)]
    human_message_ids = [m.id for m in human_messages]  # Get IDs of human messages to remove

    # Step 4: Ensure all tool calls have corresponding tool messages
    found_tool_call_ids = [m.tool_call_id for m in tool_messages]
    missing_tool_call_ids = set(tool_call_ids) - set(found_tool_call_ids)  # Find missing tool call IDs
    if missing_tool_call_ids:
        print(f"Warning: Missing tool messages for tool call IDs: {missing_tool_call_ids}")

    # Step 5: Collect all message IDs to remove using `+`
    all_ids_to_remove = ai_message_ids + tool_message_ids + human_message_ids  # List concatenation

    return {"messages": [RemoveMessage(id=m_id) for m_id in all_ids_to_remove]} # Simulating RemoveMessage

    
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





