import argparse
import boto3
import urllib.request
import socket
import os
import sys
import time
import math
from datetime import datetime
from botocore.exceptions import ClientError


def get_my_public_ip():
    """ადგენს მომხმარებლის გარე (Public) IP მისამართს"""
    try:
        with urllib.request.urlopen('https://checkip.amazonaws.com', timeout=5) as response:
            ip = response.read().decode('utf-8').strip()
            return f"{ip}/32"
    except Exception as e:
        print(f"❌ ვერ მოხერხდა Public IP-ის ავტომატური დადგენა: {e}")
        print("გთხოვთ გამოიყენოთ --custom-ssh-ip პარამეტრი.")
        sys.exit(1)


def validate_network(ec2_client, vpc_id, subnet_id):
    """ამოწმებს არსებობს თუ არა VPC და Subnet, ასევე ეკუთვნის თუ არა Subnet მოცემულ VPC-ს"""
    print("მდგომარეობის შემოწმება (VPC & Subnet Validation)...")
    try:
        ec2_client.describe_vpcs(VpcIds=[vpc_id])

        subnet_response = ec2_client.describe_subnets(SubnetIds=[subnet_id])
        actual_vpc_id = subnet_response['Subnets'][0]['VpcId']

        if actual_vpc_id != vpc_id:
            print(f"❌ შეცდომა: Subnet ({subnet_id}) არ ეკუთვნის მითითებულ VPC-ს ({vpc_id}).")
            sys.exit(1)

        print("✅ ქსელის კონფიგურაცია ვალიდურია.")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidVpcID.NotFound':
            print(f"❌ შეცდომა: VPC ID '{vpc_id}' არ არსებობს.")
        elif error_code == 'InvalidSubnetID.NotFound':
            print(f"❌ შეცდომა: Subnet ID '{subnet_id}' არ არსებობს.")
        else:
            print(f"❌ AWS ინფრასტრუქტურის შემოწმების შეცდომა: {e}")
        sys.exit(1)


def get_latest_amazon_linux_3(ssm_client):
    """მოიძიებს უახლესი Amazon Linux 2023 (AL3) AMI-ს SSM პარამეტრებიდან"""
    print("უახლესი Amazon Linux 2023 AMI-ის მოძიება...")
    try:
        response = ssm_client.get_parameter(
            Name='/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-6.1-x86_64'
        )
        ami_id = response['Parameter']['Value']
        print(f"✅ იდენტიფიცირებულია AMI: {ami_id}")
        return ami_id
    except ClientError as e:
        print(f"❌ უახლესი AMI-ის ძიება ვერ მოხერხდა: {e}")
        sys.exit(1)


def setup_key_pair(ec2_client, key_name):
    """ქმნის Key Pair-ს და ადებს შესაბამის (0400) ფაილის უფლებებს"""
    filename = f"{key_name}.pem"
    try:
        response = ec2_client.create_key_pair(KeyName=key_name)
        private_key = response['KeyMaterial']

        with open(filename, 'w') as file:
            file.write(private_key)

        os.chmod(filename, 0o400)
        print(f"✅ Key Pair შეიქმნა. ფაილი შენახულია: {filename} (0400 Permissions).")
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidKeyPair.Duplicate':
            print(f"⚠️ Key Pair სახელად '{key_name}' უკვე არსებობს. გამოვიყენებთ არსებულს.")
        else:
            print(f"❌ Key Pair-ის შექმნა ვერ მოხერხდა: {e}")
            sys.exit(1)


def setup_security_group(ec2_client, vpc_id, sg_name, ssh_ip):
    """ქმნის ახალ უსაფრთხოების ჯგუფს და ამატებს 22-ე პორტის წესს მოწოდებული IP-დან"""
    print(f"Security Group-ის შექმნა (SSH დაშვებულია: {ssh_ip})...")
    try:
        response = ec2_client.create_security_group(
            GroupName=sg_name,
            Description="CLI created SG for SSH and MySQL access",
            VpcId=vpc_id
        )
        sg_id = response['GroupId']

        ec2_client.authorize_security_group_ingress(
            GroupId=sg_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': ssh_ip, 'Description': 'SSH Access'}]
                },
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 3306,
                    'ToPort': 3306,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0', 'Description': 'MySQL Access'}]
                }
            ]
        )
        print(f"✅ Security Group შეიქმნა. ID: {sg_id}")
        return sg_id
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'InvalidGroup.Duplicate':
            print(f"⚠️ Security Group სახელად '{sg_name}' უკვე არსებობს.")
            sgs = ec2_client.describe_security_groups(
                Filters=[
                    {'Name': 'group-name', 'Values': [sg_name]},
                    {'Name': 'vpc-id', 'Values': [vpc_id]}
                ]
            )
            sg_id = sgs['SecurityGroups'][0]['GroupId']
            print(f"ვიყენებთ არსებულ Security Group-ს. ID: {sg_id}")
            return sg_id
        else:
            print(f"❌ Security Group-ის შექმნა ვერ მოხერხდა: {e}")
            sys.exit(1)


def wait_and_check_ssh(ip_address, port=22, timeout=60):
    """დაელოდება და შეამოწმებს პორტზე კავშირის ხელმისაწვდომობას socket-ის გამოყენებით"""
    print(f"პორტ {port}-ზე კავშირის შემოწმება (IP: {ip_address})...")
    start_time = time.time()

    while True:
        try:
            with socket.create_connection((ip_address, port), timeout=3):
                print(f"✅ პორტი ({port}) ღიაა და კავშირი დადასტურებულია.")
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            if time.time() - start_time > timeout:
                print(f"❌ დრო ამოიწურა! {port}-ე პორტთან დაკავშირება ვერ მოხერხდა.")
                return False
            time.sleep(5)


def create_rds_instance(rds_client, sg_id, db_id, db_user, db_pass):
    """ქმნის RDS MySQL ინსტანსს მითითებული პარამეტრებით"""
    print("\nRDS Instance-ის (MySQL) შექმნა...")
    try:
        response = rds_client.create_db_instance(
            DBInstanceIdentifier=db_id,
            AllocatedStorage=60,
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername=db_user,
            MasterUserPassword=db_pass,
            VpcSecurityGroupIds=[sg_id],
            PubliclyAccessible=True
        )
        print(f"✅ RDS ინსტანსის შექმნა დაიწყო. ID: {db_id}")
        return response['DBInstance']
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'DBInstanceAlreadyExists':
            print(f"⚠️ RDS ინსტანსი სახელად '{db_id}' უკვე არსებობს.")
        else:
            print(f"❌ RDS-ის შექმნა ვერ მოხერხდა: {e}")
            sys.exit(1)


def wait_for_rds(rds_client, db_id):
    """ელოდება RDS-ის available სტატუსს და აბრუნებს Endpoint-ს"""
    print("ველოდებით RDS ინსტანსის გააქტიურებას (ეს შეიძლება 5-10 წუთი გაგრძელდეს)...")
    try:
        waiter = rds_client.get_waiter('db_instance_available')
        waiter.wait(DBInstanceIdentifier=db_id, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})

        response = rds_client.describe_db_instances(DBInstanceIdentifier=db_id)
        endpoint = response['DBInstances'][0]['Endpoint']['Address']
        port = response['DBInstances'][0]['Endpoint']['Port']
        print(f"✅ RDS ინსტანსი გააქტიურებულია! Endpoint: {endpoint}:{port}")
        return endpoint, port
    except ClientError as e:
        print(f"❌ RDS-ის ინფორმაციის წამოღება ვერ მოხერხდა: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────
# ახალი ფუნქციონალი: storage scaling, DynamoDB listing, manual snapshot
# ──────────────────────────────────────────────────────────────────────────

def get_current_allocated_storage(rds_client, db_id):
    """წამოიღებს RDS ინსტანსის მიმდინარე AllocatedStorage-ს (GB)"""
    try:
        response = rds_client.describe_db_instances(DBInstanceIdentifier=db_id)
        return response['DBInstances'][0]['AllocatedStorage']
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'DBInstanceNotFound':
            print(f"❌ RDS ინსტანსი '{db_id}' ვერ მოიძებნა.")
        else:
            print(f"❌ RDS ინსტანსის ინფორმაციის წამოღება ვერ მოხერხდა: {e}")
        sys.exit(1)


def increase_rds_storage(rds_client, db_id, percent):
    """zრდის RDS ინსტანსის storage-ს მითითებული პროცენტით (default 25%)"""
    current_storage = get_current_allocated_storage(rds_client, db_id)
    new_storage = math.ceil(current_storage * (1 + percent / 100))

    if new_storage <= current_storage:
        new_storage = current_storage + 1  # AWS-ს მინიმუმ მთელი GB ნამატი სჭირდება

    print(f"მიმდინარე storage: {current_storage} GB → ახალი storage: {new_storage} GB (+{percent}%)")

    try:
        rds_client.modify_db_instance(
            DBInstanceIdentifier=db_id,
            AllocatedStorage=new_storage,
            ApplyImmediately=True
        )
        print(f"✅ Storage-ის გაზრდა დაიწყო ({current_storage}GB → {new_storage}GB).")
        print("⚠️ შენიშვნა: AWS-ში ეს ცვლილება ფონურ რეჟიმში სრულდება (რამდენიმე წუთიდან საათამდე)")
        print("   და მომდევნო 6 საათის განმავლობაში storage-ის ხელახალი მოდიფიკაცია არ დაიშვება.")
    except ClientError as e:
        print(f"❌ Storage-ის მოდიფიკაცია ვერ მოხერხდა: {e}")
        sys.exit(1)


def list_dynamodb_tables(region):
    """ბეჭდავს რეგიონში არსებულ ყველა DynamoDB ცხრილს"""
    dynamodb_client = boto3.client('dynamodb', region_name=region)
    print(f"\nDynamoDB ცხრილების ძიება რეგიონში: {region}...")

    try:
        paginator = dynamodb_client.get_paginator('list_tables')
        table_names = []
        for page in paginator.paginate():
            table_names.extend(page['TableNames'])

        if not table_names:
            print("⚠️ DynamoDB ცხრილები ამ რეგიონში არ მოიძებნა.")
            return []

        print(f"✅ ნაპოვნია {len(table_names)} ცხრილი:")
        for name in table_names:
            print(f"  - {name}")
        return table_names
    except ClientError as e:
        print(f"❌ DynamoDB ცხრილების მოძიება ვერ მოხერხდა: {e}")
        sys.exit(1)


def create_manual_snapshot(rds_client, db_id, snapshot_id):
    """ქმნის RDS ინსტანსის მანუალურ (ხელით გაკეთებულ) Snapshot-ს"""
    print(f"\nმანუალური Snapshot-ის შექმნა ('{snapshot_id}') ინსტანსისთვის '{db_id}'...")
    try:
        rds_client.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_id,
            DBInstanceIdentifier=db_id
        )
        print(f"✅ Snapshot-ის შექმნა დაიწყო. ID: {snapshot_id}")
        return snapshot_id
    except ClientError as e:
        error_code = e.response['Error']['Code']
        if error_code == 'DBSnapshotAlreadyExists':
            print(f"⚠️ Snapshot სახელად '{snapshot_id}' უკვე არსებობს.")
            return snapshot_id
        else:
            print(f"❌ Snapshot-ის შექმნა ვერ მოხერხდა: {e}")
            sys.exit(1)


def wait_for_snapshot(rds_client, snapshot_id):
    """ელოდება სანამ Snapshot-ის სტატუსი გახდება 'available'"""
    print("ველოდებით Snapshot-ის დასრულებას (ეს რამდენიმე წუთი შეიძლება გაგრძელდეს)...")
    try:
        waiter = rds_client.get_waiter('db_snapshot_available')
        waiter.wait(DBSnapshotIdentifier=snapshot_id, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})
        print(f"✅ Snapshot '{snapshot_id}' მზად არის.")
    except ClientError as e:
        print(f"❌ Snapshot-ის სტატუსის შემოწმება ვერ მოხერხდა: {e}")
        sys.exit(1)


# ──────────────────────────────────────────────────────────────────────────
# Command handlers
# ──────────────────────────────────────────────────────────────────────────

def run_create(args):
    """ძველი ფუნქციონალი: ქმნის EC2 ინსტანსს და მასთან დაკავშირებულ RDS ბაზას"""
    ec2_client = boto3.client('ec2', region_name=args.region)
    ec2_resource = boto3.resource('ec2', region_name=args.region)
    ssm_client = boto3.client('ssm', region_name=args.region)
    rds_client = boto3.client('rds', region_name=args.region)

    validate_network(ec2_client, args.vpc_id, args.subnet_id)

    ssh_ip = args.custom_ssh_ip if args.custom_ssh_ip else get_my_public_ip()

    sg_id = setup_security_group(ec2_client, args.vpc_id, args.sg_name, ssh_ip)
    setup_key_pair(ec2_client, args.key_name)

    ami_id = get_latest_amazon_linux_3(ssm_client)

    print("EC2 ინსტანსის ლოკაცია და კონფიგურაცია...")
    try:
        instances = ec2_resource.create_instances(
            ImageId=ami_id,
            InstanceType=args.instance_type,
            MinCount=1,
            MaxCount=1,
            KeyName=args.key_name,
            NetworkInterfaces=[{
                'DeviceIndex': 0,
                'SubnetId': args.subnet_id,
                'Groups': [sg_id],
                'AssociatePublicIpAddress': True
            }],
            TagSpecifications=[{
                'ResourceType': 'instance',
                'Tags': [{'Key': 'Name', 'Value': 'CLI-Generated-Instance'}]
            }]
        )
        instance = instances[0]
        print(f"✅ ინსტანსი წარმატებით გაეშვა! ID: {instance.id}")
    except ClientError as e:
        print(f"❌ ინსტანსის შექმნა ვერ მოხერხდა: {e.response['Error']['Message']}")
        sys.exit(1)

    print("ველოდებით ინსტანსის სრულ გააქტიურებას (Running state)...")
    instance.wait_until_running()
    instance.reload()
    public_ip = instance.public_ip_address

    print(f"✅ ინსტანსი გააქტიურდა! Public IP: {public_ip}")

    wait_and_check_ssh(public_ip, port=22, timeout=60)

    create_rds_instance(rds_client, sg_id, args.db_id, args.db_user, args.db_pass)
    wait_for_rds(rds_client, args.db_id)

    print("\n==================================")
    print("🎉 ოპერაცია წარმატებით დასრულდა!")
    print(f"შესასვლელად გამოიყენეთ ბრძანება:\nssh -i {args.key_name}.pem ec2-user@{public_ip}")
    print("==================================")


def run_increase_storage(args):
    rds_client = boto3.client('rds', region_name=args.region)
    increase_rds_storage(rds_client, args.db_id, args.percent)


def run_list_dynamodb(args):
    list_dynamodb_tables(args.region)


def run_create_snapshot(args):
    rds_client = boto3.client('rds', region_name=args.region)
    snapshot_id = args.snapshot_id or f"{args.db_id}-manual-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    create_manual_snapshot(rds_client, args.db_id, snapshot_id)
    if args.wait:
        wait_for_snapshot(rds_client, snapshot_id)


# ──────────────────────────────────────────────────────────────────────────
# Argparse / entrypoint
# ──────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="AWS EC2 & RDS Manager CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- create: EC2 + RDS ინსტანსების შექმნა (ძველი ფუნქციონალი) ---
    create_parser = subparsers.add_parser("create", help="ქმნის ახალ EC2 ინსტანსს და RDS (MySQL) ბაზას")
    create_parser.add_argument("--vpc-id", required=True, help="არსებული VPC-ის ID (მაგ: vpc-12345)")
    create_parser.add_argument("--subnet-id", required=True, help="არსებული Subnet-ის ID (მაგ: subnet-67890)")
    create_parser.add_argument("--custom-ssh-ip", help="სპეციფიკური IP (CIDR). თუ არ მიუთითებთ, ავტომატურად დადგინდება თქვენი IP.")
    create_parser.add_argument("--key-name", default="my-cli-key", help="Key Pair-ის სახელი (default: my-cli-key)")
    create_parser.add_argument("--sg-name", default="my-cli-sg", help="Security Group-ის სახელი (default: my-cli-sg)")
    create_parser.add_argument("--instance-type", default="t2.micro", help="ინსტანსის ტიპი (default: t2.micro)")
    create_parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")
    create_parser.add_argument("--db-id", default="my-cli-db", help="RDS ბაზის იდენტიფიკატორი (default: my-cli-db)")
    create_parser.add_argument("--db-user", default="admin", help="RDS ბაზის master მომხმარებელი (default: admin)")
    create_parser.add_argument("--db-pass", required=True, help="RDS ბაზის პაროლი (მინიმუმ 8 სიმბოლო)")

    # --- increase-storage: RDS storage-ის გაზრდა % -ით ---
    storage_parser = subparsers.add_parser("increase-storage", help="zრდის არსებული RDS ინსტანსის storage-ს მითითებული პროცენტით")
    storage_parser.add_argument("--db-id", required=True, help="RDS ბაზის იდენტიფიკატორი")
    storage_parser.add_argument("--percent", type=float, default=25, help="გასაზრდელი პროცენტი (default: 25)")
    storage_parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")

    # --- list-dynamodb: ცხრილების ჩამონათვალი ---
    dynamo_parser = subparsers.add_parser("list-dynamodb", help="ბეჭდავს ყველა DynamoDB ცხრილს მითითებულ რეგიონში")
    dynamo_parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")

    # --- create-snapshot: მანუალური ბექაპი ---
    snapshot_parser = subparsers.add_parser("create-snapshot", help="ქმნის RDS ინსტანსის მანუალურ Snapshot-ს")
    snapshot_parser.add_argument("--db-id", required=True, help="RDS ბაზის იდენტიფიკატორი")
    snapshot_parser.add_argument("--snapshot-id", help="Snapshot-ის სახელი (default: {db-id}-manual-{timestamp})")
    snapshot_parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")
    snapshot_parser.add_argument("--wait", action="store_true", help="დაელოდება სანამ Snapshot 'available' გახდება")

    args = parser.parse_args()

    handlers = {
        "create": run_create,
        "increase-storage": run_increase_storage,
        "list-dynamodb": run_list_dynamodb,
        "create-snapshot": run_create_snapshot,
    }
    handlers[args.command](args)


if __name__ == "__main__":
    main()