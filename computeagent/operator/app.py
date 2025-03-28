import json
from tools import tool_list
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
        return "print_messages_exit"
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

def dummy_state(state):
    messages = state["messages"]
    for i, msg in enumerate(messages):
        print(f"## Final Messages Message: {i}: {msg.content}")

    return {"messages": []}

def init_graph():
    with DynamoDBSaver.from_conn_info(table_name="whatsapp_checkpoint", max_write_request_units=100,max_read_request_units=100) as saver:
        graph = StateGraph(PrunableMessagesState)
        #graph.add_node("delete_orphan_messages",remove_orphan_ai_messages)
        graph.add_node("agent", call_gw_model)
        graph.add_node("tools", tool_node)
        graph.add_node("print_messages_enter", dummy_state)
        graph.add_node("print_messages_exit", dummy_state)
        #.add_node(delete_messages)

        #graph.add_edge(START, "delete_orphan_messages")
        graph.add_edge(START, "print_messages_enter")
        graph.add_edge("print_messages_enter", "agent")
        graph.add_conditional_edges("agent", should_continue, ["tools", "print_messages_exit"])
        graph.add_edge("tools", "agent")
        graph.add_edge("print_messages_exit", END)
        #graph.add_edge("delete_messages", END)
        app = graph.compile(checkpointer=saver)
        return app

min_number_of_messages_to_keep = int(os.environ.get("MSG_HISTORY_TO_KEEP", 10))
max_number_of_messages_to_keep = int(os.environ.get("DELETE_TRIGGER_COUNT", 15))    
PrunableMessagesState = PrunableStateFactory.create_prunable_state(min_number_of_messages_to_keep, max_number_of_messages_to_keep)   

app = init_graph()

import json
import boto3

# Initialize AWS resources
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")  # Change region if needed
table = dynamodb.Table("UserProfiles")

def get_profile_id(userid):
    """Fetch profile_id from DynamoDB using GSI on userid."""
    response = table.query(
        IndexName="UserIdIndex",
        KeyConditionExpression="userid = :uid",
        ExpressionAttributeValues={":uid": userid}
    )
    items = response.get("Items", [])
    return items[0]["profile_id"] if items else None

def get_all_userids_and_channels(profile_id):
    """Fetch all userids and channels associated with the profile_id."""
    response = table.query(
        KeyConditionExpression="profile_id = :pid",
        ExpressionAttributeValues={":pid": profile_id}
    )
    items = response.get("Items", [])
    return [(item["userid"], item["channel"]) for item in items]

def lambda_handler(event, context):
    for record in event["Records"]:
        body = json.loads(record["body"])  # SQS message body

        # Extract required fields
        channel_type = body.get("channel_type")  # WhatsApp, Email, etc.
        recipient = body.get("from")  # User ID (userid)
        message = body.get("messages")  # User's query

        # Validate required fields
        if not all([channel_type, recipient, message]):
            print("Skipping message due to missing fields")
            continue  # Skip this record

        # Step 1: Get profile_id for this user
        profile_id = get_profile_id(recipient)
        if not profile_id:
            print(f"No profile found for user: {recipient}, skipping.")
            continue

        # Step 2: Get all associated userids & channels
        user_profiles = get_all_userids_and_channels(profile_id)

        # Format profiles for the prompt
        profile_info = "\n".join(
            [f"- UserID: {uid}, Channel: {ch}" for uid, ch in user_profiles]
        )

        print(f"User Profiles for {recipient}: \n{profile_info}")

        # Step 3: Construct the prompt
        prompt = (
            f"The following user has sent a message:\n"
            f"- UserID: {recipient}\n"
            f"- Message: {message}\n"
            f"- Sent via: {channel_type}\n\n"
            f"Here are all associated user profiles:\n"
            f"{profile_info}\n\n"
            f"Respond to user queries either on the originating channel or on the channel explicitly specified in the request.."
        )

        input_message = {
            "messages": [HumanMessage(prompt)],
        }

        config = {"configurable": {"thread_id": profile_id}}
        response = app.invoke(input_message, config)

        print("Response:", response)

    return
