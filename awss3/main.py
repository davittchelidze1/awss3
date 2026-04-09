import argparse
from datetime import datetime, timedelta, timezone
import json
import logging
import mimetypes
import os
from pathlib import Path

import boto3
from boto3.s3.transfer import TransferConfig
try:
    import magic
except ImportError:
    magic = None
from botocore.exceptions import BotoCoreError, ClientError
try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(dotenv_path=None, override=False):
        env_path = Path(dotenv_path) if dotenv_path else Path(".env")
        if not env_path.is_file():
            return False

        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("export "):
                line = line[7:].strip()

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if override or key not in os.environ:
                os.environ[key] = value

        return True

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

ENV_FILE = Path(__file__).with_name(".env")

ALLOWED_MIME_TYPES = {
    "image/bmp",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/html",
    "video/mp4",
}


def get_env_value(name, default=None):
    return os.getenv(name) or os.getenv(name.lower()) or default


load_dotenv(ENV_FILE)


def detect_mime_type(file_path):
    if magic is not None:
        return magic.from_file(file_path, mime=True)

    mime_type, _ = mimetypes.guess_type(file_path)
    return mime_type


def init_client():
    try:
        client = boto3.client(
            "s3",
            aws_access_key_id=get_env_value("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=get_env_value("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=get_env_value("AWS_SESSION_TOKEN"),
            region_name=get_env_value("AWS_DEFAULT_REGION", "us-east-1")
        )
        client.list_buckets()
        return client
    except (ClientError, BotoCoreError) as e:
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
            region = s3_client.meta.region_name or get_env_value("AWS_DEFAULT_REGION", "us-east-1")
        
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

    mime_type = detect_mime_type(file_path)
    if mime_type is None:
        return False

    return mime_type in ALLOWED_MIME_TYPES


def upload_file_to_matching_folder(s3_client, bucket_name, file_path, object_name=None):
    if not Path(file_path).is_file():
        logger.error("File does not exist")
        return False

    try:
        mime_type = detect_mime_type(file_path)
        if mime_type is None:
            logger.error("Could not determine file MIME type")
            return False

        file_name = object_name if object_name else Path(file_path).name
        extension = Path(file_name).suffix.lower().replace(".", "")

        if not extension:
            if "/" in mime_type:
                extension = mime_type.split("/")[1].replace(".", "-")
            else:
                extension = "other"

        object_key = f"{extension}/{file_name}"

        s3_client.upload_file(
            file_path,
            bucket_name,
            object_key,
            ExtraArgs={"ContentType": mime_type}
        )

        print(f"Uploaded to: {object_key}")
        print(f"MIME type: {mime_type}")
        return True
    except ClientError as e:
        logger.error(e)
        return False
    except Exception as e:
        logger.error(e)
        return False


def download_file_and_upload_to_s3(s3_client, bucket_name, file_path, object_name=None):
    if not validate_file_type(file_path):
        logger.error("Only .bmp, .jpg, .jpeg, .png, .webp, .html, .mp4 files are allowed")
        return False

    if object_name is None:
        object_name = Path(file_path).name

    try:
        mime_type = detect_mime_type(file_path)
        extra_args = {"ContentType": mime_type} if mime_type else None
        upload_kwargs = {"ExtraArgs": extra_args} if extra_args else {}

        s3_client.upload_file(file_path, bucket_name, object_name, **upload_kwargs)
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


def check_and_delete_old_versions(s3_client, bucket_name, file_names):
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=180)
    total_deleted = 0

    for file_name in file_names:
        print(f"Checking versions for: {file_name}")

        versions = list_file_versions(s3_client, bucket_name, file_name)
        if versions is None:
            print("Could not read versions for this file")
            continue

        if not versions:
            print("No versions found")
            continue

        print(f"Found {len(versions)} versions")

        for version in versions:
            version_id = version.get("VersionId")
            last_modified = version.get("LastModified")
            is_latest = version.get("IsLatest", False)

            latest_text = " (Latest)" if is_latest else ""
            print(f"- VersionId: {version_id} | Date: {last_modified}{latest_text}")

            if last_modified and last_modified <= cutoff_date:
                try:
                    s3_client.delete_object(
                        Bucket=bucket_name,
                        Key=file_name,
                        VersionId=version_id
                    )
                    total_deleted += 1
                    print(f"  Deleted old version: {version_id}")
                except ClientError as e:
                    logger.error(e)

        print()

    print(f"Total deleted old versions: {total_deleted}")
    return True


def organize_by_extension(s3_client, bucket_name):
    try:
        response = s3_client.list_objects_v2(Bucket=bucket_name)
        objects = response.get('Contents', [])
        
        counts = {}
        for obj in objects:
            key = obj['Key']
            if key.endswith('/'):
                continue
                
            file_name = key.split('/')[-1]
            if '.' not in file_name:
                continue
                
            ext = file_name.split('.')[-1].lower()
            new_key = f"{ext}/{file_name}"
            
            if key == new_key:
                continue
                
            s3_client.copy_object(
                Bucket=bucket_name,
                CopySource={'Bucket': bucket_name, 'Key': key},
                Key=new_key
            )
            s3_client.delete_object(Bucket=bucket_name, Key=key)
            
            counts[ext] = counts.get(ext, 0) + 1
            
        return counts
    except ClientError as e:
        logger.error(e)
        return None


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

    upload_by_magic_parser = subparsers.add_parser("upload-by-magic")
    upload_by_magic_parser.add_argument("bucket_name")
    upload_by_magic_parser.add_argument("file_path")
    upload_by_magic_parser.add_argument("--object-name", default=None)

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

    version_flags_parser = subparsers.add_parser("versioning-flags")
    version_flags_parser.add_argument("bucket_name")
    version_flags_parser.add_argument("--file-name", default=None)

    version_flags_group = version_flags_parser.add_mutually_exclusive_group(required=True)
    version_flags_group.add_argument("--check-bucket-versioning", action="store_true")
    version_flags_group.add_argument("--show-file-versions", action="store_true")
    version_flags_group.add_argument("--restore-previous-version", action="store_true")

    delete_old_versions_parser = subparsers.add_parser("delete-old-versions")
    delete_old_versions_parser.add_argument("bucket_name")
    delete_old_versions_parser.add_argument("file_names", nargs="+")

    organize_parser = subparsers.add_parser("organize-by-ext")
    organize_parser.add_argument("bucket_name")

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

    elif args.command == "upload-by-magic":
        if upload_file_to_matching_folder(
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

    elif args.command == "versioning-flags":
        if args.check_bucket_versioning:
            status = check_bucket_versioning(s3_client, args.bucket_name)
            if status == "Enabled":
                print("Bucket versioning is enabled")
            elif status is not None:
                print("Bucket versioning is not enabled")

        elif args.show_file_versions:
            if not args.file_name:
                print("--file-name is required with --show-file-versions")
            else:
                versions = list_file_versions(s3_client, args.bucket_name, args.file_name)
                if versions is not None:
                    print(f"Total versions: {len(versions)}")
                    for idx, version in enumerate(versions):
                        print(
                            f"{idx + 1}. VersionId: {version.get('VersionId')} | "
                            f"Date: {version.get('LastModified')}"
                        )

        elif args.restore_previous_version:
            if not args.file_name:
                print("--file-name is required with --restore-previous-version")
            else:
                if restore_previous_version(s3_client, args.bucket_name, args.file_name):
                    print("Previous version uploaded as a new version")

    elif args.command == "delete-old-versions":
        if check_and_delete_old_versions(s3_client, args.bucket_name, args.file_names):
            print("Old versions cleanup finished")

    elif args.command == "organize-by-ext":
        counts = organize_by_extension(s3_client, args.bucket_name)
        if counts is not None:
            if not counts:
                print("No files were moved.")
            else:
                for ext, count in counts.items():
                    print(f"{ext} - {count}")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
