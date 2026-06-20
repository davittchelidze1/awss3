import os
import json
import logging
import urllib.request
from urllib.parse import unquote_plus
import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

s3_client = boto3.client("s3")
HF_TOKEN = os.getenv("HF_API_TOKEN")

BASE_URL = "https://api-inference.huggingface.co/models"
HF_MODELS = {
    "mobilenet": f"{BASE_URL}/google/mobilenet_v1_0.75_192",
    "resnet-50": f"{BASE_URL}/microsoft/resnet-50",
    "mit-b0": f"{BASE_URL}/nvidia/mit-b0",
    "yolos-tiny": f"{BASE_URL}/hustvl/yolos-tiny",
}

def infer_image(model_url, img_data):
    """Sends the image to Hugging Face inference API and returns the predictions."""
    if not HF_TOKEN:
        logger.warning("HF_API_TOKEN is not set. Inference might fail.")

    req = urllib.request.Request(
        model_url, 
        data=img_data, 
        headers={
            "Authorization": f"Bearer {HF_TOKEN}",
            "Content-Type": "application/octet-stream",
        }, 
        method="POST"
    )
    
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        logger.error(f"Failed to query {model_url}: {e}")
        return {"error": str(e)}

def lambda_handler(event, context):
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = unquote_plus(record["s3"]["object"]["key"])

        # ignore if the event was triggered by a json file creation
        if key.startswith("json/"):
            continue

        filename = os.path.basename(key)
        if not filename:
            continue

        try:
            # get original image from s3
            img_obj = s3_client.get_object(Bucket=bucket, Key=key)
            img_bytes = img_obj["Body"].read()

            # hit each huggingface model and save the result
            for name, url in HF_MODELS.items():
                logger.info(f"Running inference with {name} on {filename}...")
                preds = infer_image(url, img_bytes)

                dest_key = f"json/{name}_{filename}.json"
                
                s3_client.put_object(
                    Bucket=bucket,
                    Key=dest_key,
                    Body=json.dumps(preds, indent=2),
                    ContentType="application/json"
                )
                logger.info(f"Saved predictions to s3://{bucket}/{dest_key}")

        except Exception as e:
            logger.error(f"Error processing s3://{bucket}/{key}: {e}")
            
    return {
        "statusCode": 200,
        "body": json.dumps("Processing complete.")
    }

