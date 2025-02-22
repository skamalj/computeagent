# @! create tools, for LLM, to start and stop ec2 instancews. Use langraph annotations to mark these as tools
from langchain_core.tools import tool
from utils import get_secret, extract_recipient
import boto3
import requests

@tool
def start_ec2_instance(instance_id):
    """
    Starts an EC2 instance with the given instance ID.

    :param instance_id: The ID of the EC2 instance to start.
    :return: None
    """ 
    ec2 = boto3.client('ec2')
    ec2.start_instances(InstanceIds=[instance_id])

@tool
def stop_ec2_instance(instance_id):
    """
    Stops an EC2 instance with the given instance ID.
    
    :param instance_id: The ID of the EC2 instance to stop.
    :return: None
    """ 
    ec2 = boto3.client('ec2')
    ec2.stop_instances(InstanceIds=[instance_id])

# @! create tool to list instanceid and instance name basis the supplied string (can be part of a name)

@tool
def list_ec2_instances_by_name(search_string=None):
    """
    Fetches a list of EC2 instances filtered by a name tag.
    If no search string is provided, it returns all instances.

    :param search_string: A string to search for in the instance name (optional).
    :return: A list of dictionaries with instance IDs and names.
    """
    ec2 = boto3.client('ec2')

    # If search_string is provided, use a filter; otherwise, fetch all instances
    filters = [{'Name': 'tag:Name', 'Values': [f'*{search_string}*']}] if search_string else []

    response = ec2.describe_instances(Filters=filters)

    instances = []
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            instance_name = next((tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'), "Unknown")
            instances.append({'InstanceId': instance_id, 'InstanceName': instance_name})

    return instances



@tool
def send_whatsapp_message(recipient, message):
    """
    Sends a WhatsApp message using the Meta API.

    :param recipient: The recipient's phone number.
    :return: The JSON response from the API call.
    """
    access_token = get_secret()  # Fetch token from Secrets Manager
    if not access_token:
        print("Failed to retrieve access token.")
        return None
    
    url = " https://graph.facebook.com/v22.0/122101510484012147/messages"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": message}
    }
    
    response = requests.post(url, headers=headers, json=payload)
    return response.json()

