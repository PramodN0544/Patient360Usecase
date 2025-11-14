# app/S3connection.py
from http.client import HTTPException
import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION")

if not all([AWS_ACCESS_KEY, AWS_SECRET_KEY, AWS_BUCKET_NAME, AWS_REGION]):
    raise Exception("Missing AWS credentials or bucket info in .env")

# Create a single S3 client (credentials are only on server, never exposed)
s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)

def generate_presigned_url(file_key: str, expiration: int = 3600, disposition: str = "inline") -> str:
    """
    Generates a presigned URL for S3 object securely.
    :param file_key: Key of the S3 file
    :param expiration: Expiration in seconds (default 1 hour)
    :param disposition: "inline" to view, "attachment" to download
    :return: Presigned URL
    """
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": AWS_BUCKET_NAME,
                "Key": file_key,
                "ResponseContentDisposition": f'{disposition}; filename="{os.path.basename(file_key)}"'
            },
            ExpiresIn=expiration
        )
        return url
    except ClientError as e:
        print("❌ Error generating presigned URL:", e)
        return None

async def upload_lab_result_to_s3(file, patient_id: int, lab_order_id: int, hospital_id: int, encounter_id: int) -> str:
    """
    Uploads a file to S3 under structured path: hospital/patient/encounter/lab_order.pdf
    :return: file_key
    """
    file_key = f"hospital_{hospital_id}/patient_{patient_id}/encounter_{encounter_id}/lab_order_{lab_order_id}.pdf"
    try:
        s3_client.upload_fileobj(file.file, AWS_BUCKET_NAME, file_key)
        return file_key
    except ClientError as e:
        print("❌ Error uploading file to S3:", e)
        raise HTTPException(status_code=500, detail="Failed to upload file")
