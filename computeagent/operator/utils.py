import json
import boto3


def get_secret(secret_name):
    """
    Fetches the WhatsApp API token from AWS Secrets Manager.
    """
    client = boto3.client("secretsmanager")
    
    try:
        response = client.get_secret_value(SecretId=secret_name)
        secret_data = json.loads(response["SecretString"])
        return secret_data
    except Exception as e:
        print(f"Error fetching secret: {e}")
        return None


