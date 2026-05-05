import csv
import os
import sys
from dotenv import load_dotenv

from zohocrmsdk.src.com.zoho.api.authenticator import OAuthToken
from zohocrmsdk.src.com.zoho.crm.api import Initializer
from zohocrmsdk.src.com.zoho.crm.api.dc import USDataCenter
from zohocrmsdk.src.com.zoho.crm.api.record import (
    RecordOperations,
    BodyWrapper,
    Record,
    ActionWrapper,
    SuccessResponse,
    APIException,
)
from zohocrmsdk.src.com.zoho.crm.api.util import Choice

load_dotenv()

# Fields to update — only these columns will be sent to Zoho
UPDATE_FIELDS = [
    "Probability_Score",
    "Prospect_Segment",
    "Marketing_Narrative_2",
    "HPPS",
    "FCI_Tier",
    "Lifestyle_Classification",
    "Lead_Class",
]

# CSV column aliases — maps alternate CSV column names to Zoho field names
CSV_COLUMN_ALIASES = {
    "Buyer_Priority_Score": "Probability_Score",
    "FCI_Corrected": "HPPS",
    "persona": "Lifestyle_Classification",
    "Marketing_Narrative": "Marketing_Narrative_2",
}

# CSV-to-Zoho picklist mappings
PROSPECT_SEGMENT_MAP = {
    "Buy-New": "New Buyer",
    "Buy-Used": "Used Buyer",
    "No-Buy": "Non-Customer",
    "Discovery_Call": "-None-",
    "New Buyer": "New Buyer",
    "Used Buyer": "Used Buyer",
    "Non-Customer": "Non-Customer",
}

FCI_TIER_MAP = {
    "Tier 4 \u2014 Premium": "Tier 4 - Premium",
    "Tier 3 \u2014 Capable": "Tier 3 - Capable",
    "Tier 2 \u2014 Emerging": "Tier 2 - Emerging",
    "Tier 4 - Premium": "Tier 4 - Premium",
    "Tier 3 - Capable": "Tier 3 - Capable",
    "Tier 2 - Emerging": "Tier 2 - Emerging",
    "To Be Determined": "TBD",
}

LIFESTYLE_CLASSIFICATION_MAP = {
    "The Landed Outdoorsman": "Outdoorsman - P1",
    "The Heritage Camper": "Heritage - P1",
    "The Alpine Explorer": "Alpine - P2",
    "The Field & Fairway": "Solo - P3",
    "The Field & Fairway Woman": "Solo - P3",
    "The Wellness Wanderer": "Wanderer - P3",
    "The Aspirational Sophisticate": "Aspirational - P3",
    "Oliver Discovery": "-None-",
}


def initialize():
    environment = USDataCenter.PRODUCTION()
    token = OAuthToken(
        client_id=os.getenv("ZOHO_CLIENT_ID"),
        client_secret=os.getenv("ZOHO_CLIENT_SECRET"),
        refresh_token=os.getenv("ZOHO_REFRESH_TOKEN"),
    )
    Initializer.initialize(environment, token)


def read_csv(file_path):
    rows = []
    with open(file_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def build_records(rows):
    records = []
    skipped = 0
    for row in rows:
        lead_id = row.get("Id", "").strip()
        if not lead_id:
            skipped += 1
            continue

        # Only include fields that have a non-empty value
        fields_to_send = {}
        for field in UPDATE_FIELDS:
            csv_col = next((k for k, v in CSV_COLUMN_ALIASES.items() if v == field), field)
            value = row.get(csv_col, row.get(field, "")).strip()
            if value:
                if field == "Probability_Score":
                    value = int(value.replace("%", ""))
                elif field == "HPPS":
                    value = int(value)
                elif field == "Prospect_Segment":
                    mapped = PROSPECT_SEGMENT_MAP.get(value)
                    if mapped is None:
                        print(f"  WARNING: Unknown Prospect_Segment '{value}' for ID {lead_id}, skipping field")
                        continue
                    value = Choice(mapped)
                elif field == "FCI_Tier":
                    mapped = FCI_TIER_MAP.get(value)
                    if mapped is None:
                        print(f"  WARNING: Unknown FCI_Tier '{value}' for ID {lead_id}, skipping field")
                        continue
                    value = Choice(mapped)
                elif field == "Lifestyle_Classification":
                    mapped = LIFESTYLE_CLASSIFICATION_MAP.get(value)
                    if mapped is None:
                        print(f"  WARNING: Unknown Lifestyle_Classification '{value}' for ID {lead_id}, skipping field")
                        continue
                    if mapped == "-None-":
                        continue  # skip sending -None- values
                    value = Choice(mapped)
                elif field == "Lead_Class":
                    value = Choice(value)
                fields_to_send[field] = value

        if not fields_to_send:
            skipped += 1
            continue

        record = Record()
        record.set_id(int(lead_id))
        for field_name, value in fields_to_send.items():
            record.add_key_value(field_name, value)

        records.append(record)

    if skipped:
        print(f"Skipped {skipped} rows (no Id or no fields to update)")
    return records


def update_leads_batch(records):
    ops = RecordOperations("Leads")
    total = len(records)
    success_count = 0
    fail_count = 0
    errors = []

    # Process in batches of 100
    for i in range(0, total, 100):
        batch = records[i : i + 100]
        batch_num = (i // 100) + 1
        total_batches = (total + 99) // 100
        print(f"\nBatch {batch_num}/{total_batches} — sending {len(batch)} records...")

        body = BodyWrapper()
        body.set_data(batch)

        response = ops.update_records(body)

        if response is None:
            print("  No response received.")
            fail_count += len(batch)
            continue

        status_code = response.get_status_code()
        response_object = response.get_object()

        if isinstance(response_object, ActionWrapper):
            for action_response in response_object.get_data():
                if isinstance(action_response, SuccessResponse):
                    success_count += 1
                elif isinstance(action_response, APIException):
                    fail_count += 1
                    details = action_response.get_details()
                    record_id = details.get("id", "unknown") if details else "unknown"
                    errors.append(
                        f"  ID {record_id}: {action_response.get_code().get_value()} - {action_response.get_message().get_value()}"
                    )
        elif isinstance(response_object, APIException):
            print(f"  Batch error: {response_object.get_code().get_value()}")
            print(f"  Message: {response_object.get_message().get_value()}")
            fail_count += len(batch)

    return success_count, fail_count, errors


def update_leads_from_csv(csv_path):
    print(f"Reading CSV: {csv_path}")
    rows = read_csv(csv_path)
    print(f"Total rows in CSV: {len(rows)}")

    print(f"\nBuilding update records for fields: {', '.join(UPDATE_FIELDS)}")
    records = build_records(rows)
    print(f"Records to update: {len(records)}")

    if not records:
        print("No records to update.")
        return

    print("\n=== Starting Updates ===")
    success, failures, errors = update_leads_batch(records)

    print("\n=== Results ===")
    print(f"Successful: {success}")
    print(f"Failed: {failures}")
    if errors:
        print("\nErrors:")
        for err in errors:
            print(err)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python bulk_lead_update.py <path_to_csv>")
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"File not found: {csv_path}")
        sys.exit(1)

    initialize()
    update_leads_from_csv(csv_path)
