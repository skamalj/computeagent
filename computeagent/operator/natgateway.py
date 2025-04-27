import boto3
import time

def find_vpc_by_name(ec2_resource, vpc_name_tag):
    vpcs = list(ec2_resource.vpcs.filter(Filters=[{'Name': 'tag:Name', 'Values': [vpc_name_tag]}]))
    if not vpcs:
        raise Exception(f"VPC with Name tag '{vpc_name_tag}' not found.")
    return vpcs[0]

def find_internet_gateway(client, vpc_id):
    igws = client.describe_internet_gateways(Filters=[{'Name': 'attachment.vpc-id', 'Values': [vpc_id]}])['InternetGateways']
    if not igws:
        raise Exception(f"No Internet Gateway attached to VPC '{vpc_id}'.")
    return igws[0]['InternetGatewayId']

def classify_subnets(ec2_client, subnets, igw_id):
    public_subnets = []
    private_subnets = []
    for subnet in subnets:
        route_tables = ec2_client.describe_route_tables(Filters=[{'Name': 'association.subnet-id', 'Values': [subnet.id]}])['RouteTables']
        if not route_tables:
            continue
        routes = route_tables[0]['Routes']
        if any(route.get('GatewayId') == igw_id for route in routes):
            public_subnets.append(subnet)
        else:
            private_subnets.append(subnet)
    return public_subnets, private_subnets

def find_existing_nat_gateway(client, vpc_id):
    response = client.describe_nat_gateways(
        Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]
    )
    nat_gateways = response['NatGateways']

    for ngw in nat_gateways:
        if ngw['State'] == 'available':
            return ngw['NatGatewayId']

    # None found
    return None

def create_nat_gateway(client, public_subnet_id):
    print(f"Allocating Elastic IP for NAT Gateway...")
    eip = client.allocate_address(Domain='vpc')
    allocation_id = eip['AllocationId']
    
    print(f"Creating NAT Gateway in subnet {public_subnet_id}...")
    response = client.create_nat_gateway(SubnetId=public_subnet_id, AllocationId=allocation_id)
    natgw_id = response['NatGateway']['NatGatewayId']
    
    print(f"Waiting for NAT Gateway {natgw_id} to become available...")
    waiter = client.get_waiter('nat_gateway_available')
    waiter.wait(NatGatewayIds=[natgw_id])
    
    print(f"NAT Gateway {natgw_id} is now available.")
    return natgw_id

def update_private_subnet_routes(client, natgw_id, private_subnets):
    updated_subnets = []
    for subnet in private_subnets:
        route_tables = client.describe_route_tables(Filters=[{'Name': 'association.subnet-id', 'Values': [subnet.id]}])['RouteTables']
        if not route_tables:
            continue
        route_table_id = route_tables[0]['RouteTableId']

        # Check if a default route exists
        routes = route_tables[0]['Routes']
        existing_default_route = any(route.get('DestinationCidrBlock') == '0.0.0.0/0' for route in routes)
        
        if existing_default_route:
            print(f"Replacing default route for private subnet {subnet.id}...")
            client.replace_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock='0.0.0.0/0',
                NatGatewayId=natgw_id
            )
        else:
            print(f"Creating default route for private subnet {subnet.id}...")
            client.create_route(
                RouteTableId=route_table_id,
                DestinationCidrBlock='0.0.0.0/0',
                NatGatewayId=natgw_id
            )
        updated_subnets.append(subnet.id)
    return updated_subnets

def create_nat_gateway_for_vpc_name(vpc_name_tag: str):
    """
    Creates a NAT Gateway in the public subnet of a VPC identified by its 'Name' tag.
    Also updates route tables of private subnets to use the created NAT Gateway.
    """
    ec2 = boto3.resource('ec2')
    client = boto3.client('ec2')

    print(f"Locating VPC '{vpc_name_tag}'...")
    vpc = find_vpc_by_name(ec2, vpc_name_tag)

    print(f"Finding Internet Gateway for VPC {vpc.id}...")
    igw_id = find_internet_gateway(client, vpc.id)

    print(f"Classifying subnets for VPC {vpc.id}...")
    subnets = list(vpc.subnets.all())
    public_subnets, private_subnets = classify_subnets(client, subnets, igw_id)

    if not public_subnets:
        raise Exception(f"No public subnets found in VPC '{vpc_name_tag}'.")

    public_subnet = public_subnets[0]  # Pick the first public subnet

    print(f"Checking for existing NAT Gateway in VPC {vpc.id}...")
    natgw_id = find_existing_nat_gateway(client, vpc.id)

    if natgw_id:
        print(f"Existing NAT Gateway '{natgw_id}' found, reusing it.")
    else:
        natgw_id = create_nat_gateway(client, public_subnet.id)

    print(f"Updating private subnets to route through NAT Gateway '{natgw_id}'...")
    updated_private_subnets = update_private_subnet_routes(client, natgw_id, private_subnets)

    print("NAT Gateway setup completed successfully.")

    return {
        'NatGatewayId': natgw_id,
        'SubnetId': public_subnet.id,
        'PrivateSubnetsUpdated': updated_private_subnets
    }

def find_nat_gateways_for_vpc(client, vpc_id):
    nat_gateways = client.describe_nat_gateways(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}])['NatGateways']
    return nat_gateways

def delete_nat_gateway(client, nat_gateway_id):
    print(f"Deleting NAT Gateway {nat_gateway_id}...")
    client.delete_nat_gateway(NatGatewayId=nat_gateway_id)

def wait_for_natgw_deletion(client, nat_gateway_id, timeout=600):
    print(f"Waiting for NAT Gateway {nat_gateway_id} to be deleted...")
    start_time = time.time()
    while True:
        try:
            response = client.describe_nat_gateways(NatGatewayIds=[nat_gateway_id])
            state = response['NatGateways'][0]['State']
            if state == 'deleted':
                print(f"NAT Gateway {nat_gateway_id} deleted successfully.")
                break
            elif state == 'deleting':
                time.sleep(10)
            else:
                raise Exception(f"NAT Gateway {nat_gateway_id} in unexpected state: {state}")
        except client.exceptions.ClientError as e:
            if 'InvalidNatGatewayID.NotFound' in str(e):
                print(f"NAT Gateway {nat_gateway_id} not found (already deleted).")
                break
            else:
                raise
        if time.time() - start_time > timeout:
            raise TimeoutError(f"Timeout waiting for NAT Gateway {nat_gateway_id} to be deleted.")

def delete_all_available_nat_gateways_for_vpc_name(vpc_name_tag: str):
    """
    Deletes all 'available' NAT Gateways associated with a VPC identified by its 'Name' tag.
    """
    ec2 = boto3.resource('ec2')
    client = boto3.client('ec2')

    print(f"Locating VPC '{vpc_name_tag}'...")
    vpc = find_vpc_by_name(ec2, vpc_name_tag)

    print(f"Finding NAT Gateways in VPC {vpc.id}...")
    nat_gateways = find_nat_gateways_for_vpc(client, vpc.id)

    to_delete = [ngw for ngw in nat_gateways if ngw['State'] == 'available']

    if not to_delete:
        print(f"No 'available' NAT Gateways to delete in VPC {vpc.id}.")
        return {'DeletedNatGateways': []}

    deleted_natgws = []
    for ngw in to_delete:
        natgw_id = ngw['NatGatewayId']
        delete_nat_gateway(client, natgw_id)
        wait_for_natgw_deletion(client, natgw_id)
        deleted_natgws.append(natgw_id)

    print("All 'available' NAT Gateways deleted successfully.")

    return {
        'DeletedNatGateways': deleted_natgws
    }

#create_nat_gateway_for_vpc_name("mcp-vpc")
delete_all_available_nat_gateways_for_vpc_name("mcp-vpc")
