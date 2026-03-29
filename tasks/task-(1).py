import argparse
import boto3
from botocore.exceptions import ClientError


def bucket_exists(s3_client, bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        error_code = int(e.response['Error']['Code'])
        if error_code == 404:
            return False
        else:
            raise


def create_bucket(s3_client, bucket_name, region=None):
    if region is None:
        s3_client.create_bucket(Bucket=bucket_name)
    else:
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={
                'LocationConstraint': region
            }
        )


def main():
    parser = argparse.ArgumentParser(
        description="Check if S3 bucket exists, if not create it"
    )

    parser.add_argument(
        "bucket_name",
        help="Name of the S3 bucket"
    )

    parser.add_argument(
        "--region",
        help="AWS region (optional)",
        default=None
    )

    args = parser.parse_args()

    s3_client = boto3.client('s3', region_name=args.region)

    if bucket_exists(s3_client, args.bucket_name):
        print(f"Bucket '{args.bucket_name}' უკვე არსებობს.")
    else:
        print(f"Bucket '{args.bucket_name}' არ არსებობს. ვქმნით...")
        create_bucket(s3_client, args.bucket_name, args.region)
        print("Bucket წარმატებით შეიქმნა.")


if __name__ == "__main__":
    main()