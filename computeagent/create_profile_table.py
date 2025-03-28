import boto3

# Initialize DynamoDB client
dynamodb = boto3.client("dynamodb", region_name="ap-south-1")  # Change region if needed

table_name = "UserProfiles"

#Create table with new column "channel"
#response = dynamodb.create_table(
#    TableName=table_name,
#    AttributeDefinitions=[
#        {"AttributeName": "profile_id", "AttributeType": "S"},  # Primary Key
#        {"AttributeName": "userid", "AttributeType": "S"}  # GSI Attribute
#    ],
#    KeySchema=[
#            {"AttributeName": "profile_id", "KeyType": "HASH"},
#            {"AttributeName": "userid", "KeyType": "RANGE"}
#        ],
#    ProvisionedThroughput={"ReadCapacityUnits": 50, "WriteCapacityUnits": 50},
#    GlobalSecondaryIndexes=[
#        {
#            "IndexName": "UserIdIndex",
#            "KeySchema": [{"AttributeName": "userid", "KeyType": "HASH"}],
#            "Projection": {"ProjectionType": "ALL"},
#            "ProvisionedThroughput": {"ReadCapacityUnits": 50, "WriteCapacityUnits": 50}
#        }
#    ]
#)

#print("Table created:", response)
# Initialize DynamoDB resource
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
table = dynamodb.Table("UserProfiles")

def add_user(profile_id, userid, channel):
    response = table.put_item(
        Item={
            "profile_id": profile_id,
            "userid": userid,
            "channel": channel  # New column
        }
    )
    print("Item added:", response)


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

