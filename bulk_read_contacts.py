import os
import sys
import time
import zipfile
from pathlib import Path
from dotenv import load_dotenv

from zohocrmsdk.src.com.zoho.api.authenticator import OAuthToken
from zohocrmsdk.src.com.zoho.crm.api import Initializer
from zohocrmsdk.src.com.zoho.crm.api.dc import USDataCenter
from zohocrmsdk.src.com.zoho.crm.api.modules import MinifiedModule
from zohocrmsdk.src.com.zoho.crm.api.bulk_read import (
    BulkReadOperations,
    BodyWrapper,
    Query,
    ActionWrapper,
    SuccessResponse,
    APIException,
    ResponseWrapper,
    FileBodyWrapper,
)

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR / "ZOHO Contact Files Downloads"
POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 600


def initialize():
    environment = USDataCenter.PRODUCTION()
    token = OAuthToken(
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
    )
    Initializer.initialize(environment, token)


def create_bulk_read_job():
    ops = BulkReadOperations()
    request = BodyWrapper()
    query = Query()
    module = MinifiedModule()
    module.set_api_name("Contacts")
    query.set_module(module)
    query.set_page(1)
    request.set_query(query)

    response = ops.create_bulk_read_job(request)
    if response is None:
        print("No response received.")
        return None

    response_object = response.get_object()
    if isinstance(response_object, ActionWrapper):
        for action_response in response_object.get_data():
            if isinstance(action_response, SuccessResponse):
                job_id = action_response.get_details().get("id")
                print(f"Bulk read job created: {job_id}")
                return job_id
            elif isinstance(action_response, APIException):
                print(f"Error: {action_response.get_code().get_value()} - {action_response.get_message().get_value()}")
    return None


def poll_job(job_id):
    ops = BulkReadOperations()
    elapsed = 0
    while elapsed < POLL_TIMEOUT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
        elapsed += POLL_INTERVAL_SECONDS
        response = ops.get_bulk_read_job_details(int(job_id))
        if response is None:
            continue
        response_object = response.get_object()
        if isinstance(response_object, ResponseWrapper):
            for job in response_object.get_data():
                state = job.get_state().get_value()
                print(f"  Job state: {state}")
                if state == "COMPLETED":
                    return True
                elif state == "FAILED":
                    print("Job failed.")
                    return False
    print("Polling timed out.")
    return False


def download_and_extract(job_id):
    ops = BulkReadOperations()
    response = ops.download_result(int(job_id))
    if response is None:
        print("No response received.")
        return None

    if response.get_status_code() in [204, 304]:
        print("No content returned.")
        return None

    response_object = response.get_object()
    if not isinstance(response_object, FileBodyWrapper):
        print("Unexpected response type.")
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    zip_path = SCRIPT_DIR / f"_temp_contacts_{timestamp}.zip"
    stream_wrapper = response_object.get_file()
    with open(zip_path, "wb") as f:
        for chunk in stream_wrapper.get_stream():
            f.write(chunk)
    print(f"Downloaded ZIP: {zip_path} ({zip_path.stat().st_size:,} bytes)")

    # Extract CSV from ZIP
    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_names = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_names:
            print("No CSV found in ZIP.")
            zip_path.unlink()
            return None
        csv_name = csv_names[0]
        extracted = zf.read(csv_name)

    zip_path.unlink()

    # Count records (subtract header row)
    record_count = extracted.count(b"\n") - 1
    output_path = OUTPUT_DIR / f"Oliver_Contacts_{timestamp}.csv"
    output_path.write_bytes(extracted)

    print(f"  Records: {record_count:,}")
    print(f"  Size: {len(extracted):,} bytes ({len(extracted) / 1_048_576:.1f} MB)")
    print(f"Saved: {output_path}")
    return output_path


if __name__ == "__main__":
    print("=" * 60)
    print(f"Oliver RV Contact Download — {time.strftime('%Y-%m-%d')}")
    print("=" * 60)

    print("\n[1/4] Initializing Zoho SDK...")
    initialize()

    print("\n[2/4] Creating bulk read job...")
    job_id = create_bulk_read_job()
    if not job_id:
        print("Failed to create job.")
        sys.exit(1)

    print(f"\n[3/4] Polling job {job_id} (timeout: {POLL_TIMEOUT_SECONDS}s)...")
    if not poll_job(job_id):
        print("Job did not complete successfully.")
        sys.exit(1)

    print("\n[4/4] Downloading and extracting...")
    output = download_and_extract(job_id)
    if output:
        print(f"\nDone. Saved {output.name}")
