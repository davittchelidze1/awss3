    import argparse
    import boto3
    import urllib.request
    import socket
    import os
    import sys
    import time
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
            # VPC შემოწმება
            ec2_client.describe_vpcs(VpcIds=[vpc_id])
            
            # Subnet შემოწმება
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
        """მოიძიებს უახლესი Amazon Linux 2023 (გურმანულად AL3) AMI-ს SSM პარამეტრებიდან"""
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
                
            # პროგრამულად ვაყენებთ 0400 უფლებებს
            # (შენიშვნა: Windows-ზე ეს ყოველთვის ზუსტად ისევ არ თარგმნის უფლებებს როგორც Linux-ზე,
            # მაგრამ Python-ის მოთხოვნას ასრულებს).
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
                # მოვძებნოთ მისი ID 
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
        """დაელოდება და შეამოწმებს (22 ან 3306) პორტზე კავშირის ხელმისაწვდომობას socket-ის გამოყენებით"""
        print(f"პორტ {port}-ზე კავშირის შემოწმება (IP: {ip_address})...")
        start_time = time.time()
        
        while True:
            try:
                with socket.create_connection((ip_address, port), timeout=3) as sock:
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
                DBInstanceClass='db.t3.micro',  # T3 micro არის Free Tier/საბაზისო მოთხოვნებისთვის
                Engine='mysql',
                MasterUsername=db_user,
                MasterUserPassword=db_pass,
                VpcSecurityGroupIds=[sg_id],
                PubliclyAccessible=True  # აუცილებელია გარედან დასაკავშირებლად (DBeaver, DataGrip)
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

    def main():
        parser = argparse.ArgumentParser(description="AWS EC2 & RDS Manager CLI")
        parser.add_argument("--vpc-id", required=True, help="არსებული VPC-ის ID (მაგ: vpc-12345)")
        parser.add_argument("--subnet-id", required=True, help="არსებული Subnet-ის ID (მაგ: subnet-67890)")
        parser.add_argument("--custom-ssh-ip", help="სპეციფიკური IP (CIDR, მაგ: 1.2.3.4/32). თუ არ მიუთითებთ, ავტომატურად დადგინდება თქვენი IP.")
        parser.add_argument("--key-name", default="my-cli-key", help="Key Pair-ის სახელი (default: my-cli-key)")
        parser.add_argument("--sg-name", default="my-cli-sg", help="Security Group-ის სახელი (default: my-cli-sg)")
        parser.add_argument("--instance-type", default="t2.micro", help="ინსტანსის ტიპი (default: t2.micro)")
        parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")
        
        # RDS-ის არგუმენტები
        parser.add_argument("--db-id", default="my-cli-db", help="RDS ბაზის იდენტიფიკატორი (default: my-cli-db)")
        parser.add_argument("--db-user", default="admin", help="RDS ბაზის master მომხმარებელი (default: admin)")
        parser.add_argument("--db-pass", required=True, help="RDS ბაზის პაროლი (მინიმუმ 8 სიმბოლო)")

        args = parser.parse_args()

        # AWS სერვისებთან წვდომის ობიექტები
        ec2_client = boto3.client('ec2', region_name=args.region)
        ec2_resource = boto3.resource('ec2', region_name=args.region)
        ssm_client = boto3.client('ssm', region_name=args.region)
        rds_client = boto3.client('rds', region_name=args.region)

        # 1. ქსელის ვალიდაცია
        validate_network(ec2_client, args.vpc_id, args.subnet_id)

        # 2. SSH წვდომისთვის IP-ის დადგენა
        if args.custom_ssh_ip:
            ssh_ip = args.custom_ssh_ip
        else:
            ssh_ip = get_my_public_ip()
        
        # 3. Security Group და KeyPair შექმნა
        sg_id = setup_security_group(ec2_client, args.vpc_id, args.sg_name, ssh_ip)
        setup_key_pair(ec2_client, args.key_name)

        # 4. უახლესი AL3 (Amazon Linux 2023) AMI-ის მოძიება
        ami_id = get_latest_amazon_linux_3(ssm_client)

        # 5. EC2 ინსტანსის შექმნა
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
                    'AssociatePublicIpAddress': True  # აუცილებელია სახომავლო Public IP-ის მისანიჭებლად
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

        # 6. ლოდინი და გააქტიურება
        print("ველოდებით ინსტანსის სრულ გააქტიურებას (Running state)...")
        instance.wait_until_running()
        instance.reload() # მონაცემების განახლება (Public IP-ის წამოსაღებად)
        public_ip = instance.public_ip_address
        
        print(f"✅ ინსტანსი გააქტიურდა! Public IP: {public_ip}")

        # 7. Socket-ით 22-ე პორტის შემოწმება
        wait_and_check_ssh(public_ip, port=22, timeout=60)

        print("\n==================================")
        print("🎉 ოპერაცია წარმატებით დასრულდა!")
        print(f"შესასვლელად გამოიყენეთ ბრძანება:\nssh -i {args.key_name}.pem ec2-user@{public_ip}")
        print("==================================")

    if __name__ == "__main__":
        main()