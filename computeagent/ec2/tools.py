# @! create tools, for LLM, to start and stop ec2 instancews. Use langraph annotations to mark these as tools
from langchain_core.tools import tool
from utils import get_secret, extract_recipient
import boto3
import requests
from datetime import datetime, timedelta

@tool
def start_ec2_instance(instance_id):
    """
    Starts an EC2 instance with the given instance ID.

    :param instance_id: The ID of the EC2 instance to start.
    :return: None
    """ 
    ec2 = boto3.client('ec2')
    ec2.start_instances(InstanceIds=[instance_id])
    return f"Instance {instance_id} has been started."

@tool
def stop_ec2_instance(instance_id):
    """
    Stops an EC2 instance with the given instance ID.
    
    :param instance_id: The ID of the EC2 instance to stop.
    :return: None
    """ 
    ec2 = boto3.client('ec2')
    ec2.stop_instances(InstanceIds=[instance_id])
    return f"Instance {instance_id} has been stopped."

# @! create tool to list instanceid and instance name basis the supplied string (can be part of a name)

@tool
def list_ec2_instances_by_name():
    """
    Fetches a list of EC2 instances with their instance IDs, names, and current status.

    :return: A list of dictionaries with instance IDs, names, and current status.
    """
    ec2 = boto3.client('ec2')

    response = ec2.describe_instances()

    instances = []
    for reservation in response['Reservations']:
        for instance in reservation['Instances']:
            instance_id = instance['InstanceId']
            instance_name = next((tag['Value'] for tag in instance.get('Tags', []) if tag['Key'] == 'Name'), "Unknown")
            instance_state = instance['State']['Name']  # Fetching instance status
            instances.append({
                'InstanceId': instance_id,
                'InstanceName': instance_name,
                'InstanceState': instance_state
            })

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

@tool
def get_billing_data(days: int = 30):
    """
    Fetches AWS billing data for the given period and provides a full cost breakdown.
    :param days: Number of days in the past to analyze.
    :return: Structured billing data.
    """
    ce = boto3.client('ce')
    # Define date range
    ut_end_date = datetime.now()  # Keep as datetime object
    end_date = ut_end_date.strftime("%Y-%m-%d")  # Convert to string after formatting
    start_date = (ut_end_date - timedelta(days=days)).strftime("%Y-%m-%d")  # Subtract first, then format


    # Query total cost grouped by service
    response = ce.get_cost_and_usage(
        TimePeriod={"Start": str(start_date), "End": str(end_date)},
        Granularity="MONTHLY",
        Metrics=["UnblendedCost"],
        GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}]  # Group by service
    )

    # Extract total cost and currency
    total_cost = 0.0
    currency = "USD"  # Default currency (AWS usually returns USD)
    
    if "Total" in response["ResultsByTime"][0]:
        for metric_key, metric_data in response["ResultsByTime"][0]["Total"].items():
            if "Amount" in metric_data:
                total_cost += float(metric_data["Amount"])
            if "Unit" in metric_data:
                currency = metric_data["Unit"]

    # Extract cost breakdown by service
    cost_data = response["ResultsByTime"][0].get("Groups", [])
    service_costs = [
        {"service": item["Keys"][0], "cost": round(float(item["Metrics"]["UnblendedCost"]["Amount"]), 2)}
        for item in cost_data if "UnblendedCost" in item["Metrics"]
    ]

    return {
        "total_cost": round(total_cost, 2),
        "currency": currency,
        "service_costs": service_costs,  # Pass all service data to LLM
        "start_date": str(start_date),
        "end_date": str(end_date),
    }
