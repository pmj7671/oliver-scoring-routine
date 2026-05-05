"""
score_new_leads.py
==================
Oliver Travel Trailers — Standalone Lead Scoring Script
Version: V5.5  |  May 2026

PURPOSE
-------
Scores a new batch of leads using the trained LightGBM model and
K-Prototypes persona clusters — no retraining required.

Joins the Zoho CRM export with the Aspire enrichment file,
scores every lead, and produces a Zoho-compliant output CSV.

REQUIRED FILES
--------------
1. oliver_xgboost_model.pkl        — trained LightGBM classifier + encoders
2. oliver_kprototypes_clusters.pkl — K-Prototypes model for persona assignment
3. <zoho_file>.csv                 — Zoho CRM export (Id, names, email)
4. <aspire_file>.csv               — Aspire enrichment file (id + 39 features)

USAGE
-----
    python score_new_leads.py

    Update these 3 lines in the CONFIG section before each run:
        ZOHO_FILE    — Zoho CRM export filename
        ASPIRE_FILE  — Aspire enrichment filename
        OUTPUT_FILE  — desired output filename

ZOHO FIELD REQUIREMENTS
-----------------------
    Buyer_Priority_Score  — whole number (0-100 scale)
    FCI_Corrected         — whole number
    Lead_Class            — picklist: Hot Lead / Warm Lead / Cool Lead only
    Id                    — match key for Zoho import

OUTPUT COLUMN GUIDE
-------------------
    Id                       — Zoho record Id (match key for import)
    Sales_Rank               — 1 = hottest lead
    First Name / Last Name   — from Zoho export
    Email                    — from Zoho export
    Prospect_Segment         — New Buyer / Used Buyer / Non-Customer (Zoho field)
    Lead_Class               — Hot Lead / Warm Lead / Cool Lead
    Sales_Priority           — Priority 1 / 2 / 3
    Buyer_Priority_Score     — 0-100 whole number (main sort field)
    Prob_Buy_New             — probability of new unit purchase (0-1)
    Prob_Buy_Used            — probability of used unit purchase (0-1)
    Prob_No_Buy              — probability of no purchase (0-1)
    Financial_Data_Available — True/False
    FCI_Corrected            — 0-100 whole number financial capability score
    FCI_Tier                 — Tier 1-4 label
    persona                  — K-Prototypes segment name
    persona_priority         — Priority 1 Hot / 2 Warm / 3 Nurture
    Marketing_Narrative      — personalised outreach guidance for sales rep
"""

import pandas as pd
import numpy as np
import pickle
import warnings
warnings.filterwarnings('ignore')

from sklearn.preprocessing import StandardScaler

# ══════════════════════════════════════════════════════════════════════════════
# CONFIG — update these 3 lines before each run
# ══════════════════════════════════════════════════════════════════════════════
ZOHO_FILE   = 'Oliver_Leads_20260504_062818.csv'       # ← Zoho CRM export
ASPIRE_FILE = 'Aspire_Enrichment_20260504_063347.csv'  # ← Aspire enrichment
OUTPUT_FILE = 'Oliver_Leads_Scored_2026_05_04.csv'     # ← output filename

# Model files — only update when switching to a new model version
MODEL_FILE   = 'V5_5_3_18_2026_oliver_xgboost_model.pkl'
CLUSTER_FILE = 'V5_5_3_18_2026_oliver_kprototypes_clusters.pkl'

# ── Do not edit below this line unless changing business logic ────────────────

# Net worth score map — extended to handle all Aspire return values (A-O)
NW_MAP = {'O':10,'N':10,'M':8,'L':7,'K':6,'J':5,'I':4,
           'H':3,'G':2,'F':2,'E':1,'D':1,'C':1,'B':1,'A':1}

# Persona names — must match PERSONA_MAP in training notebook
PERSONA_MAP = {
    3: 'The Heritage Camper',
    2: 'The Landed Outdoorsman',
    4: 'The Alpine Explorer',
    5: 'The Field & Fairway',
    0: 'The Wellness Wanderer',
    1: 'The Aspirational Sophisticate',
}
PRIORITY_MAP = {
    'The Landed Outdoorsman':        'Priority 1 — Hot',
    'The Heritage Camper':           'Priority 1 — Hot',
    'The Alpine Explorer':           'Priority 2 — Warm',
    'The Field & Fairway':           'Priority 3 — Nurture',
    'The Wellness Wanderer':         'Priority 3 — Nurture',
    'The Aspirational Sophisticate': 'Priority 3 — Nurture',
}

# Zoho picklist values — must match Zoho field definitions exactly
SALES_PRIORITY_MAP = {
    'Hot Lead':  'Priority 1 — Immediate Outreach',
    'Warm Lead': 'Priority 2 — Warm Outreach',
    'Cool Lead': 'Priority 3 — Nurture',
}
PROSPECT_SEGMENT_MAP = {
    'Hot Lead':  'New Buyer',
    'Warm Lead': 'New Buyer',
    'Cool Lead': 'Non-Customer',
}

# ══════════════════════════════════════════════════════════════════════════════
# STEP 1 — Load model and cluster bundles
# ══════════════════════════════════════════════════════════════════════════════
print("=" * 60)
print("STEP 1 — Loading model bundles")
print("=" * 60)

with open(MODEL_FILE, 'rb') as f:
    bundle = pickle.load(f)

model            = bundle['model']
encoders         = bundle['encoders']
feats            = bundle['features']
model_name       = bundle.get('model_name', 'LightGBM')
training_medians = bundle.get('training_medians', {})
cv_results       = bundle.get('cv_results', {})

CATEGORICAL_FEATURES = list(encoders.keys())
NUMERIC_FEATURES     = [f for f in feats if f not in CATEGORICAL_FEATURES]

print(f"  Classifier:  {model_name}")
print(f"  Features:    {len(feats)}")
print(f"  Encoders:    {len(encoders)} categorical columns")
if cv_results:
    best = max(cv_results, key=lambda k: cv_results[k]['mean'])
    print(f"  CV AUC:      {cv_results[best]['mean']:.4f} ({best})")

with open(CLUSTER_FILE, 'rb') as f:
    cluster_bundle = pickle.load(f)
kp_model = cluster_bundle['model']
print(f"  Personas:    {kp_model.n_clusters} K-Prototypes clusters")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 2 — Load and join Zoho + Aspire files
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 2 — Loading and joining Zoho + Aspire files")
print("=" * 60)

zoho   = pd.read_csv(ZOHO_FILE,   low_memory=False, encoding='latin1')
aspire = pd.read_csv(ASPIRE_FILE, low_memory=False, encoding='latin1')
print(f"  Zoho:    {len(zoho):,} records")
print(f"  Aspire:  {len(aspire):,} records")

# Join on Zoho 'Id' (capitalized) ↔ Aspire 'id' (lowercase)
leads     = zoho.merge(aspire, left_on='Id', right_on='id', how='inner')
unmatched = len(aspire) - len(leads)
print(f"  Joined:  {len(leads):,} records"
      f"{f'  ⚠ {unmatched} unmatched' if unmatched else '  ✓ perfect join'}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 3 — Normalize columns
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 3 — Normalizing columns")
print("=" * 60)

# Standard renames — Zoho and Aspire field name differences
leads = leads.rename(columns={
    'First_Name':  'First Name',
    'Last_Name':   'Last Name',
    'EDUC_MODEL':  'EDUC_MODEL_1',
    'GNDR_GNDR':   'GNDR_GNDR_1',
    'MRTL_MODEL':  'MRTL_MODEL_1',
})

# Handle EQTY_AMNT — only rename if EQTY_AMNT_I1 not already present from Aspire
if 'EQTY_AMNT_I1' not in leads.columns and 'EQTY_AMNT' in leads.columns:
    leads = leads.rename(columns={'EQTY_AMNT': 'EQTY_AMNT_I1'})

# Handle income field version difference (Aspire sometimes returns v6 or v7)
if 'lu_inc_model_v7_amt' not in leads.columns and 'lu_inc_model_v6_amt' in leads.columns:
    leads = leads.rename(columns={'lu_inc_model_v6_amt': 'lu_inc_model_v7_amt'})

# Derive age_clean from whichever age column Aspire returns
age_src = next((c for c in ['EXACT_AGE', 'EXACT_AGE_1', 'COMBINED_AGE_1']
                if c in leads.columns), None)
leads['age_clean'] = pd.to_numeric(leads[age_src], errors='coerce') \
    if age_src else np.nan

# Add any still-missing features as NaN — will be imputed in Step 4
missing_feats = [f for f in feats if f not in leads.columns]
for f in missing_feats:
    leads[f] = np.nan

if missing_feats:
    print(f"  ⚠ {len(missing_feats)} features absent — will impute: {missing_feats}")
else:
    print(f"  ✓ All 40 model features present")
print(f"  age_clean: {leads['age_clean'].notna().sum()} of {len(leads)} populated")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 4 — Encode features
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 4 — Encoding features")
print("=" * 60)

leads_enc = leads.reindex(columns=feats).copy().reset_index(drop=True)

# Categorical: use saved LabelEncoders, map unseen values to 'Unknown'
for col in CATEGORICAL_FEATURES:
    leads_enc[col] = leads_enc[col].fillna('Unknown').astype(str)
    le    = encoders[col]
    known = set(le.classes_)
    unseen = [v for v in leads_enc[col].unique() if v not in known]
    if unseen:
        print(f"  ⚠ {col}: {len(unseen)} unseen value(s) → Unknown")
    leads_enc[col] = leads_enc[col].apply(lambda v: v if v in known else 'Unknown')
    leads_enc[col] = le.transform(leads_enc[col])

# Numeric: coerce to float, fill nulls with training medians
for col in NUMERIC_FEATURES:
    leads_enc[col] = pd.to_numeric(leads_enc[col], errors='coerce')
    fill_val = training_medians.get(col, leads_enc[col].median())
    if pd.isna(fill_val): fill_val = 0
    leads_enc[col] = leads_enc[col].fillna(fill_val)

print(f"  ✓ Encoding complete | {leads_enc.isna().sum().sum()} nulls remaining")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 5 — Score with LightGBM
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print(f"STEP 5 — Scoring with {model_name}")
print("=" * 60)

X_new = leads_enc[feats].values
proba = model.predict_proba(X_new)   # shape (n_leads, 3): [P(NoBuy), P(Used), P(New)]

# Index-safe assignment — prevents NaN columns
leads = leads.reset_index(drop=True)
leads['Prob_Buy_New']         = pd.Series(proba[:, 2].round(4), index=leads.index)
leads['Prob_Buy_Used']        = pd.Series(proba[:, 1].round(4), index=leads.index)
leads['Prob_No_Buy']          = pd.Series(proba[:, 0].round(4), index=leads.index)
leads['Buyer_Priority_Score'] = pd.Series(
    np.maximum(proba[:, 2], proba[:, 1]).round(4), index=leads.index)

# Validate — fail loud if any probability column has nulls
null_check = {c: leads[c].isna().sum()
              for c in ['Prob_Buy_New', 'Prob_Buy_Used', 'Prob_No_Buy']}
if any(v > 0 for v in null_check.values()):
    raise ValueError(f"NULL PROBABILITIES DETECTED: {null_check}. Re-run from Step 3.")

print(f"  ✓ 0 nulls on all probability columns")
print(f"  Max score: {leads['Buyer_Priority_Score'].max():.4f}"
      f"  | >0.40: {(leads['Buyer_Priority_Score'] > 0.40).sum()}"
      f"  | >0.60: {(leads['Buyer_Priority_Score'] > 0.60).sum()}"
      f"  | >0.80: {(leads['Buyer_Priority_Score'] > 0.80).sum()}")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 6 — Assign personas with K-Prototypes
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 6 — Assigning personas")
print("=" * 60)

leads_kp = leads.reindex(columns=NUMERIC_FEATURES + CATEGORICAL_FEATURES).copy()
for col in NUMERIC_FEATURES:
    leads_kp[col] = pd.to_numeric(leads_kp[col], errors='coerce')
    fill = leads_kp[col].median()
    if pd.isna(fill): fill = 0
    leads_kp[col] = leads_kp[col].fillna(fill)
for col in CATEGORICAL_FEATURES:
    leads_kp[col] = leads_kp[col].fillna('Unknown').astype(str)

scaler_kp  = StandardScaler()
X_num_kp   = scaler_kp.fit_transform(leads_kp[NUMERIC_FEATURES])
X_cat_kp   = leads_kp[CATEGORICAL_FEATURES].values
X_kp       = np.hstack([X_num_kp, X_cat_kp])
cat_idx_kp = list(range(len(NUMERIC_FEATURES),
                         len(NUMERIC_FEATURES) + len(CATEGORICAL_FEATURES)))

clusters = kp_model.predict(X_kp, categorical=cat_idx_kp)
leads['cluster']          = clusters
leads['persona']          = leads['cluster'].map(PERSONA_MAP).fillna('Unknown')
leads['persona_priority'] = leads['persona'].map(PRIORITY_MAP).fillna('Unknown')

print(f"  ✓ Personas assigned:")
print(leads['persona'].value_counts().to_string())

# ══════════════════════════════════════════════════════════════════════════════
# STEP 7 — Financial Capability Index (FCI)
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 7 — Computing FCI")
print("=" * 60)

fci = leads[['lu_inc_model_v7_amt', 'RVAL_TOTL', 'fin_fla_networth']].copy()
fci['inc'] = pd.to_numeric(fci['lu_inc_model_v7_amt'], errors='coerce').fillna(0)
fci['rv']  = pd.to_numeric(fci['RVAL_TOTL'],           errors='coerce').fillna(0)
fci['nw']  = fci['fin_fla_networth'].map(NW_MAP).fillna(1)
for col in ['inc', 'rv']:
    fci[col] = fci[col].clip(upper=fci[col].quantile(0.99))

# FCI weights from V3.5 model run (income 42.6%, RV value 29.2%, net worth 28.3%)
w_inc, w_rv, w_nw = 0.426, 0.292, 0.283
leads['FCI_Corrected'] = (
    fci['inc'].apply(lambda v: (fci['inc'] <= v).mean() * 100) * w_inc +
    fci['rv'].apply( lambda v: (fci['rv']  <= v).mean() * 100) * w_rv  +
    fci['nw'].apply( lambda v: (fci['nw']  <= v).mean() * 100) * w_nw
).round(1)
leads['FCI_Tier'] = pd.cut(
    leads['FCI_Corrected'],
    bins=[-0.1, 25, 50, 75, 101],
    labels=['Tier 1 — Entry', 'Tier 2 — Emerging',
            'Tier 3 — Capable', 'Tier 4 — Premium']
)
print(f"  ✓ FCI computed")
print(leads['FCI_Tier'].value_counts().sort_index().to_string())

# ══════════════════════════════════════════════════════════════════════════════
# STEP 8 — Oliver Lead Classification + Financial Data Flag
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 8 — Oliver Lead Classification")
print("=" * 60)

# Financial data availability flag
fin_cols    = ['lu_inc_model_v7_amt', 'RVAL_TOTL', 'EQTY_AMNT_I1', 'fin_fla_networth']
fin_present = [c for c in fin_cols if c in leads.columns]
leads['Financial_Data_Available'] = leads[fin_present].notnull().any(axis=1)

def assign_oliver_class(row):
    p_new  = row['Prob_Buy_New']
    p_used = row['Prob_Buy_Used']
    p_no   = row['Prob_No_Buy']
    tier   = str(row.get('FCI_Tier', ''))
    fin    = bool(row.get('Financial_Data_Available', False))
    # Hot Lead — confirmed new buyer with verified financial data
    if p_new > p_used and p_new > p_no and fin:
        return 'Hot Lead'
    # Hot Lead — used-signal lead elevated by Tier 4 Premium financial capacity
    if p_used > 0.15 and 'Premium' in tier:
        return 'Hot Lead'
    # Warm Lead — used-signal with Tier 3 Capable or lower FCI
    if p_used > 0.15 and 'Capable' in tier:
        return 'Warm Lead'
    if p_used > 0.15 and ('Emerging' in tier or 'Entry' in tier):
        return 'Warm Lead'
    # Warm Lead — strong lifestyle signal but no financial data confirmed
    if p_new > p_used and p_new > p_no and not fin:
        return 'Warm Lead'
    # Cool Lead — insufficient signal, nurture only
    return 'Cool Lead'

leads['Lead_Class']       = leads.apply(assign_oliver_class, axis=1)
leads['Sales_Priority']   = leads['Lead_Class'].map(SALES_PRIORITY_MAP)
leads['Prospect_Segment'] = leads['Lead_Class'].map(PROSPECT_SEGMENT_MAP)

print(f"  ✓ Lead_Class assigned:")
print(leads['Lead_Class'].value_counts().to_string())
print(f"\n  Prospect_Segment:")
print(leads['Prospect_Segment'].value_counts().to_string())
print(f"\n  Financial_Data_Available:")
print(leads['Financial_Data_Available'].value_counts().to_string())

# ══════════════════════════════════════════════════════════════════════════════
# STEP 9 — Marketing Narratives
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 9 — Generating marketing narratives")
print("=" * 60)

def build_narrative(row):
    name       = str(row.get('First Name', 'Friend')).strip()
    cluster    = int(row.get('cluster', 0))
    fishing    = float(row.get('Act_Int_Fishing') or 50)
    outdoor    = float(row.get('Act_Int_Outdoor_Enthusiast') or 50)
    hunting    = float(row.get('Act_Int_Hunting_Enthusiasts') or 50)
    snow       = float(row.get('Act_Int_Snow_Sports') or 50)
    golf       = float(row.get('Act_Int_Play_Golf') or 50)
    wine       = float(row.get('Act_Int_Wine_Lovers') or 50)
    health     = float(row.get('Act_Int_Healthy_Living') or 50)
    travel     = str(row.get('Z_TRAVEL') or '')
    rv         = float(row.get('RVAL_TOTL') or 0)
    lead_class = str(row.get('Lead_Class', ''))
    fci        = int(row.get('FCI_Corrected') or 0)

    # Sales action based on Lead_Class
    if lead_class == 'Hot Lead':
        action = ("Rep call within 7 days. Lead with Oliver craftsmanship, "
                  "American-built quality, and lifetime structural warranty. "
                  "Invite to factory tour or owner rally.")
    elif lead_class == 'Warm Lead':
        action = (f"Rep call within 14 days. Frame the new Oliver as a long-term "
                  f"investment — resale value, durability, and total cost of ownership. "
                  f"FCI score of {fci} — introduce financing options if needed.")
    else:
        action = ("Add to long-form nurture sequence. Build brand relationship "
                  "and gather data. No direct sales rep time at this stage. "
                  "Revisit in 90 days or when engagement signals improve.")

    # Persona-specific opening
    if cluster == 2:
        hooks = [x for x, c in [('serious fishing', fishing > 55),
                                  ('backcountry access', outdoor > 45),
                                  ('upgrading RV', rv > 100000)] if c]
        opening = (f'{name} is a high-net-worth outdoor enthusiast with affinity '
                   f'for {hooks[0] if hooks else "the outdoors"}.')
    elif cluster == 3:
        opening = (f'{name} closely matches existing Oliver owners. '
                   f'May already know an owner — consider a referral prompt.')
    elif cluster == 4:
        hooks = [x for x, c in [('winter adventures', snow > 60),
                                  ('year-round pursuits', outdoor > 60),
                                  ('frequent travel', travel == 'Y')] if c]
        opening = (f'{name} is active and well-traveled with interest in '
                   f'{hooks[0] if hooks else "active lifestyle travel"}.')
    elif cluster == 5:
        hooks = [x for x, c in [('golf and outdoor', golf > 65),
                                  ('fishing', fishing > 65),
                                  ('hunting', hunting > 55)] if c]
        opening = (f'{name} is a sporting, outdoor-oriented prospect with passion '
                   f'for {hooks[0] if hooks else "outdoor sporting lifestyle"}.')
    elif cluster == 0:
        hooks = [x for x, c in [('healthy living', health > 60),
                                  ('comfort and leisure', wine > 55)] if c]
        opening = (f'{name} gravitates toward '
                   f'{hooks[0] if hooks else "comfort and lifestyle"} '
                   f'rather than rugged adventure.')
    elif cluster == 1:
        opening = (f'{name} has strong lifestyle interests but income below '
                   f'the typical Oliver buyer threshold.')
    else:
        opening = f'{name} is a prospect for Oliver Travel Trailers.'

    return f"{opening} {action}"

leads['Marketing_Narrative'] = leads.apply(build_narrative, axis=1)
print(f"  ✓ Narratives generated for {len(leads):,} leads")

# ══════════════════════════════════════════════════════════════════════════════
# STEP 10 — Zoho compliance formatting + save
# ══════════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}")
print("STEP 10 — Zoho compliance formatting + save")
print("=" * 60)

# Zoho requires whole numbers for score and FCI fields
leads['Buyer_Priority_Score'] = (leads['Buyer_Priority_Score'] * 100).round(0).astype(int)
leads['FCI_Corrected']        = leads['FCI_Corrected'].round(0).astype(int)

# Sort by score then FCI descending, assign rank
leads_out = leads.sort_values(
    ['Buyer_Priority_Score', 'FCI_Corrected'],
    ascending=[False, False]
).reset_index(drop=True)
leads_out['Sales_Rank'] = leads_out.index + 1

# Select and order output columns
OUTPUT_COLS = [
    'Id', 'Sales_Rank', 'First Name', 'Last Name', 'Email',
    'Prospect_Segment', 'Lead_Class', 'Sales_Priority', 'Buyer_Priority_Score',
    'Prob_Buy_New', 'Prob_Buy_Used', 'Prob_No_Buy',
    'Financial_Data_Available', 'FCI_Corrected', 'FCI_Tier',
    'persona', 'persona_priority', 'Marketing_Narrative',
]
OUTPUT_COLS = [c for c in OUTPUT_COLS if c in leads_out.columns]
final = leads_out[OUTPUT_COLS].copy()

# Final validation
print(f"  Shape: {final.shape} | Duplicates: {final.duplicated().sum()}")
print(f"\n  Lead_Class distribution:")
print(final['Lead_Class'].value_counts().to_string())
print(f"\n  Prospect_Segment distribution:")
print(final['Prospect_Segment'].value_counts().to_string())
print(f"\n  FCI Tier distribution:")
print(final['FCI_Tier'].value_counts().sort_index().to_string())

final.to_csv(OUTPUT_FILE, index=False)
print(f"\n  ✓ Saved → {OUTPUT_FILE}")

print(f"\n  Top 5 leads:")
preview = ['Sales_Rank', 'First Name', 'Last Name', 'Lead_Class',
           'Buyer_Priority_Score', 'FCI_Corrected', 'FCI_Tier', 'persona']
preview = [c for c in preview if c in final.columns]
print(final[preview].head(5).to_string(index=False))

print(f"\n{'=' * 60}")
print("SCORING COMPLETE")
print("=" * 60)