import argparse
import ipaddress
import boto3
import sys

def validate_cidr(cidr):
    """ამოწმებს CIDR-ის ვალიდურობას"""
    try:
        ipaddress.IPv4Network(cidr)
        return True
    except ValueError:
        print(f"შეცდომა: არასწორი CIDR ბლოკი '{cidr}'")
        sys.exit(1)

def create_infrastructure(args):
    # CIDR ვალიდაცია
    validate_cidr(args.vpc_cidr)
    validate_cidr(args.public_subnet_cidr)
    validate_cidr(args.private_subnet_cidr)

    print(f"სკრიპტი იწყებს ინფრასტრუქტურის შექმნას რიგიონში: {args.region}...")
    
    ec2_resource = boto3.resource('ec2', region_name=args.region)

    # 1. VPC-ის შექმნა
    print(f"იქმნება VPC CIDR ბლოკით {args.vpc_cidr}...")
    vpc = ec2_resource.create_vpc(CidrBlock=args.vpc_cidr)
    vpc.wait_until_available()
    vpc.create_tags(Tags=[{'Key': 'Name', 'Value': args.vpc_name}])
    print(f"VPC შეიქმნა. ID: {vpc.id}")

    # 2. Internet Gateway (IGW) შექმნა
    print("იქმნება Internet Gateway (IGW)...")
    igw = ec2_resource.create_internet_gateway()
    igw.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-igw"}])
    vpc.attach_internet_gateway(InternetGatewayId=igw.id)
    print(f"IGW შეიქმნა და მიება VPC-ს. ID: {igw.id}")

    # 3. Subnet-ების შექმნა
    print(f"იქმნება Public Subnet CIDR ბლოკით {args.public_subnet_cidr}...")
    public_subnet = vpc.create_subnet(CidrBlock=args.public_subnet_cidr)
    public_subnet.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-public-subnet"}])

    print(f"იქმნება Private Subnet CIDR ბლოკით {args.private_subnet_cidr}...")
    private_subnet = vpc.create_subnet(CidrBlock=args.private_subnet_cidr)
    private_subnet.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-private-subnet"}])

    # 4. Route Table-ების შექმნა და მარშრუტიზაცია
    print("იქმნება და კონფიგურირდება Route Table-ები...")
    
    # Public Route Table
    public_rt = vpc.create_route_table()
    public_rt.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-public-rt"}])
    # ინტერნეტთან კავშირის დამატება IGW-ის გავლით -> 0.0.0.0/0
    public_rt.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=igw.id)
    public_rt.associate_with_subnet(SubnetId=public_subnet.id)

    # Private Route Table
    private_rt = vpc.create_route_table()
    private_rt.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-private-rt"}])
    private_rt.associate_with_subnet(SubnetId=private_subnet.id)

    print("\n✅ წარმატებით შეიქმნა ინფრასტრუქტურა!")
    print(f"VPC ID: {vpc.id}")
    print(f"Public Subnet ID: {public_subnet.id}")
    print(f"Private Subnet ID: {private_subnet.id}")


def destroy_infrastructure(args):
    ec2_resource = boto3.resource('ec2', region_name=args.region)

    print(f"ვეძებთ VPC-ს სახელით: '{args.vpc_name}' ...")
    vpcs = list(ec2_resource.vpcs.filter(Filters=[{'Name': 'tag:Name', 'Values': [args.vpc_name]}]))

    if not vpcs:
        print(f"შეცდომა: '{args.vpc_name}' სახელის მქონე VPC ვერ მოიძებნა.")
        return

    for vpc in vpcs:
        print(f"მოიძებნა VPC (ID: {vpc.id}). ვიწყებთ ავტომატური წაშლის პროცესს...")

        # 1. Internet Gateway-ების ჩამოშორება (detach) და წაშლა
        for igw in vpc.internet_gateways.all():
            print(f"➔ ვხსნით IGW-ს (Detach): {igw.id}")
            vpc.detach_internet_gateway(InternetGatewayId=igw.id)
            print(f"➔ ვშლით IGW-ს (Delete): {igw.id}")
            igw.delete()

        # 2. ინდივიდუალური Route Table-ების წაშლა (Main Route Table-ის გარდა)
        for rt in vpc.route_tables.all():
            is_main = False
            for assoc in rt.associations_attribute:
                if assoc['Main']:
                    is_main = True
                    break
            if not is_main:
                print(f"➔ ვშლით Route Table-ს: {rt.id}")
                rt.delete()

        # 3. Subnet-ების წაშლა
        for subnet in vpc.subnets.all():
            print(f"➔ ვშლით Subnet-ს: {subnet.id}")
            subnet.delete()

        # 4. თავად VPC-ის წაშლა
        print(f"➔ ვშლით ძირითად VPC-ს: {vpc.id}")
        vpc.delete()

    print("\n✅ ინფრასტრუქტურა სრულად და წარმატებით წაიშალა!")


def main():
    parser = argparse.ArgumentParser(description="AWS Infrastructure Manager CLI")
    subparsers = parser.add_subparsers(dest="action", required=True, help="აირჩიეთ მოქმედება: create ან destroy")

    # Create ბრძანების სტრუქტურა
    create_parser = subparsers.add_parser("create", help="ინფრასტრუქტურის შექმნა")
    create_parser.add_argument("--vpc-name", required=True, help="VPC-ის სახელი (Tag:Name)")
    create_parser.add_argument("--vpc-cidr", default="10.0.0.0/16", help="VPC-ის CIDR ბლოკი (default: 10.0.0.0/16)")
    create_parser.add_argument("--public-subnet-cidr", default="10.0.1.0/24", help="Public Subnet-ის CIDR (default: 10.0.1.0/24)")
    create_parser.add_argument("--private-subnet-cidr", default="10.0.2.0/24", help="Private Subnet-ის CIDR (default: 10.0.2.0/24)")
    create_parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")

    # Destroy ბრძანების სტრუქტურა
    destroy_parser = subparsers.add_parser("destroy", help="ინფრასტრუქტურის წაშლა")
    destroy_parser.add_argument("--vpc-name", required=True, help="წასაშლელი VPC-ის სახელი")
    destroy_parser.add_argument("--region", default="us-east-1", help="AWS რეგიონი (default: us-east-1)")

    args = parser.parse_args()

    try:
        if args.action == "create":
            create_infrastructure(args)
        elif args.action == "destroy":
            destroy_infrastructure(args)
    except Exception as e:
        print(f"დაფიქსირდა შეცდომა: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
