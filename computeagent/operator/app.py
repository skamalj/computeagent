import json
from tools import tool_list
# import requests

from langgraph.graph import StateGraph,  START, END
from langgraph.prebuilt import ToolNode
from langchain_core.messages import SystemMessage,  HumanMessage
from langgraph_dynamodb_checkpoint import DynamoDBSaver
from langgraph_utils import call_model, create_tools_json
import os
from langgraph_reducer import PrunableStateFactory
import boto3

model_name = model=os.getenv("MODEL_NAME")
provider_name = os.getenv("PROVIDER_NAME")
stepfunctions = boto3.client("stepfunctions")

tool_node = ToolNode(tools=tool_list)

    
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
        
        return {"messages": [response]}

def init_graph():
    with DynamoDBSaver.from_conn_info(table_name="whatsapp_checkpoint", max_write_request_units=100,max_read_request_units=100, ttl_seconds=86400) as saver:
        graph = StateGraph(PrunableMessagesState)
        
        graph.add_node("agent", call_gw_model)
        graph.add_node("tools", tool_node)
    
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", should_continue, ["tools", END])
        graph.add_edge("tools", "agent")
       
        app = graph.compile(checkpointer=saver)
        return app

min_number_of_messages_to_keep = int(os.environ.get("MSG_HISTORY_TO_KEEP", 10))
max_number_of_messages_to_keep = int(os.environ.get("DELETE_TRIGGER_COUNT", 15))    
PrunableMessagesState = PrunableStateFactory.create_prunable_state(min_number_of_messages_to_keep, max_number_of_messages_to_keep)   

app = init_graph()

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

def handle_message(channel_type, recipient, message):
    # Step 1: Get profile_id for this user
    profile_id = get_profile_id(recipient)
    if not profile_id:
        print(f"No profile found for user: {recipient}, skipping.")
        return None

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

    return {
        "nextagent": "END",  # or another agent name if chaining
        "message": response["messages"][-1].content,
        "thread_id": profile_id,
        "channel_type": channel_type,
        "from": recipient
    }

def lambda_handler(event, context):
    print("Received event:", json.dumps(event, indent=2))

    # Handle Step Function event with task token
    if "taskToken" in event and "input" in event:
        task_token = event["taskToken"]
        input_data = event["input"]
        channel_type = input_data.get("channel_type")
        recipient = input_data.get("from")
        message = input_data.get("message")

        result = handle_message(channel_type, recipient, message)
        if result:
            stepfunctions.send_task_success(
                taskToken=task_token,
                output=json.dumps(result)
            )
        else:
            stepfunctions.send_task_failure(
                taskToken=task_token,
                error="UserProfileError",
                cause="Missing profile or invalid input."
            )
        return

    # Handle SQS event
    if "Records" in event:
        for record in event["Records"]:
            body = json.loads(record["body"])
            channel_type = body.get("channel_type")
            recipient = body.get("from")
            message = body.get("messages")

            if not all([channel_type, recipient, message]):
                print("Skipping message due to missing fields")
                continue

            handle_message(channel_type, recipient, message)

    return
