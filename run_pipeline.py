# run_pipeline.py  — single command to score + report
import subprocess, sys
from datetime import datetime

# ── Config ──────────────────────────────────────────────────────
ZOHO_FILE   = 'zoho/Oliver_Leads_20260504_062818.csv'
ASPIRE_FILE = 'aspire/Aspire_Enrichment_20260504_063347.csv'
DATE_STR    = datetime.today().strftime('%Y_%m_%d')
SCORED_FILE = f'output/Oliver_Leads_Scored_{DATE_STR}.csv'
REPORT_FILE = f'output/Oliver_Lead_Report_{DATE_STR}.pdf'
BATCH_DATE  = datetime.today().strftime('%B %-d, %Y')

# ── Step 1: Score ────────────────────────────────────────────────
print("Running scorer...")
subprocess.run([sys.executable, 'score_new_leads.py',
    '--zoho',   ZOHO_FILE,
    '--aspire', ASPIRE_FILE,
    '--output', SCORED_FILE], check=True)

# ── Step 2: Report ───────────────────────────────────────────────
print("Generating report...")
subprocess.run([sys.executable, 'generate_lead_report.py',
    '--input',  SCORED_FILE,
    '--output', REPORT_FILE,
    '--batch',  BATCH_DATE], check=True)

print(f"\nDone! Files saved:")
print(f"  {SCORED_FILE}")
print(f"  {REPORT_FILE}")