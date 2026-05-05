"""
generate_lead_report.py
=======================
Oliver Travel Trailers — Automated Lead Scoring Report Generator
Version: V1.0  |  April 2026

PURPOSE
-------
Generates a fully styled 3-page PDF report from any scored leads CSV file.
Run after score_new_leads.py to produce a client-ready report automatically.

USAGE
-----
    python generate_lead_report.py

    Or with arguments:
    python generate_lead_report.py --input Oliver_Leads_Scored_2026_05_01.csv
                                   --output Oliver_Lead_Report_2026_05_01.pdf
                                   --batch "May 1, 2026"
                                   --batch_num "Batch #1 of May"

REQUIREMENTS
------------
    pip install reportlab pandas

INPUT FILE
----------
The scored CSV must contain these columns (produced by score_new_leads.py):
    Id, First Name, Last Name, Email, Lead_Class, Prospect_Segment,
    Sales_Priority, Buyer_Priority_Score, FCI_Corrected, FCI_Tier,
    persona, persona_priority, Marketing_Narrative

OUTPUT
------
    Styled 3-page PDF with:
    - Header banner with batch stats
    - Analyst context note (score distribution commentary)
    - Priority lead cards (Hot and Warm leads)
    - Persona distribution bar chart
    - FCI donut chart
    - High FCI Cool Leads watch table
    - Month-to-date performance table (if prior_batches provided)
    - Numbered next steps
    - Active AI Advisors footer
"""

import argparse
import math
import os
import sys
from datetime import datetime, timedelta

import pandas as pd
from reportlab.lib.colors import HexColor, white
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (HRFlowable, Paragraph, SimpleDocTemplate,
                                Spacer, Table, TableStyle)
from reportlab.platypus.flowables import Flowable

# ── CONFIG — update these paths before running ────────────────────────────────
INPUT_FILE   = 'Oliver_Leads_Scored_2026_04_30.csv'   # ← scored CSV
OUTPUT_FILE  = 'Oliver_Lead_Report_2026_04_30.pdf'    # ← output PDF
BATCH_DATE   = 'April 30, 2026'                        # ← display date
BATCH_NUM    = 'Batch #5 of April'                     # ← batch label
CLIENT_NAME  = 'Oliver Travel Trailers'
PREPARED_BY  = 'Active AI Advisors'
WEBSITE      = 'activeaiadvisors.com'
MODEL_INFO   = 'LightGBM V5.5  |  AUC 0.94  |  Trained on ground-truth purchase records'

# Prior batches for MTD table — add/remove as needed
# Format: {'date': display, 'total': n, 'hot': n, 'warm': n, 'cool': n, 'match': pct}
PRIOR_BATCHES = [
    {'date':'Apr 2-14', 'total':329, 'hot':4, 'warm':2, 'cool':323, 'match':79.9},
    {'date':'Apr 21',   'total':129, 'hot':4, 'warm':1, 'cool':124, 'match':97.7},
    {'date':'Apr 28',   'total':172, 'hot':2, 'warm':3, 'cool':167, 'match':97.7},
    {'date':'Apr 29 ★', 'total':88,  'hot':6, 'warm':2, 'cool':80,  'match':98.4},
]

# ── Colors ────────────────────────────────────────────────────────────────────
FOREST = HexColor('#1A3C2B')
MID    = HexColor('#2D6A4F')
LIGHT  = HexColor('#52B788')
GOLD   = HexColor('#B5832A')
CREAM  = HexColor('#F8F4EE')
WARM   = HexColor('#FEF3E2')
LGRAY  = HexColor('#E5E7EB')
GRAY   = HexColor('#6B7280')
WHITE  = white

# ── Paragraph Styles ──────────────────────────────────────────────────────────
def S(name, **kw): return ParagraphStyle(name, **kw)
s_body     = S('body',  fontName='Helvetica',      fontSize=10, textColor=HexColor('#333333'), spaceAfter=4, leading=14)
s_bold     = S('bold',  fontName='Helvetica-Bold', fontSize=10, textColor=FOREST, spaceAfter=2, leading=14)
s_small    = S('small', fontName='Helvetica',      fontSize=8,  textColor=GRAY, spaceAfter=2, leading=11)
s_stat     = S('stat',  fontName='Times-Bold',     fontSize=30, textColor=FOREST, spaceAfter=0, leading=32, alignment=TA_CENTER)
s_stat_g   = S('stat_g',fontName='Times-Bold',     fontSize=30, textColor=GOLD,   spaceAfter=0, leading=32, alignment=TA_CENTER)
s_stat_m   = S('stat_m',fontName='Times-Bold',     fontSize=30, textColor=MID,    spaceAfter=0, leading=32, alignment=TA_CENTER)
s_stat_gr  = S('stat_gr',fontName='Times-Bold',    fontSize=30, textColor=GRAY,   spaceAfter=0, leading=32, alignment=TA_CENTER)
s_stat_lbl = S('stat_lbl',fontName='Helvetica-Bold',fontSize=7, textColor=GRAY,   spaceAfter=0, leading=9,  alignment=TA_CENTER)

# ── Utility: word wrap ────────────────────────────────────────────────────────
def wrap_text(canvas, text, font, size, max_width):
    words = text.split()
    lines, line = [], ''
    for w in words:
        test = line + (' ' if line else '') + w
        if canvas.stringWidth(test, font, size) < max_width:
            line = test
        else:
            if line: lines.append(line)
            line = w
    if line: lines.append(line)
    return lines

# ── Custom Flowables ──────────────────────────────────────────────────────────
class HeaderBanner(Flowable):
    def __init__(self, w, total, hot, warm, cool, batch_date, batch_num, client):
        self.w=w; self.h=110; self.total=total; self.hot=hot
        self.warm=warm; self.cool=cool
        self.batch_date=batch_date; self.batch_num=batch_num; self.client=client
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(FOREST)
        c.roundRect(0,0,self.w,self.h,4,fill=1,stroke=0)
        c.setFillColor(GOLD)
        c.rect(0,0,5,self.h,fill=1,stroke=0)
        c.setFillColor(GOLD); c.setFont('Helvetica-Bold',7)
        c.drawString(16, self.h-18, f'{PREPARED_BY.upper()} — CONFIDENTIAL')
        c.setFillColor(WHITE); c.setFont('Times-Bold',20)
        c.drawString(16, self.h-42, f'AI Lead Scoring Report  |  {self.batch_date}')
        c.setFillColor(HexColor('#AAAAAA')); c.setFont('Helvetica',8)
        c.drawString(16, self.h-56, f'{self.client}   |   {self.batch_num}   |   LightGBM · K-Prototypes · FCI')
        # Right: total
        c.setFillColor(WHITE); c.setFont('Times-Bold',28)
        c.drawRightString(self.w-16, self.h-44, str(self.total))
        c.setFillColor(GOLD); c.setFont('Helvetica',8)
        c.drawRightString(self.w-16, self.h-56, 'LEADS SCORED')
        c.setStrokeColor(HexColor('#FFFFFF')); c.setLineWidth(0.3)
        c.line(self.w-130, self.h-68, self.w-16, self.h-68)
        c.setFillColor(WHITE); c.setFont('Helvetica',8)
        for i, txt in enumerate([f'{self.hot} Hot Lead{"s" if self.hot!=1 else ""}',
                                  f'{self.warm} Warm Lead{"s" if self.warm!=1 else ""}',
                                  f'{self.cool} Cool Leads']):
            c.drawRightString(self.w-16, self.h-80-i*10, txt)

class SectionHeader(Flowable):
    def __init__(self, text, w):
        self.text=text; self.w=w; self.h=28
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(FOREST)
        c.rect(0,0,self.w,2,fill=1,stroke=0)
        c.setFont('Times-Bold',13)
        c.drawString(0, 8, self.text)

class ContextBox(Flowable):
    def __init__(self, text, w, title='ANALYST NOTE'):
        self.raw=text; self.w=w; self.title=title
        chars = int(w/5.5)
        lines = math.ceil(len(text)/chars)+3
        self.h = max(55, lines*13+22)
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(WARM)
        c.roundRect(0,0,self.w,self.h,3,fill=1,stroke=0)
        c.setFillColor(GOLD)
        c.rect(0,0,4,self.h,fill=1,stroke=0)
        c.setFillColor(HexColor('#5a4a2a'))
        if self.title:
            c.setFont('Helvetica-Bold',9)
            c.drawString(12, self.h-16, self.title+':')
            start_y = self.h-30
        else:
            start_y = self.h-14
        c.setFont('Helvetica',9)
        lines = wrap_text(c, self.raw, 'Helvetica', 9, self.w-22)
        y = start_y
        for ln in lines:
            c.drawString(12, y, ln)
            y -= 13

class LeadCard(Flowable):
    def __init__(self, name, badge, score, fci, tier, persona, narrative, w, hot=True):
        self.name=name; self.badge=badge; self.score=score; self.fci=fci
        self.tier=tier; self.persona=persona; self.narrative=narrative
        self.w=w; self.hot=hot; self.h=110
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        hdr_h=28
        c.setFillColor(CREAM)
        c.roundRect(0,0,self.w,self.h,3,fill=1,stroke=0)
        c.setFillColor(FOREST if self.hot else MID)
        c.roundRect(0,self.h-hdr_h,self.w,hdr_h,3,fill=1,stroke=0)
        c.rect(0,self.h-hdr_h,self.w,3,fill=1,stroke=0)
        c.setFillColor(WHITE); c.setFont('Times-Bold',13)
        c.drawString(12, self.h-20, self.name)
        badge_w = c.stringWidth(self.badge,'Helvetica-Bold',8)+16
        c.setFillColor(GOLD if self.hot else HexColor('#FFFFFF'))
        c.roundRect(self.w-badge_w-10,self.h-22,badge_w,16,2,fill=1,stroke=0)
        c.setFillColor(WHITE if self.hot else MID)
        c.setFont('Helvetica-Bold',8)
        c.drawString(self.w-badge_w-2, self.h-15, self.badge)
        y = self.h-44
        for lbl, val in [('Score:',str(self.score)),('FCI:',f'{self.fci} — {self.tier}'),('Persona:',self.persona)]:
            lw = c.stringWidth(lbl+' ','Helvetica',8)
            c.setFillColor(GRAY); c.setFont('Helvetica',8)
            c.drawString(12 if lbl=='Score:' else (12+185 if lbl=='FCI:' else 12+370), y, lbl)
            c.setFillColor(FOREST); c.setFont('Helvetica-Bold',8)
            c.drawString((12 if lbl=='Score:' else (12+185 if lbl=='FCI:' else 12+370))+lw, y, val)
        c.setFillColor(GOLD)
        c.rect(12,10,3,self.h-60,fill=1,stroke=0)
        c.setFillColor(HexColor('#444444')); c.setFont('Helvetica-Oblique',8.5)
        lines = wrap_text(c, self.narrative, 'Helvetica-Oblique', 8.5, self.w-36)
        y2 = self.h-60
        for ln in lines[:3]:
            c.drawString(20, y2, ln); y2-=12

class BarChart(Flowable):
    def __init__(self, w, h, data):
        self.w=w; self.h=h; self.data=data
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(FOREST); c.setFont('Helvetica-Bold',8)
        c.drawString(0, self.h-12, 'PERSONA DISTRIBUTION')
        if not self.data: return
        max_val = max(v for _,v,_ in self.data) or 1
        bar_h=16; gap=8; label_w=115
        chart_w = self.w-label_w-45
        y = self.h-28
        for label, val, color in self.data:
            c.setFillColor(GRAY); c.setFont('Helvetica',8)
            c.drawString(0, y+3, label[:24])
            c.setFillColor(LGRAY)
            c.roundRect(label_w,y,chart_w,bar_h,2,fill=1,stroke=0)
            fill_w = max(4, int(val/max_val*chart_w))
            c.setFillColor(color)
            c.roundRect(label_w,y,fill_w,bar_h,2,fill=1,stroke=0)
            c.setFillColor(WHITE); c.setFont('Helvetica-Bold',7.5)
            pct = val/64*100 if val else 0
            c.drawString(label_w+max(4,fill_w-32), y+5, f'{val} ({pct:.0f}%)')
            y -= (bar_h+gap)

class DonutChart(Flowable):
    def __init__(self, w, h, data, center_pct, center_label):
        self.w=w; self.h=h; self.data=data
        self.center_pct=center_pct; self.center_label=center_label
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(FOREST); c.setFont('Helvetica-Bold',8)
        c.drawString(0, self.h-12, 'FINANCIAL CAPABILITY INDEX')
        cx=62; cy=self.h-75; r_outer=48; r_inner=30
        start=90
        for _,_,pct,color in self.data:
            sweep = pct/100*360
            c.setFillColor(color)
            c.wedge(cx-r_outer,cy-r_outer,cx+r_outer,cy+r_outer,start,sweep,fill=1,stroke=0)
            start+=sweep
        c.setFillColor(WHITE)
        c.circle(cx,cy,r_inner,fill=1,stroke=0)
        c.setFillColor(FOREST); c.setFont('Times-Bold',14)
        c.drawCentredString(cx,cy+2,self.center_pct)
        c.setFillColor(GRAY); c.setFont('Helvetica',7)
        c.drawCentredString(cx,cy-10,self.center_label)
        lx=128; ly=self.h-40
        for label,count,pct,color in self.data:
            c.setFillColor(color)
            c.circle(lx,ly+4,5,fill=1,stroke=0)
            c.setFillColor(HexColor('#333333')); c.setFont('Helvetica',8.5)
            c.drawString(lx+9,ly,f'{label} — {count} ({pct:.0f}%)')
            ly-=18

class FooterBanner(Flowable):
    def __init__(self, w, prepared_by, website, batch_date):
        self.w=w; self.h=50
        self.prepared_by=prepared_by; self.website=website; self.batch_date=batch_date
    def wrap(self, aw, ah): return self.w, self.h
    def draw(self):
        c = self.canv
        c.setFillColor(FOREST)
        c.roundRect(0,0,self.w,self.h,3,fill=1,stroke=0)
        c.setFillColor(WHITE); c.setFont('Helvetica-Bold',10)
        c.drawString(16,28,self.prepared_by)
        c.setFillColor(HexColor('#AAAAAA')); c.setFont('Helvetica',8)
        c.drawString(16,14,'Grounded AI\u2122 \u2014 Disciplined Intelligence for Business')
        c.setFillColor(HexColor('#AAAAAA')); c.setFont('Helvetica',8)
        c.drawRightString(self.w-16,28,self.batch_date)
        c.setFillColor(GOLD); c.setFont('Helvetica',8)
        c.drawRightString(self.w-16,14,self.website)

# ── Main report builder ───────────────────────────────────────────────────────
def generate_report(input_file, output_file, batch_date, batch_num,
                    prior_batches=None, client_name=CLIENT_NAME):

    print(f"Reading scored file: {input_file}")
    df = pd.read_csv(input_file)
    total = len(df)

    # Classification counts
    hot_leads  = df[df['Lead_Class']=='Hot Lead']
    warm_leads = df[df['Lead_Class']=='Warm Lead']
    cool_leads = df[df['Lead_Class']=='Cool Lead']
    n_hot  = len(hot_leads)
    n_warm = len(warm_leads)
    n_cool = len(cool_leads)

    print(f"  {total} leads | {n_hot} Hot | {n_warm} Warm | {n_cool} Cool")

    # FCI tiers
    fci_counts = df['FCI_Tier'].value_counts()
    t4 = fci_counts.get('Tier 4 — Premium', 0)
    t3 = fci_counts.get('Tier 3 — Capable', 0)
    t2 = fci_counts.get('Tier 2 — Emerging', 0)
    t1 = fci_counts.get('Tier 1 — Entry', 0)
    tier3_plus = t4 + t3
    tier3_plus_pct = int(tier3_plus/total*100) if total else 0

    # Score context
    max_score = df['Buyer_Priority_Score'].max()
    score_context = ''
    if max_score < 30:
        score_context = (f'The maximum Buyer Priority Score this batch is {max_score}, '
            f'which is lower than recent batches. This reflects the persona mix in this '
            f'cohort — leads with longer conversion cycles. '
            f'Notably, {tier3_plus} leads ({tier3_plus_pct}%) carry FCI Tier 3 or Tier 4 '
            f'financial capacity and may be elevated by future CRM engagement signals.')
    else:
        score_context = (f'The maximum Buyer Priority Score this batch is {max_score}. '
            f'{tier3_plus} leads ({tier3_plus_pct}%) carry FCI Tier 3 or Tier 4 financial '
            f'capacity, representing the strongest pool for future conversion.')

    # Top cool leads by FCI
    top_cool = df[df['Lead_Class']=='Cool Lead'].nlargest(5,'FCI_Corrected')

    # Persona distribution
    persona_order = ['The Field & Fairway','The Aspirational Sophisticate',
                     'The Heritage Camper','The Wellness Wanderer',
                     'The Landed Outdoorsman','The Alpine Explorer']
    persona_colors_list = [MID, HexColor('#3A7D5E'), HexColor('#52B788'),
                           HexColor('#74C69D'), HexColor('#95D5B2'), HexColor('#B7E4C7')]
    pv = df['persona'].value_counts()
    persona_data = []
    for i, p in enumerate(persona_order):
        count = pv.get(p, 0)
        if count > 0:
            short = p.replace('The ','').replace(' Sophisticate','Soph.')
            persona_data.append((short, count, persona_colors_list[i % len(persona_colors_list)]))
    persona_data.sort(key=lambda x: x[1], reverse=True)

    # Donut data
    donut_data = [
        ('Tier 4 Premium', t4, t4/total*100 if total else 0, FOREST),
        ('Tier 3 Capable',  t3, t3/total*100 if total else 0, LIGHT),
        ('Tier 2 Emerging', t2, t2/total*100 if total else 0, GOLD),
        ('Tier 1 Entry',    t1, t1/total*100 if total else 0, LGRAY),
    ]

    # MTD totals
    all_batches = (prior_batches or []) + [{
        'date': batch_date.split(',')[0],
        'total': total, 'hot': n_hot, 'warm': n_warm, 'cool': n_cool, 'match': None
    }]
    mtd_total = sum(b['total'] for b in all_batches)
    mtd_hot   = sum(b['hot']   for b in all_batches)
    mtd_warm  = sum(b['warm']  for b in all_batches)
    mtd_cool  = sum(b['cool']  for b in all_batches)

    # Next steps — auto-generate from lead data
    next_steps = []
    for _, row in hot_leads.iterrows():
        days_out = (datetime.now() + timedelta(days=7)).strftime('%b %-d, %Y')
        next_steps.append(
            f"Assign {row['First Name']} {row['Last Name']} to a sales rep for contact "
            f"by {days_out}. Lead with craftsmanship and factory tour invitation. "
            f"FCI {int(row['FCI_Corrected'])} confirms strong financial capacity.")
    for _, row in warm_leads.iterrows():
        days_out = (datetime.now() + timedelta(days=14)).strftime('%b %-d, %Y')
        next_steps.append(
            f"Assign {row['First Name']} {row['Last Name']} for follow-up by {days_out}. "
            f"Open with financing conversation — FCI {int(row['FCI_Corrected'])} indicates "
            f"a financing pathway will be key.")
    if len(top_cool) > 0:
        next_steps.append(
            f"Add the {len(top_cool)} high-FCI Cool Leads to a 90-day monitoring list. "
            f"Re-score when new engagement data (plant tour, website activity) is available.")
    next_steps.append(
        f"Upload all {total} records to Zoho CRM using Id as the match key. "
        f"Fields: Lead_Class, Prospect_Segment, Score, FCI, Persona, Marketing Narrative.")
    if prior_batches:
        next_steps.append(
            f"Review prior batch Hot Leads — confirm rep contact has been made "
            f"and log outcomes in Zoho for model performance tracking.")

    # ── Build PDF ─────────────────────────────────────────────────────────────
    doc = SimpleDocTemplate(output_file, pagesize=letter,
        leftMargin=0.6*inch, rightMargin=0.6*inch,
        topMargin=0.5*inch, bottomMargin=0.5*inch)
    W = letter[0] - 1.2*inch
    story = []

    # Header
    story.append(HeaderBanner(W, total, n_hot, n_warm, n_cool,
                               batch_date, batch_num, client_name))
    story.append(Spacer(1,14))

    # Intro
    story.append(Paragraph('Dear Oliver Leadership Team,', s_body))
    story.append(Spacer(1,4))
    story.append(Paragraph(
        f'Please find below the AI lead scoring summary for the batch processed on '
        f'<b>{batch_date}</b>, along with contextual observations and a month-to-date '
        f'recap. All {total} records have been classified, scored, and are ready '
        f'for upload to Zoho CRM.', s_body))
    story.append(Spacer(1,14))
    story.append(HRFlowable(width=W, thickness=0.5, color=LGRAY))
    story.append(Spacer(1,10))

    # Stat boxes
    story.append(SectionHeader(f'{batch_date} Batch Summary', W))
    story.append(Spacer(1,8))
    stat_data = [
        [Paragraph(str(total),s_stat), Paragraph(str(n_hot),s_stat_g),
         Paragraph(str(n_warm),s_stat_m), Paragraph(str(n_cool),s_stat_gr)],
        [Paragraph('LEADS SCORED',s_stat_lbl), Paragraph('HOT LEAD'+('' if n_hot==1 else 'S'),s_stat_lbl),
         Paragraph('WARM LEAD'+('' if n_warm==1 else 'S'),s_stat_lbl), Paragraph('COOL LEADS',s_stat_lbl)],
    ]
    stat_t = Table(stat_data, colWidths=[W/4]*4)
    stat_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,-1),CREAM),
        ('LINEABOVE',(0,0),(0,1),3,FOREST), ('LINEABOVE',(1,0),(1,1),3,GOLD),
        ('LINEABOVE',(2,0),(2,1),3,MID),    ('LINEABOVE',(3,0),(3,1),3,GRAY),
        ('ALIGN',(0,0),(-1,-1),'CENTER'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),10), ('BOTTOMPADDING',(0,0),(-1,-1),10),
        ('GRID',(0,0),(-1,-1),0.5,LGRAY),
    ]))
    story.append(stat_t)
    story.append(Spacer(1,14))

    # Context
    story.append(ContextBox(score_context, W))
    story.append(Spacer(1,14))

    # Priority leads
    story.append(SectionHeader('Priority Leads — Action Required', W))
    story.append(Spacer(1,8))
    if len(hot_leads) == 0 and len(warm_leads) == 0:
        story.append(Paragraph(
            'No Hot or Warm Leads in this batch. All leads are classified as Cool Lead '
            '(Non-Customer) and have been added to the long-form nurture sequence.', s_body))
    else:
        for _, row in pd.concat([hot_leads, warm_leads]).iterrows():
            is_hot = row['Lead_Class'] == 'Hot Lead'
            story.append(LeadCard(
                name=f"{row['First Name']} {row['Last Name']}",
                badge='HOT LEAD' if is_hot else 'WARM LEAD',
                score=int(row['Buyer_Priority_Score']),
                fci=int(row['FCI_Corrected']),
                tier=str(row['FCI_Tier']).replace('Tier ','Tier '),
                persona=str(row['persona']),
                narrative=str(row['Marketing_Narrative'])[:220],
                w=W, hot=is_hot))
            story.append(Spacer(1,8))
    story.append(Spacer(1,6))

    # Charts
    story.append(SectionHeader('Batch Analytics', W))
    story.append(Spacer(1,8))
    chart_table = Table(
        [[BarChart(W*0.54, 140, persona_data),
          DonutChart(W*0.44, 140, donut_data,
                     f'{tier3_plus_pct}%', 'Tier 3+')]],
        colWidths=[W*0.54, W*0.46])
    chart_table.setStyle(TableStyle([
        ('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),0), ('RIGHTPADDING',(0,0),(-1,-1),0),
        ('TOPPADDING',(0,0),(-1,-1),0),  ('BOTTOMPADDING',(0,0),(-1,-1),0),
    ]))
    story.append(chart_table)
    story.append(Spacer(1,14))

    # High FCI Cool Leads
    story.append(SectionHeader('Cool Leads — High FCI to Watch', W))
    story.append(Spacer(1,6))
    story.append(ContextBox(
        f'These {len(top_cool)} leads carry strong financial capacity but did not reach '
        f'the scoring threshold for active outreach. Recommend adding to a 90-day '
        f'monitoring list and re-scoring after the next CRM data refresh.', W, title=''))
    story.append(Spacer(1,8))
    if len(top_cool) > 0:
        watch_data = [['NAME','SCORE','FCI','TIER','PERSONA']]
        for _, row in top_cool.iterrows():
            watch_data.append([
                f"{row['First Name']} {row['Last Name']}",
                str(int(row['Buyer_Priority_Score'])),
                str(int(row['FCI_Corrected'])),
                str(row['FCI_Tier']),
                str(row['persona'])
            ])
        wt = Table(watch_data, colWidths=[W*0.25,W*0.1,W*0.1,W*0.22,W*0.33])
        wt.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(-1,0),FOREST), ('TEXTCOLOR',(0,0),(-1,0),WHITE),
            ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,0),7.5),
            ('FONTNAME',(0,1),(-1,-1),'Helvetica'), ('FONTSIZE',(0,1),(-1,-1),9),
            ('TEXTCOLOR',(0,1),(-1,-1),HexColor('#333333')),
            ('ROWBACKGROUNDS',(0,1),(-1,-1),[WHITE,CREAM]),
            ('GRID',(0,0),(-1,-1),0.5,LGRAY),
            ('ALIGN',(1,0),(-1,-1),'CENTER'), ('ALIGN',(0,0),(0,-1),'LEFT'),
            ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8),
        ]))
        story.append(wt)
    story.append(Spacer(1,14))

    # MTD table
    story.append(SectionHeader('Month-to-Date Performance', W))
    story.append(Spacer(1,8))
    mtd_data = [['BATCH','LEADS','HOT','WARM','COOL','MATCH RATE *']]
    for b in all_batches:
        mtd_data.append([
            b['date'], str(b['total']), str(b['hot']),
            str(b['warm']), str(b['cool']),
            f"{b['match']:.1f}%" if b.get('match') else '—'
        ])
    mtd_data.append(['TOTAL', str(mtd_total), str(mtd_hot),
                     str(mtd_warm), str(mtd_cool), '—'])
    mtd_t = Table(mtd_data, colWidths=[W*0.22,W*0.12,W*0.1,W*0.1,W*0.12,W*0.18])
    mtd_t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),FOREST), ('TEXTCOLOR',(0,0),(-1,0),WHITE),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'), ('FONTSIZE',(0,0),(-1,0),7.5),
        ('FONTNAME',(0,1),(-1,-2),'Helvetica'), ('FONTSIZE',(0,1),(-1,-2),9),
        ('TEXTCOLOR',(0,1),(-1,-2),HexColor('#333333')),
        ('ROWBACKGROUNDS',(0,1),(-1,-2),[WHITE,CREAM]),
        ('BACKGROUND',(0,-1),(-1,-1),HexColor('#EEF7F2')),
        ('FONTNAME',(0,-1),(-1,-1),'Helvetica-Bold'), ('TEXTCOLOR',(0,-1),(-1,-1),FOREST),
        ('GRID',(0,0),(-1,-1),0.5,LGRAY),
        ('ALIGN',(1,0),(-1,-1),'CENTER'), ('ALIGN',(0,0),(0,-1),'LEFT'),
        ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
        ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7),
        ('LEFTPADDING',(0,0),(-1,-1),8), ('RIGHTPADDING',(0,0),(-1,-1),8),
        ('TEXTCOLOR',(2,1),(2,-1),GOLD), ('FONTNAME',(2,1),(2,-1),'Helvetica-Bold'),
        ('TEXTCOLOR',(3,1),(3,-1),MID),  ('FONTNAME',(3,1),(3,-1),'Helvetica-Bold'),
    ]))
    story.append(mtd_t)
    story.append(Spacer(1,6))
    story.append(Paragraph(
        '* Match Rate = percentage of leads successfully enriched by Aspire with '
        'demographic, financial, and lifestyle data. Unmatched records are scored '
        'using median imputation and typically classify as Cool Lead.',
        ParagraphStyle('footnote', fontName='Helvetica-Oblique', fontSize=8,
                       textColor=GRAY, leading=11)))
    story.append(Spacer(1,14))

    # Next steps
    story.append(SectionHeader('Next Steps', W))
    story.append(Spacer(1,8))
    for i, step in enumerate(next_steps, 1):
        step_t = Table([[
            Paragraph(f'<b>{i}</b>', ParagraphStyle('sn',fontName='Helvetica-Bold',
                fontSize=9,textColor=WHITE,alignment=TA_CENTER,leading=11)),
            Paragraph(step, s_body)
        ]], colWidths=[22, W-30])
        step_t.setStyle(TableStyle([
            ('BACKGROUND',(0,0),(0,0),FOREST), ('BACKGROUND',(1,0),(1,0),WHITE),
            ('ALIGN',(0,0),(0,0),'CENTER'), ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ('TOPPADDING',(0,0),(-1,-1),7), ('BOTTOMPADDING',(0,0),(-1,-1),7),
            ('LEFTPADDING',(0,0),(0,0),4),  ('RIGHTPADDING',(0,0),(0,0),4),
            ('LEFTPADDING',(1,0),(1,0),10),
            ('LINEBELOW',(0,0),(-1,-1),0.5,LGRAY),
        ]))
        story.append(step_t)

    story.append(Spacer(1,8))
    story.append(Paragraph(
        f'The complete scored file is available in Zoho CRM or upon request. {MODEL_INFO}.',
        ParagraphStyle('disc',fontName='Helvetica',fontSize=8,textColor=GRAY,leading=11)))
    story.append(Spacer(1,14))
    story.append(FooterBanner(W, PREPARED_BY, WEBSITE, batch_date))

    doc.build(story)
    size = os.path.getsize(output_file)
    print(f"  Report saved → {output_file}  ({size:,} bytes)")
    return output_file


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate Oliver lead scoring PDF report')
    parser.add_argument('--input',     default=INPUT_FILE,  help='Scored CSV file')
    parser.add_argument('--output',    default=OUTPUT_FILE, help='Output PDF path')
    parser.add_argument('--batch',     default=BATCH_DATE,  help='Batch date display string')
    parser.add_argument('--batch_num', default=BATCH_NUM,   help='Batch number label')
    args = parser.parse_args()

    generate_report(
        input_file   = args.input,
        output_file  = args.output,
        batch_date   = args.batch,
        batch_num    = args.batch_num,
        prior_batches= PRIOR_BATCHES,
        client_name  = CLIENT_NAME,
    )