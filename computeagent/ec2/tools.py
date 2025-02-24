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
def start_rds_instance(db_instance_identifier):
    """
    Starts an RDS instance with the given identifier.

    :param db_instance_identifier: The identifier of the RDS instance to start.
    :return: A confirmation message indicating the RDS instance has been started.
    """
    rds = boto3.client('rds')
    rds.start_db_instance(DBInstanceIdentifier=db_instance_identifier)
    return f"RDS instance {db_instance_identifier} has been started."

@tool
def stop_rds_instance(db_instance_identifier):
    """
    Stops an RDS instance using the provided identifier.

    :param db_instance_identifier: The identifier of the RDS instance to stop.
    :return: A message indicating the RDS instance has been stopped.
    """
    rds = boto3.client('rds')
    rds.stop_db_instance(DBInstanceIdentifier=db_instance_identifier)
    return f"RDS instance {db_instance_identifier} has been stopped."

@tool
def list_rds_instances():
    """
    Fetches and returns a list of RDS instances with their identifiers and statuses.

    Returns:
        list: A list of dictionaries containing 'DBInstanceIdentifier' and 'DBInstanceStatus'.
    """
    rds = boto3.client('rds')
    response = rds.describe_db_instances()
    instances = []
    for db_instance in response['DBInstances']:
        instance_id = db_instance['DBInstanceIdentifier']
        instance_status = db_instance['DBInstanceStatus']
        instances.append({
            'DBInstanceIdentifier': instance_id,
            'DBInstanceStatus': instance_status
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
    
    url = "https://graph.facebook.com/v22.0/122101510484012147/messages"
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
    ut_end_date = datetime.utcnow()  # Use UTC to match AWS timestamps
    end_date = ut_end_date.strftime("%Y-%m-%d")  # Convert to string
    start_date = (ut_end_date - timedelta(days=days)).strftime("%Y-%m-%d")

    print(f"Fetching AWS billing data from {start_date} to {end_date}...")

    try:
        # Query AWS Cost Explorer
        response = ce.get_cost_and_usage(
            TimePeriod={"Start": start_date, "End": end_date},
            Granularity="DAILY",  # Changed to daily for more accuracy
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}]  # Group by service
        )
    except Exception as e:
        print("Error fetching AWS billing data:", str(e))
        return None

    # Initialize total cost and currency
    total_cost = 0.0
    currency = "USD"  # Default currency

    service_costs = {}

    # Process results
    for period in response.get("ResultsByTime", []):
        for group in period.get("Groups", []):
            service = group["Keys"][0]  # Extract service name
            cost = float(group["Metrics"]["UnblendedCost"]["Amount"])  # Convert cost to float
            currency = group["Metrics"]["UnblendedCost"].get("Unit", currency)  # Get currency
            
            # Aggregate costs for the service
            if service in service_costs:
                service_costs[service] += cost
            else:
                service_costs[service] = cost

            total_cost += cost  # Accumulate total cost

    # Convert dictionary to sorted list
    service_cost_list = [
        {"service": service, "cost": round(cost, 2)}
        for service, cost in sorted(service_costs.items(), key=lambda x: x[1], reverse=True)
    ]

    return {
        "total_cost": round(total_cost, 2),
        "currency": currency,
        "service_costs": service_cost_list,
        "start_date": start_date,
        "end_date": end_date,
    }
