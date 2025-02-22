import json
import boto3
import json

def extract_whatsapp_messages(body):
    """
    Extracts all WhatsApp text messages from the given JSON body and returns them as a concatenated list.
    
    :param body: The parsed JSON body (dict) from SQS.
    :return: List of extracted text messages.
    """
    messages_list = []
    
    try:
        # Extract the 'entry' field
        entry_list = body.get("entry", [])
        
        for entry in entry_list:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                
                # Get messages list
                messages = value.get("messages", [])
                for message in messages:
                    if message.get("type") == "text":
                        messages_list.append(message["text"]["body"])

    except Exception as e:
        print(f"Error extracting messages: {str(e)}")

    return " ".join(messages_list)  # Concatenate all messages into a single string

SECRET_NAME = "WhatsAppAPIToken"  # Ensure this matches the secret name in AWS

def get_secret():
    """
    Fetches the WhatsApp API token from AWS Secrets Manager.
    """
    client = boto3.client("secretsmanager")
    
    try:
        response = client.get_secret_value(SecretId=SECRET_NAME)
        secret_data = json.loads(response["SecretString"])
        return secret_data.get("ACCESS_TOKEN")
    except Exception as e:
        print(f"Error fetching secret: {e}")
        return None


def extract_recipient(data):
    """
    Extracts the sender phone number from the "from" field in a WhatsApp message received via SQS.

    :param data: JSON object received from SQS
    :return: Sender phone number or None if not found
    """
    try:
        # Navigate through the JSON structure to find the sender's phone number
        entries = data.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                
                for message in messages:
                    sender_number = message.get("from")  # Extract sender number from "from" field
                    if sender_number:
                        return sender_number

        return None  # Return None if sender number is not found

    except (json.JSONDecodeError, TypeError) as e:
        print(f"Error processing JSON: {e}")
        return None
