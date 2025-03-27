import json
from tools import tool_list
from utils import extract_whatsapp_messages, extract_recipient
# import requests

from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph,  START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langchain_core.messages import RemoveMessage
from langgraph_utils import call_model, create_tools_json
import os
from prunablemessagestate import PrunableStateFactory

model_name = model=os.getenv("MODEL_NAME")
provider_name = os.getenv("PROVIDER_NAME")

model = ChatOpenAI(model=model_name, temperature=0)
tool_node = ToolNode(tools=tool_list)
model_with_tools  = model.bind_tools(tool_list)

def print_message_ids(messages):
    for msg in messages:
        if isinstance(msg, AIMessage):
            tool_call_ids = [tc["id"] for tc in msg.tool_calls] if hasattr(msg, "tool_calls") and msg.tool_calls else []
            print(f"AIMessage - ID: {msg.id}, Tool Call IDs: {tool_call_ids}, Content: {msg.content}")
        
        elif isinstance(msg, ToolMessage):
            print(f"ToolMessage - ID: {msg.id}, Tool Call ID: {msg.tool_call_id}")

def remove_orphan_ai_messages(state):
    
    # Step 1: Identify orphan tool call IDs and their corresponding AIMessage IDs
    print("Identifying and removing orphan AI messages...")
    messages = state["messages"]
    print_message_ids(messages)
    orphan_tool_calls = find_orphan_tool_calls_with_ai_message_ids(messages)
    orphan_ai_message_ids = set(orphan_tool_calls.values())  # AIMessage IDs to remove

    # Step 2: Prepare RemoveMessage instances for orphan AI messages
    remove_messages = [RemoveMessage(id=ai_id) for ai_id in orphan_ai_message_ids]

    print(f"Packing orphan AI messages for removal: {orphan_ai_message_ids}")
    return {"messages": remove_messages}

def find_orphan_tool_calls_with_ai_message_ids(messages):
    """
    Identifies orphan tool call IDs that exist in AIMessage but do not have a corresponding ToolMessage.
    Also returns the AIMessage IDs that contain these orphan tool calls.

    Args:
        messages (list): List of messages, including AIMessage and ToolMessage instances.

    Returns:
        dict: Mapping of orphan tool call IDs to their corresponding AIMessage IDs.
    """
    print("Finding orphan tool calls with AI message IDs...")
    # Step 1: Collect tool call IDs and their parent AIMessage IDs
    tool_calls_map = {
        tc["id"]: msg.id
        for msg in messages
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls
        for tc in msg.tool_calls
    }

    # Step 2: Collect tool call IDs that have a response (from ToolMessage)
    responded_tool_call_ids = {
        msg.tool_call_id for msg in messages if isinstance(msg, ToolMessage)
    }

    # Step 3: Identify orphan tool call IDs (missing responses)
    orphan_tool_calls = {
        tc_id: ai_msg_id
        for tc_id, ai_msg_id in tool_calls_map.items()
        if tc_id not in responded_tool_call_ids
    }

    if orphan_tool_calls:
        print(f"Orphan Tool Call IDs and their AIMessage IDs: {orphan_tool_calls}")
    else:
        print("No orphan tool call IDs found.")

    return orphan_tool_calls
    
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

        # Find orphan tool calls with AI message IDs
        find_orphan_tool_calls_with_ai_message_ids(messages)

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
        graph.add_node("delete_orphan_messages",remove_orphan_ai_messages)
        graph.add_node("agent", call_gw_model)
        graph.add_node("tools", tool_node)
        #.add_node(delete_messages)

        graph.add_edge(START, "delete_orphan_messages")
        graph.add_edge("delete_orphan_messages", "agent")
        graph.add_conditional_edges("agent", should_continue, ["tools", END])
        graph.add_edge("tools", "agent")
        #graph.add_edge("delete_messages", END)
        app = graph.compile(checkpointer=saver)
        return app
    
PrunableMessagesState = PrunableStateFactory.create_prunable_state(10, 15)   

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
        messages = app.get_state(config).values.get("messages", [])
        if len(messages) > 10:
            app.update_state(config, {"messages": [RemoveMessage(id=m.id) for m in messages[1:6]]})
        print(f"Message recieved from {recipeint}:  {message}")
        input_message = {
            "messages": [
                ("human", f"Message recieved from Whatsapp user {recipeint}:  {message}"),
            ]
        }
        response = app.invoke(input_message, config)
        print(response)
        return





