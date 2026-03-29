import argparse
import json
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

    # check if policy exists
    try:
        s3.get_bucket_policy(Bucket=bucket)
        print("Policy already exists")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchBucketPolicy":
            raise

    # create policy
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/dev/*"
            },
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/test/*"
            }
        ]
    }

    s3.put_bucket_policy(
        Bucket=bucket,
        Policy=json.dumps(policy)
    )

    print("Policy created")


if __name__ == "__main__":
    main()