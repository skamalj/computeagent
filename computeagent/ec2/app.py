import json
from tools import start_ec2_instance, stop_ec2_instance, list_ec2_instances_by_name, send_whatsapp_message, get_billing_data
from tools import list_rds_instances, start_rds_instance, stop_rds_instance, create_azure_devops_user_story
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
tools += [list_rds_instances, start_rds_instance, stop_rds_instance, create_azure_devops_user_story]

tool_node = ToolNode(tools=tools)
model_with_tools  = model.bind_tools(tools)

def print_message_ids(messages):
    for msg in messages:
        if isinstance(msg, AIMessage):
            tool_call_ids = [tc["id"] for tc in msg.tool_calls] if hasattr(msg, "tool_calls") and msg.tool_calls else []
            print(f"AIMessage - ID: {msg.id}, Tool Call IDs: {tool_call_ids}")
        
        elif isinstance(msg, ToolMessage):
            print(f"ToolMessage - ID: {msg.id}, Tool Call ID: {msg.tool_call_id}")

def remove_orphan_ai_messages(state: MessagesState):
    
    # Step 1: Identify orphan tool call IDs and their corresponding AIMessage IDs
    print("Identifying and removing orphan AI messages...")
    messages = state["messages"]
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

def delete_messages(state: MessagesState, n=int(os.getenv("MSG_HISTORY_TO_KEEP"))):
    try:
        messages = state["messages"]

        # Print message IDs for debugging
        print_message_ids(messages)

        if len(messages) <= n:
            return {"messages": []}  # No deletion needed

        messages_to_remove = messages[-n:]  # Messages to remove
        messages_to_keep = messages[:-n]  # Messages to keep

        # Step 1: Collect AIMessage IDs and tool call IDs
        ai_messages = [m for m in messages_to_remove if isinstance(m, AIMessage)]
        ai_message_ids = [m.id for m in ai_messages]  # AIMessage IDs for removal
        tool_call_ids = [
                tc['id'] 
                for msg in ai_messages 
                if hasattr(msg, "tool_calls") and msg.tool_calls 
                for tc in msg.tool_calls
            ]    # Tool call IDs
        print(f"Deleting these AIMessages: {ai_message_ids}, Tool call IDs: {tool_call_ids}")

        # Step 2: Collect tool message IDs by checking tool_call_id
        tool_messages = [m for m in messages if isinstance(m, ToolMessage) and m.tool_call_id in tool_call_ids]
        tool_message_ids = [m.id for m in tool_messages]  # Get IDs of tool messages to remove
        print(f"Deleting these ToolMessages: {tool_message_ids}")

        # Step 3: Identify human messages for removal
        human_messages = [m for m in messages_to_remove if isinstance(m, HumanMessage)]
        human_message_ids = [m.id for m in human_messages]  # Get IDs of human messages to remove

        # Step 4: Ensure all tool calls have corresponding tool messages
        found_tool_call_ids = [m.tool_call_id for m in tool_messages]
        missing_tool_call_ids = set(tool_call_ids) - set(found_tool_call_ids)  # Find missing tool call IDs
        print(f"Tool call IDs: {tool_call_ids}, Found tool call IDs: {found_tool_call_ids}")
        if missing_tool_call_ids:
            print(f"Warning: Missing tool messages for tool call IDs: {missing_tool_call_ids}")

        # Step 5: Collect all message IDs to remove using `+`
        all_ids_to_remove = ai_message_ids + tool_message_ids + human_message_ids  # List concatenation
        print(f"Removing these messages: {all_ids_to_remove}")

        return {"messages": [RemoveMessage(id=m_id) for m_id in all_ids_to_remove]} # Simulating RemoveMessage
    except Exception as e:
        print(f"Error deleting messages: {e}, Total messages {len(messages)}")
        return {"messages": []}
    
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
        system_msg = SystemMessage(content=system_message)

        # Find orphan tool calls with AI message IDs
        find_orphan_tool_calls_with_ai_message_ids(messages)

        if isinstance(messages[0], SystemMessage):
            messages[0]=system_msg
        else:
            messages.insert(0, system_msg)
            
        response = model_with_tools.invoke(messages)
        return {"messages": [response]}

def init_graph():
    with DynamoDBSaver.from_conn_info(table_name="whatsapp_checkpoint") as saver:
        graph = StateGraph(MessagesState)
        graph.add_node("delete_orphan_messages",remove_orphan_ai_messages)
        graph.add_node("agent", call_model)
        graph.add_node("tools", tool_node)
        graph.add_node(delete_messages)

        graph.add_edge(START, "delete_orphan_messages")
        graph.add_edge("delete_orphan_messages", "agent")
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





