import os
import boto3
from fastapi import UploadFile
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv()  # Load .env file

AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_KEY")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME")
AWS_REGION = os.getenv("AWS_REGION")

if not AWS_ACCESS_KEY or not AWS_SECRET_KEY or not AWS_BUCKET_NAME or not AWS_REGION:
    raise Exception("❌ Missing AWS config in .env file")

s3_client = boto3.client(
    "s3",
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name=AWS_REGION
)


async def upload_lab_result_to_s3(
    file: UploadFile,
    patient_id: int,
    lab_order_id: int,
    hospital_id: int,
    encounter_id: int
):
    """
    Upload lab result PDF to S3 with structure:
    hospital_<hospital_id>/patient_<patient_id>/encounter_<encounter_id>/lab_order_<lab_order_id>.pdf
    """

    folder_path = f"hospital_{hospital_id}/patient_{patient_id}/encounter_{encounter_id}"
    file_key = f"{folder_path}/lab_order_{lab_order_id}.pdf"

    try:
        s3_client.upload_fileobj(
            file.file,
            AWS_BUCKET_NAME,
            file_key,
            ExtraArgs={"ContentType": "application/pdf"}
        )
    except ClientError as e:
        raise Exception(f"Failed to upload file to S3: {str(e)}")

    file_url = f"https://{AWS_BUCKET_NAME}.s3.{AWS_REGION}.amazonaws.com/{file_key}"
    return file_url
