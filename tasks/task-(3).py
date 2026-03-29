import argparse
import boto3
from botocore.exceptions import ClientError


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("bucket")
    args = parser.parse_args()

    s3 = boto3.client("s3")
    bucket = args.bucket

    # check if bucket exists
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError:
        print("Bucket does not exist")
        return

    # delete bucket
    try:
        s3.delete_bucket(Bucket=bucket)
        print("Bucket deleted")
    except ClientError as e:
        print("Error deleting bucket:", e)


if __name__ == "__main__":
    main()