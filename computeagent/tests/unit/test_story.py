import os
import requests
import base64
import boto3
import json

def create_azure_devops_user_story(title, description):
    """
    Creates a new Azure DevOps user story.
    """
    az_pat = os.getenv("AZ_DEVOPS_PAT")
    sqs_queue_url = os.getenv("LOKI_TO_JARVIS_QUEUE_URL")  # Ensure this is set in the environment variables
    if not az_pat:
        print("Error: AZ_DEVOPS_PAT environment variable not found.")
        return None

    # Encode PAT as Base64 (format: username:PAT)
    auth_header = base64.b64encode(f"'':{az_pat}".encode()).decode()

    url = "https://dev.azure.com/skamalj-org/agent-loki/_apis/wit/workitems/$User%20Story?api-version=7.1"
    headers = {
        "Content-Type": "application/json-patch+json",
        "Authorization": f"Basic {auth_header}"
    }

    payload = [
        {"op": "add", "path": "/fields/System.Title", "value": title},
        {"op": "add", "path": "/fields/System.Description", "value": description},
        {"op": "add", "path": "/fields/System.State", "value": "New"}
    ]

    response = requests.post(url, headers=headers, json=payload)

    if response.status_code == 200 or response.status_code == 201:
        story_data = response.json()
        story_id = story_data.get("id")
        
        if story_id:
            # Send story ID to SQS
            sqs_client = boto3.client("sqs")
            message_body = json.dumps({"story_id": story_id})
            
            sqs_response = sqs_client.send_message(
                QueueUrl=sqs_queue_url,
                MessageBody=message_body
            )
            
            print(f"Story ID {story_id} sent to SQS. Message ID: {sqs_response['MessageId']}")
        
        return story_data
    else:
        print("Failed to create user story:", response.text)
        return None


if __name__ == "__main__":
    create_azure_devops_user_story("Create Lambda Lister", "Create tool to check lambda functions in account")
