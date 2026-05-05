"""
Automated Daily Zoho Lead Download
===================================
Downloads all Oliver RV leads from Zoho CRM via Bulk Read API,
extracts CSV, saves with timestamp, cleans old files, and sends
email status alerts.

Usage:
    python daily_lead_download.py
"""

import csv
import os
import smtplib
import sys
import time
import zipfile
from datetime import datetime, timedelta
from email.mime.text import MIMEText
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

# --- Configuration -----------------------------------------------------------

load_dotenv()

SCRIPT_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = SCRIPT_DIR.parent / "ZOHOLeads_Download"
LOG_FILE = SCRIPT_DIR / "download_log.csv"

GMAIL_SENDER = os.getenv("GMAIL_SENDER", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
ALERT_RECIPIENTS = [
    addr.strip()
    for addr in os.getenv("ALERT_RECIPIENTS", "").split(",")
    if addr.strip()
]

POLL_INTERVAL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 600  # 10 minutes
MAX_RETRIES = 2
RETRY_DELAY_SECONDS = 30
MIN_EXPECTED_SIZE_BYTES = 1_000_000  # 1 MB — expect ~47 MB for 37K+ leads
CLEANUP_DAYS = 7
FILE_PREFIX = "Oliver_Leads_"


# --- Zoho SDK ----------------------------------------------------------------

def initialize_zoho():
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
    module.set_api_name("Leads")
    query.set_module(module)
    query.set_page(1)
    request.set_query(query)

    response = ops.create_bulk_read_job(request)
    if response is None:
        raise RuntimeError("No response from Zoho Bulk Read API")

    status_code = response.get_status_code()
    response_object = response.get_object()

    if isinstance(response_object, ActionWrapper):
        for action_response in response_object.get_data():
            if isinstance(action_response, SuccessResponse):
                job_id = action_response.get_details().get("id")
                print(f"Bulk read job created: {job_id}")
                return job_id
            elif isinstance(action_response, APIException):
                msg = action_response.get_message().get_value()
                raise RuntimeError(f"Zoho API error: {msg}")
    elif isinstance(response_object, APIException):
        msg = response_object.get_message().get_value()
        raise RuntimeError(f"Zoho API error (status {status_code}): {msg}")

    raise RuntimeError(f"Unexpected response (status {status_code})")


def poll_job(job_id):
    ops = BulkReadOperations()
    start = time.time()

    while time.time() - start < POLL_TIMEOUT_SECONDS:
        time.sleep(POLL_INTERVAL_SECONDS)
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
                if state == "FAILED":
                    raise RuntimeError("Zoho bulk read job FAILED")

    raise RuntimeError(
        f"Polling timed out after {POLL_TIMEOUT_SECONDS}s — job {job_id} did not complete"
    )


def download_zip(job_id):
    ops = BulkReadOperations()
    response = ops.download_result(int(job_id))

    if response is None:
        raise RuntimeError("No download response from Zoho")

    if response.get_status_code() in (204, 304):
        raise RuntimeError(f"No content to download (status {response.get_status_code()})")

    response_object = response.get_object()
    if isinstance(response_object, FileBodyWrapper):
        stream = response_object.get_file()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = SCRIPT_DIR / f"_temp_leads_{timestamp}.zip"
        with open(zip_path, "wb") as f:
            for chunk in stream.get_stream():
                f.write(chunk)
        print(f"Downloaded ZIP: {zip_path} ({zip_path.stat().st_size:,} bytes)")
        return zip_path
    elif isinstance(response_object, APIException):
        msg = response_object.get_message().get_value()
        raise RuntimeError(f"Download error: {msg}")

    raise RuntimeError("Unexpected download response")


# --- File Processing ---------------------------------------------------------

def extract_csv(zip_path):
    with zipfile.ZipFile(zip_path, "r") as zf:
        csv_files = [n for n in zf.namelist() if n.endswith(".csv")]
        if not csv_files:
            raise RuntimeError(f"No CSV found in ZIP: {zip_path}")
        csv_name = csv_files[0]
        zf.extract(csv_name, SCRIPT_DIR)
        return SCRIPT_DIR / csv_name


def count_csv_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        return sum(1 for _ in reader)


def save_to_output(csv_path):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = OUTPUT_DIR / f"{FILE_PREFIX}{timestamp}.csv"
    csv_path.rename(dest)
    print(f"Saved: {dest}")
    return dest


def cleanup_old_files():
    cutoff = datetime.now() - timedelta(days=CLEANUP_DAYS)
    deleted = []
    if not OUTPUT_DIR.exists():
        return deleted

    for f in OUTPUT_DIR.glob(f"{FILE_PREFIX}*.csv"):
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        if mtime < cutoff:
            size = f.stat().st_size
            f.unlink()
            deleted.append(f"{f.name} ({size:,} bytes, modified {mtime:%Y-%m-%d})")
            print(f"Deleted old file: {f.name}")

    return deleted


# --- Email -------------------------------------------------------------------

def send_email(subject, body):
    if not GMAIL_SENDER or not GMAIL_APP_PASSWORD or not ALERT_RECIPIENTS:
        print("Email not configured — skipping alert")
        return

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_SENDER
    msg["To"] = ", ".join(ALERT_RECIPIENTS)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_SENDER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_SENDER, ALERT_RECIPIENTS, msg.as_string())
        print(f"Alert email sent to: {', '.join(ALERT_RECIPIENTS)}")
    except Exception as e:
        print(f"Failed to send email: {e}")


# --- Logging -----------------------------------------------------------------

def log_run(status, filename="", file_size=0, record_count=0, files_cleaned=0, error=""):
    write_header = not LOG_FILE.exists()
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow([
                "timestamp", "status", "filename", "file_size_bytes",
                "record_count", "files_cleaned", "error",
            ])
        writer.writerow([
            datetime.now().isoformat(),
            status,
            filename,
            file_size,
            record_count,
            files_cleaned,
            error,
        ])


# --- Main Workflow -----------------------------------------------------------

def run():
    timestamp_display = datetime.now().strftime("%Y-%m-%d")
    zip_path = None
    temp_csv = None

    try:
        print("=" * 60)
        print(f"Oliver RV Lead Download — {timestamp_display}")
        print("=" * 60)

        # Step 1: Initialize Zoho
        print("\n[1/7] Initializing Zoho SDK...")
        initialize_zoho()

        # Step 2: Create bulk read job (with retry)
        job_id = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                print(f"\n[2/7] Creating bulk read job (attempt {attempt + 1})...")
                job_id = create_bulk_read_job()
                break
            except RuntimeError as e:
                if attempt < MAX_RETRIES:
                    print(f"  Retrying in {RETRY_DELAY_SECONDS}s... ({e})")
                    time.sleep(RETRY_DELAY_SECONDS)
                else:
                    raise

        # Step 3: Poll for completion
        print(f"\n[3/7] Polling job {job_id} (timeout: {POLL_TIMEOUT_SECONDS}s)...")
        poll_job(job_id)

        # Step 4: Download ZIP
        print("\n[4/7] Downloading results...")
        zip_path = download_zip(job_id)

        # Step 5: Extract and validate CSV
        print("\n[5/7] Extracting CSV...")
        temp_csv = extract_csv(zip_path)
        file_size = temp_csv.stat().st_size
        record_count = count_csv_rows(temp_csv)
        print(f"  Records: {record_count:,}")
        print(f"  Size: {file_size:,} bytes ({file_size / 1_000_000:.1f} MB)")

        warnings = []
        if file_size < MIN_EXPECTED_SIZE_BYTES:
            warnings.append(
                f"WARNING: File size ({file_size:,} bytes) is smaller than expected "
                f"(minimum {MIN_EXPECTED_SIZE_BYTES:,} bytes)"
            )
            print(f"  {warnings[-1]}")

        # Step 6: Save to output folder
        print("\n[6/7] Saving to output folder...")
        dest = save_to_output(temp_csv)
        temp_csv = None  # moved, no longer at temp location

        # Step 7: Cleanup old files
        print("\n[7/7] Cleaning up files older than 7 days...")
        deleted = cleanup_old_files()
        print(f"  Deleted {len(deleted)} old file(s)")

        # Log and email
        log_run("SUCCESS", dest.name, file_size, record_count, len(deleted))

        body_lines = [
            f"Status: SUCCESS",
            f"File: {dest.name}",
            f"Records: {record_count:,}",
            f"File Size: {file_size:,} bytes ({file_size / 1_000_000:.1f} MB)",
            f"Saved To: {dest}",
            f"Files Cleaned Up: {len(deleted)}",
        ]
        if deleted:
            body_lines.append("\nDeleted Files:")
            for d in deleted:
                body_lines.append(f"  - {d}")
        if warnings:
            body_lines.append("\nWarnings:")
            for w in warnings:
                body_lines.append(f"  - {w}")

        send_email(
            f"[SUCCESS] Oliver RV Lead Download - {timestamp_display}",
            "\n".join(body_lines),
        )

        print(f"\nDone. Saved {dest.name}")

    except Exception as e:
        error_msg = str(e)
        print(f"\nFAILED: {error_msg}")

        log_run("FAILED", error=error_msg)

        send_email(
            f"[FAILED] Oliver RV Lead Download - {timestamp_display}",
            f"Status: FAILED\nError: {error_msg}\n\nCheck logs at: {LOG_FILE}",
        )

        sys.exit(1)

    finally:
        # Clean up temp files
        if zip_path and zip_path.exists():
            zip_path.unlink()
        if temp_csv and temp_csv.exists():
            temp_csv.unlink()


if __name__ == "__main__":
    run()
