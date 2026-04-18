import os
from urllib.parse import unquote_plus

import boto3


s3 = boto3.client("s3")


def get_target_key(object_key):
    file_name = os.path.basename(object_key)
    if not file_name:
        return None

    if "." in file_name:
        extension = file_name.rsplit(".", 1)[1].lower()
    else:
        extension = "other"

    return f"{extension}/{file_name}"


def lambda_handler(event, context):
    records = event.get("Records", [])

    for record in records:
        bucket_name = record["s3"]["bucket"]["name"]
        object_key = unquote_plus(record["s3"]["object"]["key"])

        target_key = get_target_key(object_key)
        if target_key is None:
            continue

        if object_key == target_key:
            continue

        s3.copy_object(
            Bucket=bucket_name,
            CopySource={"Bucket": bucket_name, "Key": object_key},
            Key=target_key,
        )

        s3.delete_object(Bucket=bucket_name, Key=object_key)

    return {
        "statusCode": 200,
        "body": "Files were moved into extension folders",
    }
