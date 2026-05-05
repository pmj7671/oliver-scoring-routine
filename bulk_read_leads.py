import os
import time
from datetime import datetime
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


def initialize():
    environment = USDataCenter.PRODUCTION()
    token = OAuthToken(
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
    )
    Initializer.initialize(environment, token)


def create_bulk_read_job(module_api_name):
    bulk_read_operations = BulkReadOperations()
    request = BodyWrapper()

    query = Query()
    module = MinifiedModule()
    module.set_api_name(module_api_name)
    query.set_module(module)
    query.set_page(1)

    request.set_query(query)

    response = bulk_read_operations.create_bulk_read_job(request)
    if response is None:
        print("No response received.")
        return None

    print("Status Code: " + str(response.get_status_code()))
    response_object = response.get_object()

    if isinstance(response_object, ActionWrapper):
        for action_response in response_object.get_data():
            if isinstance(action_response, SuccessResponse):
                print("Status: " + action_response.get_status().get_value())
                print("Code: " + action_response.get_code().get_value())
                details = action_response.get_details()
                job_id = details.get("id")
                print("Job ID: " + str(job_id))
                print("Message: " + action_response.get_message().get_value())
                return job_id
            elif isinstance(action_response, APIException):
                print("Error Status: " + action_response.get_status().get_value())
                print("Error Code: " + action_response.get_code().get_value())
                print("Message: " + action_response.get_message().get_value())
                details = action_response.get_details()
                for key, value in details.items():
                    print(f"  {key}: {value}")
    elif isinstance(response_object, APIException):
        print("Error Status: " + response_object.get_status().get_value())
        print("Error Code: " + response_object.get_code().get_value())
        print("Message: " + str(response_object.get_message()))
        details = response_object.get_details()
        for key, value in details.items():
            print(f"  {key}: {value}")

    return None


def check_job_status(job_id):
    bulk_read_operations = BulkReadOperations()
    response = bulk_read_operations.get_bulk_read_job_details(int(job_id))

    if response is None:
        print("No response received.")
        return None

    response_object = response.get_object()
    if isinstance(response_object, ResponseWrapper):
        for job in response_object.get_data():
            state = job.get_state().get_value()
            print(f"Job State: {state}")
            result = job.get_result()
            if result and result.get_download_url():
                print(f"Download URL: {result.get_download_url()}")
            return state
    elif isinstance(response_object, APIException):
        print("Error: " + response_object.get_code().get_value())
        print("Message: " + str(response_object.get_message()))

    return None


def download_result(job_id, destination_folder="./"):
    bulk_read_operations = BulkReadOperations()
    response = bulk_read_operations.download_result(int(job_id))

    if response is None:
        print("No response received.")
        return

    print("Status Code: " + str(response.get_status_code()))

    if response.get_status_code() in [204, 304]:
        print("No Content" if response.get_status_code() == 204 else "Not Modified")
        return

    response_object = response.get_object()

    if isinstance(response_object, FileBodyWrapper):
        stream_wrapper = response_object.get_file()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_name = stream_wrapper.get_name()
        name, ext = os.path.splitext(original_name)
        file_name = os.path.join(destination_folder, f"Leads_{timestamp}{ext}")
        with open(file_name, "wb") as f:
            for chunk in stream_wrapper.get_stream():
                f.write(chunk)
        print(f"Downloaded to: {file_name}")
    elif isinstance(response_object, APIException):
        print("Error: " + response_object.get_status().get_value())
        print("Code: " + response_object.get_code().get_value())
        print("Message: " + response_object.get_message().get_value())
        details = response_object.get_details()
        for key, value in details.items():
            print(f"  {key}: {value}")


if __name__ == "__main__":
    initialize()
    print("=== Creating Bulk Read Job for Leads ===")
    job_id = create_bulk_read_job("Leads")

    if job_id:
        print("\n=== Polling Job Status ===")
        while True:
            time.sleep(5)
            state = check_job_status(job_id)
            if state == "COMPLETED":
                print("\n=== Downloading Results ===")
                download_result(job_id)
                break
            elif state in ("FAILED", None):
                print("Job failed or could not get status.")
                break
            else:
                print("Waiting 5 seconds...")
