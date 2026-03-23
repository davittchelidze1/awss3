import argparse
import json
import logging
import os
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
import magic
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

ALLOWED_MIME_TYPES = {
    "image/bmp",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
}


def init_client():
    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
            region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        )
        client.list_buckets()
        return client
    except ClientError as e:
        logger.error("Failed to initialize S3 client")
        logger.error(e)
        return None


def list_buckets(s3_client):
    try:
        response = s3_client.list_buckets()
        return response
    except ClientError as e:
        logger.error(e)
        return None


def create_bucket(s3_client, bucket_name, region=None):
    try:
        if region is None:
            region = s3_client.meta.region_name or os.getenv("AWS_DEFAULT_REGION", "us-east-1")
        
        if region == "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region}
            )
        return True
    except ClientError as e:
        logger.error(e)
        return False


def delete_bucket(s3_client, bucket_name):
    try:
        s3_client.delete_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        logger.error(e)
        return False


def delete_file(s3_client, bucket_name, file_name):
    try:
        s3_client.delete_object(Bucket=bucket_name, Key=file_name)
        return True
    except ClientError as e:
        logger.error(e)
        return False


def bucket_exists(s3_client, bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError:
        return False


def validate_file_type(file_path):
    if not Path(file_path).is_file():
        return False

    mime_type = magic.from_file(file_path, mime=True)
    return mime_type in ALLOWED_MIME_TYPES


def download_file_and_upload_to_s3(s3_client, bucket_name, file_path, object_name=None):
    if not validate_file_type(file_path):
        logger.error("Only .bmp, .jpg, .jpeg, .png, .webp, .mp4 files are allowed")
        return False

    if object_name is None:
        object_name = Path(file_path).name

    try:
        s3_client.upload_file(file_path, bucket_name, object_name)
        return True
    except ClientError as e:
        logger.error(e)
        return False


def set_object_access_policy(s3_client, bucket_name, file_name):
    try:
        response = s3_client.put_object_acl(
            ACL="public-read",
            Bucket=bucket_name,
            Key=file_name
        )
        status_code = response["ResponseMetadata"]["HTTPStatusCode"]
        return status_code == 200
    except ClientError as e:
        logger.error(e)
        return False


def generate_public_read_policy(bucket_name):
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            }
        ]
    }
    return json.dumps(policy)


def create_bucket_policy(s3_client, bucket_name):
    try:
        policy = generate_public_read_policy(bucket_name)
        s3_client.put_bucket_policy(
            Bucket=bucket_name,
            Policy=policy
        )
        return True
    except ClientError as e:
        logger.error(e)
        return False


def read_bucket_policy(s3_client, bucket_name):
    try:
        policy = s3_client.get_bucket_policy(Bucket=bucket_name)
        return policy["Policy"]
    except ClientError as e:
        logger.error(e)
        return None


def upload_large_file(s3_client, bucket_name, file_path, object_name=None):
    if not validate_file_type(file_path):
        logger.error("Only .bmp, .jpg, .jpeg, .png, .webp, .mp4 files are allowed")
        return False

    if object_name is None:
        object_name = Path(file_path).name

    # Multipart upload config for large files
    config = TransferConfig(
        multipart_threshold=25 * 1024 * 1024,  # 25MB
        max_concurrency=10,
        multipart_chunksize=25 * 1024 * 1024,  # 25MB
        use_threads=True
    )

    try:
        s3_client.upload_file(file_path, bucket_name, object_name, Config=config)
        return True
    except ClientError as e:
        logger.error(e)
        return False


def set_lifecycle_policy(s3_client, bucket_name):
    policy = {
        'Rules': [
            {
                'ID': 'DeleteOldObjects120Days',
                'Filter': {'Prefix': ''},
                'Status': 'Enabled',
                'Expiration': {
                    'Days': 120
                }
            }
        ]
    }
    try:
        s3_client.put_bucket_lifecycle_configuration(
            Bucket=bucket_name,
            LifecycleConfiguration=policy
        )
        return True
    except ClientError as e:
        logger.error(e)
        return False


def check_bucket_versioning(s3_client, bucket_name):
    try:
        response = s3_client.get_bucket_versioning(Bucket=bucket_name)
        status = response.get('Status', 'Not Enabled')
        return status
    except ClientError as e:
        logger.error(e)
        return None


def list_file_versions(s3_client, bucket_name, file_name):
    try:
        response = s3_client.list_object_versions(Bucket=bucket_name, Prefix=file_name)
        versions = response.get('Versions', [])
        versions = [v for v in versions if v['Key'] == file_name]
        return versions
    except ClientError as e:
        logger.error(e)
        return None


def restore_previous_version(s3_client, bucket_name, file_name):
    try:
        versions = list_file_versions(s3_client, bucket_name, file_name)
        if not versions or len(versions) < 2:
            logger.error("Not enough versions to restore the previous one.")
            return False

        previous_version = versions[1]
        previous_version_id = previous_version['VersionId']

        copy_source = {
            'Bucket': bucket_name,
            'Key': file_name,
            'VersionId': previous_version_id
        }
        s3_client.copy_object(
            Bucket=bucket_name,
            Key=file_name,
            CopySource=copy_source
        )
        return True
    except ClientError as e:
        logger.error(e)
        return False


def main():
    parser = argparse.ArgumentParser(description="Simple S3 CLI tool")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("list-buckets")

    create_parser = subparsers.add_parser("create-bucket")
    create_parser.add_argument("bucket_name")

    delete_parser = subparsers.add_parser("delete-bucket")
    delete_parser.add_argument("bucket_name")

    delete_file_parser = subparsers.add_parser("delete-file")
    delete_file_parser.add_argument("bucket_name")
    delete_file_parser.add_argument("file_name")

    del_parser = subparsers.add_parser("-del")
    del_parser.add_argument("bucket_name")
    del_parser.add_argument("file_name")

    exists_parser = subparsers.add_parser("bucket-exists")
    exists_parser.add_argument("bucket_name")

    upload_parser = subparsers.add_parser("upload-file")
    upload_parser.add_argument("bucket_name")
    upload_parser.add_argument("file_path")
    upload_parser.add_argument("--object-name", default=None)

    upload_large_parser = subparsers.add_parser("upload-large-file")
    upload_large_parser.add_argument("bucket_name")
    upload_large_parser.add_argument("file_path")
    upload_large_parser.add_argument("--object-name", default=None)

    lifecycle_parser = subparsers.add_parser("set-lifecycle-policy")
    lifecycle_parser.add_argument("bucket_name")

    object_acl_parser = subparsers.add_parser("set-object-access")
    object_acl_parser.add_argument("bucket_name")
    object_acl_parser.add_argument("file_name")

    create_policy_parser = subparsers.add_parser("create-bucket-policy")
    create_policy_parser.add_argument("bucket_name")

    read_policy_parser = subparsers.add_parser("read-bucket-policy")
    read_policy_parser.add_argument("bucket_name")

    versioning_parser = subparsers.add_parser("check-versioning")
    versioning_parser.add_argument("bucket_name")

    file_versions_parser = subparsers.add_parser("list-file-versions")
    file_versions_parser.add_argument("bucket_name")
    file_versions_parser.add_argument("file_name")

    restore_version_parser = subparsers.add_parser("restore-previous-version")
    restore_version_parser.add_argument("bucket_name")
    restore_version_parser.add_argument("file_name")

    args = parser.parse_args()

    s3_client = init_client()
    if s3_client is None:
        return

    if args.command == "list-buckets":
        buckets = list_buckets(s3_client)
        if buckets:
            for bucket in buckets["Buckets"]:
                print(bucket["Name"])

    elif args.command == "create-bucket":
        if create_bucket(s3_client, args.bucket_name):
            print("Bucket created")

    elif args.command == "delete-bucket":
        if delete_bucket(s3_client, args.bucket_name):
            print("Bucket deleted")

    elif args.command in ("delete-file", "-del"):
        if delete_file(s3_client, args.bucket_name, args.file_name):
            print("File deleted")

    elif args.command == "bucket-exists":
        if bucket_exists(s3_client, args.bucket_name):
            print("Bucket exists")
        else:
            print("Bucket does not exist")

    elif args.command == "upload-file":
        if download_file_and_upload_to_s3(
            s3_client,
            args.bucket_name,
            args.file_path,
            args.object_name
        ):
            print("File uploaded")

    elif args.command == "upload-large-file":
        if upload_large_file(s3_client, args.bucket_name, args.file_path, args.object_name):
            print("Large file uploaded successfully using multipart upload")

    elif args.command == "set-lifecycle-policy":
        if set_lifecycle_policy(s3_client, args.bucket_name):
            print("Lifecycle policy set (120 days expiration)")

    elif args.command == "set-object-access":
        if set_object_access_policy(s3_client, args.bucket_name, args.file_name):
            print("Object access policy set")

    elif args.command == "create-bucket-policy":
        if create_bucket_policy(s3_client, args.bucket_name):
            print("Bucket policy created")

    elif args.command == "read-bucket-policy":
        policy = read_bucket_policy(s3_client, args.bucket_name)
        if policy:
            print(policy)

    elif args.command == "check-versioning":
        status = check_bucket_versioning(s3_client, args.bucket_name)
        if status is not None:
            print(f"Bucket versioning status: {status}")

    elif args.command == "list-file-versions":
        versions = list_file_versions(s3_client, args.bucket_name, args.file_name)
        if versions is not None:
            print(f"Total versions: {len(versions)}")
            for idx, v in enumerate(versions):
                is_latest = " (Latest)" if v.get("IsLatest") else ""
                print(f"{idx+1}. VersionId: {v.get('VersionId')} | Date: {v.get('LastModified')}{is_latest}")

    elif args.command == "restore-previous-version":
        if restore_previous_version(s3_client, args.bucket_name, args.file_name):
            print("Successfully restored the previous version as the new current version.")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()