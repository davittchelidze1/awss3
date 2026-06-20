import argparse
import ipaddress
import boto3
import sys
import math

def validate_cidr(cidr):
    """ამოწმებს CIDR-ის ვალიდურობას"""
    try:
        ipaddress.IPv4Network(cidr)
        return True
    except ValueError:
        print(f"შეცდომა: არასწორი CIDR ბლოკი '{cidr}'")
        sys.exit(1)

def get_subnet_cidrs(vpc_cidr_str, subnets_needed):
    """VPC CIDR-დან დინამიურად აგენერირებს საჭირო რაოდენობის Subnet CIDR-ებს."""
    vpc_net = ipaddress.IPv4Network(vpc_cidr_str)
    
    # ვითვლით თუ რამდენი ბიტით უნდა გავზარდოთ prefix-ი, რომ მივიღოთ მინიმუმ subnets_needed
    # მაგ: თუ გვჭირდება 4 სუბნეტი -> 2^2=4 (log2(4)=2), prefix_diff=2
    prefix_diff = math.ceil(math.log2(subnets_needed)) if subnets_needed > 1 else 1
    new_prefix = vpc_net.prefixlen + prefix_diff
    
    # AWS Subnet არ შეიძლება იყოს /28 -ზე მცირე 
    if new_prefix > 28:
        print(f"შეცდომა: VPC CIDR '{vpc_cidr_str}' ძალიან პატარაა {subnets_needed} სუბნეტის შესაქმნელად.")
        sys.exit(1)
        
    subnets = list(vpc_net.subnets(new_prefix=new_prefix))
    return [str(s) for s in subnets[:subnets_needed]]

def create_infrastructure(args):
    validate_cidr(args.vpc_cidr)
    
    if args.subnet_count < 1 or args.subnet_count > 100:
        print("შეცდომა: --subnet-count უნდა იყოს 1-დან 100-მდე (რადგან 100 public + 100 private = 200 მაქსიმუმ).")
        sys.exit(1)

    print(f"სკრიპტი იწყებს ინფრასტრუქტურის შექმნას რიგიონში: {args.region}...")
    
    # გვჭირდება 2 * N სუბნეტი (N public, N private)
    total_subnets_needed = args.subnet_count * 2
    subnet_cidrs = get_subnet_cidrs(args.vpc_cidr, total_subnets_needed)
    
    public_cidrs = subnet_cidrs[:args.subnet_count]
    private_cidrs = subnet_cidrs[args.subnet_count:]

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

    # 3. Route Table-ების შექმნა და მარშრუტიზაცია
    print("იქმნება და კონფიგურირდება Route Table-ები...")
    
    public_rt = vpc.create_route_table()
    public_rt.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-public-rt"}])
    public_rt.create_route(DestinationCidrBlock='0.0.0.0/0', GatewayId=igw.id)

    private_rt = vpc.create_route_table()
    private_rt.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-private-rt"}])

    # 4. Subnet-ების შექმნა
    print(f"იქმნება {args.subnet_count} Public და {args.subnet_count} Private სუბნეტი...")
    
    for i, cidr in enumerate(public_cidrs, 1):
        subnet = vpc.create_subnet(CidrBlock=cidr)
        subnet.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-public-subnet-{i}"}])
        public_rt.associate_with_subnet(SubnetId=subnet.id)
        print(f" [+] Public Subnet {i} ({cidr}) შეიქმნა. ID: {subnet.id}")

    for i, cidr in enumerate(private_cidrs, 1):
        subnet = vpc.create_subnet(CidrBlock=cidr)
        subnet.create_tags(Tags=[{'Key': 'Name', 'Value': f"{args.vpc_name}-private-subnet-{i}"}])
        private_rt.associate_with_subnet(SubnetId=subnet.id)
        print(f" [+] Private Subnet {i} ({cidr}) შეიქმნა. ID: {subnet.id}")

    print("\n✅ წარმატებით შეიქმნა ინფრასტრუქტურა!")
    print(f"VPC ID: {vpc.id}")


def destroy_infrastructure(args):
    ec2_resource = boto3.resource('ec2', region_name=args.region)

    print(f"ვეძებთ VPC-ს სახელით: '{args.vpc_name}' ...")
    vpcs = list(ec2_resource.vpcs.filter(Filters=[{'Name': 'tag:Name', 'Values': [args.vpc_name]}]))

    if not vpcs:
        print(f"შეცდომა: '{args.vpc_name}' სახელის მქონე VPC ვერ მოიძებნა.")
        return

    for vpc in vpcs:
        print(f"მოიძებნა VPC (ID: {vpc.id}). ვიწყებთ ავტომატური წაშლის პროცესს...")

        for igw in vpc.internet_gateways.all():
            print(f"➔ ვხსნით IGW-ს (Detach): {igw.id}")
            vpc.detach_internet_gateway(InternetGatewayId=igw.id)
            print(f"➔ ვშლით IGW-ს (Delete): {igw.id}")
            igw.delete()

        for rt in vpc.route_tables.all():
            is_main = False
            for assoc in rt.associations_attribute:
                if assoc['Main']:
                    is_main = True
                    break
            if not is_main:
                print(f"➔ ვშლით Route Table-ს: {rt.id}")
                rt.delete()

        for subnet in vpc.subnets.all():
            print(f"➔ ვშლით Subnet-ს: {subnet.id}")
            subnet.delete()

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
    create_parser.add_argument("--subnet-count", type=int, default=1, help="ცალკეული ტიპის სუბნეტების რაოდენობა (მაქსიმუმ 100)")
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
