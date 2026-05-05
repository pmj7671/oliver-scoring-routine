import csv
import json
import os
import sys
import time
import requests
from dotenv import load_dotenv

load_dotenv()

ASPIRE_API_URL = "https://api.aspiredatanetwork.com/v1/match"
ASPIRE_API_KEY = os.getenv("ASPIRE_API_KEY")

# Zoho export columns -> Aspire input fields
FIELD_MAP = {
    "Id": "id",
    "First_Name": "first",
    "Last_Name": "last",
    "Street": "address",
    "Zip_Code": "zip",
    "Phone": "phone",
    "Email": "email",
}


def read_and_filter(csv_path):
    """Read Zoho bulk export CSV and return only rows where HPPS,
    Probability_Score, and Prospect_Segment are all blank."""
    rows = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            hpps = row.get("HPPS", "").strip()
            prob = row.get("Probability_Score", "").strip()
            seg = row.get("Prospect_Segment", "").strip()
            if not hpps and not prob and not seg:
                rows.append(row)
    return rows


def build_aspire_payload(rows):
    """Convert filtered Zoho rows into Aspire API request records.
    Skips records that lack the minimum required fields:
    (address + zip) or phone or email."""
    records = []
    skipped = 0
    for row in rows:
        record = {}
        for zoho_col, aspire_field in FIELD_MAP.items():
            value = row.get(zoho_col, "").strip()
            if value:
                record[aspire_field] = value
        # Must have at least: (address + zip) or phone or email
        has_address = "address" in record and "zip" in record
        has_phone = "phone" in record
        has_email = "email" in record
        if has_address or has_phone or has_email:
            records.append(record)
        else:
            skipped += 1
    if skipped:
        print(f"Skipped {skipped} records (no address+zip, phone, or email)")
    return records


def call_aspire(batch):
    """Send a batch of records to Aspire and return the response list."""
    headers = {
        "x-api-key": ASPIRE_API_KEY,
        "Content-Type": "application/json",
    }
    resp = requests.post(ASPIRE_API_URL, headers=headers, json=batch, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    if data.get("status", {}).get("status_code") != 200:
        print(f"  API error: {data.get('status', {}).get('message')}")
        return []

    return data.get("data", {}).get("response", [])


def enrich(csv_path, output_path):
    print(f"Reading: {csv_path}")
    rows = read_and_filter(csv_path)
    print(f"Filtered records (all three fields blank): {len(rows)}")

    records = build_aspire_payload(rows)
    print(f"Records with enough data for Aspire: {len(records)}")

    if not records:
        print("No records to enrich.")
        return

    # Process in batches of 100 (default; API will tell us max)
    batch_size = 100
    all_results = []
    total_batches = (len(records) + batch_size - 1) // batch_size

    for i in range(0, len(records), batch_size):
        batch = records[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        print(f"\nBatch {batch_num}/{total_batches} — sending {len(batch)} records...")

        try:
            results = call_aspire(batch)
            matched = sum(1 for r in results if r.get("meta", {}).get("match") == 1)
            print(f"  Returned {len(results)} results ({matched} matched)")
            all_results.extend(results)
        except requests.exceptions.HTTPError as e:
            print(f"  HTTP error: {e}")
        except Exception as e:
            print(f"  Error: {e}")

        # Brief pause between batches to be respectful of rate limits
        if i + batch_size < len(records):
            time.sleep(1)

    # Write results to CSV
    if not all_results:
        print("\nNo results to write.")
        return

    # Collect all result field names across all responses
    meta_fields = ["id", "match", "match_type", "verified_phone", "verified_email"]
    result_fields = set()
    for item in all_results:
        result_fields.update(item.get("result", {}).keys())
    result_fields = sorted(result_fields)

    fieldnames = meta_fields + result_fields

    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for item in all_results:
            meta = item.get("meta", {})
            result = item.get("result", {})
            row = {
                "id": meta.get("id", ""),
                "match": meta.get("match", ""),
                "match_type": meta.get("match_type", ""),
                "verified_phone": meta.get("verified_phone", ""),
                "verified_email": meta.get("verified_email", ""),
            }
            row.update(result)
            writer.writerow(row)

    print(f"\n=== Results ===")
    total = len(all_results)
    matched = sum(1 for r in all_results if r.get("meta", {}).get("match") == 1)
    print(f"Total processed: {total}")
    print(f"Matched: {matched}")
    print(f"Unmatched: {total - matched}")
    print(f"Output saved to: {output_path}")


if __name__ == "__main__":
    if not ASPIRE_API_KEY:
        print("Error: ASPIRE_API_KEY not set in .env")
        sys.exit(1)

    # Default to the most recent Zoho export if no path provided
    if len(sys.argv) >= 2:
        input_path = sys.argv[1]
    else:
        input_path = "ZOHO Lead Files Downloads/5887454000087783289.csv"

    if not os.path.exists(input_path):
        print(f"File not found: {input_path}")
        sys.exit(1)

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join("Aspire Downloads", f"Aspire_Enrichment_{timestamp}.csv")

    enrich(input_path, output_path)
