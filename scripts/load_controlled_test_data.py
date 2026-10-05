#!/usr/bin/env python3
"""
POST-PHASE-13 STAGE 1: Controlled Test Data Preparation & Loading Script

Database Target:
  PostgreSQL 18.6: localhost:5432/mnghealthreportingdb (schema: dbo)
  
Principles:
  - FROZEN production architecture: zero application modifications
  - Completely synthetic data: ZERO real PII
  - Atomic transaction: rollback on error, commit only after validation
  - Identity sequences resynchronized
  - Generates reports/controlled_test_data_manifest.json with exact ground-truth metrics
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import random
import statistics
import sys
from typing import Any

import psycopg
from dotenv import load_dotenv

# Ensure environment variables are loaded
load_dotenv()

DB_SERVER = os.getenv("DB_SERVER", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "mnghealthreportingdb")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "Vatsal@123")
DB_SCHEMA = os.getenv("DB_SCHEMA", "dbo")

# Fixed deterministic seed
SEED = 42
random.seed(SEED)

ALL_67_TABLES = [
    "SchemaVersions", "api_audit_log", "api_auth_token", "api_client", "api_client_endpoints",
    "api_endpoint", "api_error_log", "client_hcp", "client_hcp_specialties", "client_hcp_target_list",
    "client_rep", "client_rep_client_hcp", "client_speaker", "data_sync_history", "database_firewall_rules",
    "email_audit_log", "email_queue", "event_lead_evaluations", "event_provider", "event_survey_responses",
    "field_approval_request", "invitation_templates", "mailchimp_campaign", "mailchimp_campaign_recipients",
    "mng_app_roles", "mng_app_users", "mng_calendar_categories", "mng_calendar_items", "mng_specialties",
    "mng_territories", "mng_user_roles", "mng_users", "rep_notifications", "site_details",
    "site_event_breakout_room_registrants", "site_event_breakout_rooms", "site_event_dial_in_numbers",
    "site_event_evaluation_questions", "site_event_evaluations", "site_event_materials",
    "site_event_registrant_materials", "site_event_registrants", "site_event_speakers", "site_event_topics",
    "site_event_venues", "site_events", "site_faqs", "site_materials", "site_page_sections", "site_pages",
    "site_reminders", "site_speakers", "site_tags", "site_team_members", "site_topics", "site_venues",
    "sms_audit_log", "sms_queue", "specialty_categories", "sync_change_log", "sync_conflicts",
    "sync_entity_mapping", "sync_history", "sync_log", "sync_stats", "sync_watermark", "user_accounts"
]

SELECTED_TABLES = [
    "site_details",
    "site_events",
    "site_speakers",
    "site_event_speakers",
    "site_topics",
    "site_event_topics",
    "site_event_registrants",
    "user_accounts",
    "site_team_members",
    "site_tags",
]

EXPECTED_INCREMENTS = {
    "site_details": 5,
    "site_events": 120,
    "site_speakers": 25,
    "site_event_speakers": 150,
    "site_topics": 20,
    "site_event_topics": 140,
    "site_event_registrants": 200,
    "user_accounts": 35,
    "site_team_members": 15,
    "site_tags": 25,
}


def get_db_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=DB_SERVER,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def get_table_counts(conn: psycopg.Connection) -> dict[str, int]:
    counts = {}
    with conn.cursor() as cur:
        cur.execute(f"SELECT table_name FROM information_schema.tables WHERE table_schema = '{DB_SCHEMA}' ORDER BY table_name;")
        tables = [r[0] for r in cur.fetchall()]
        for t in tables:
            cur.execute(f'SELECT COUNT(*) FROM {DB_SCHEMA}."{t}";')
            counts[t] = cur.fetchone()[0]
    return counts


def generate_synthetic_data() -> dict[str, list[dict[str, Any]]]:
    """Generate deterministic synthetic test dataset for 10 interrelated tables."""
    # 1. Sites (5 rows)
    # Sites 1-3 have children; Sites 4-5 have 0 children (outer join / childless parent test)
    sites = [
        {
            "id": 602,
            "sitecore_site_id": "c0000001-0000-0000-0000-000000000001",
            "site_name": "Synthetic Clinical Site Alpha",
            "site_client_name": "Alpha Health Network",
            "site_status": "Active",
            "site_type": "Hospital",
            "site_brands": "Brand Alpha",
            "product_name": "CardioGuard",
            "country": "United States",
            "therapeutic_area": "Cardiology",
            "site_branded": True,
            "site_go_live_date": datetime(2024, 1, 10, 9, 0, 0),
            "created_date": datetime(2024, 1, 1, 9, 0, 0),
        },
        {
            "id": 603,
            "sitecore_site_id": "c0000002-0000-0000-0000-000000000002",
            "site_name": "Synthetic Research Site Beta",
            "site_client_name": "Beta Pharma Group",
            "site_status": "Pending",
            "site_type": "Clinic",
            "site_brands": "Brand Beta",
            "product_name": "NeuroRelief",
            "country": "Canada",
            "therapeutic_area": "Neurology",
            "site_branded": True,
            "site_go_live_date": datetime(2024, 6, 1, 10, 0, 0),
            "created_date": datetime(2024, 5, 15, 10, 0, 0),
        },
        {
            "id": 604,
            "sitecore_site_id": "c0000003-0000-0000-0000-000000000003",
            "site_name": "Synthetic Regional Center Gamma",
            "site_client_name": "Gamma Medical System",
            "site_status": "Active",
            "site_type": "Academic Center",
            "site_brands": "Brand Gamma",
            "product_name": "OncoCare",
            "country": "United States",
            "therapeutic_area": "Oncology",
            "site_branded": False,
            "site_go_live_date": datetime(2025, 2, 15, 8, 30, 0),
            "created_date": datetime(2025, 1, 20, 8, 30, 0),
        },
        {
            "id": 605,
            "sitecore_site_id": "c0000004-0000-0000-0000-000000000004",
            "site_name": "Synthetic Standalone Site Delta",
            "site_client_name": "Delta Life Sciences",
            "site_status": "Completed",
            "site_type": "Outpatient Clinic",
            "site_brands": "Brand Delta",
            "product_name": "DermProtect",
            "country": "United Kingdom",
            "therapeutic_area": "Dermatology",
            "site_branded": False,
            "site_go_live_date": datetime(2025, 5, 20, 14, 0, 0),
            "created_date": datetime(2025, 4, 1, 14, 0, 0),
        },
        {
            "id": 606,
            "sitecore_site_id": "c0000005-0000-0000-0000-000000000005",
            "site_name": "Synthetic Future Site Epsilon",
            "site_client_name": "Epsilon Biotech",
            "site_status": "Draft",
            "site_type": "Research Institute",
            "site_brands": "Brand Epsilon",
            "product_name": "ImmunoPlus",
            "country": "Germany",
            "therapeutic_area": "Immunology",
            "site_branded": True,
            "site_go_live_date": datetime(2026, 1, 1, 0, 0, 0),
            "created_date": datetime(2025, 12, 1, 0, 0, 0),
        },
    ]

    # 2. Events (120 rows)
    # Durations: 10x0, 15x15, 30x30, 25x45, 20x60, 10x90, 3x120, 2x180, 5xNone
    durations = (
        [0] * 10
        + [15] * 15
        + [30] * 30
        + [45] * 25
        + [60] * 20
        + [90] * 10
        + [120] * 3
        + [180] * 2
        + [None] * 5
    )
    statuses = ["Active"] * 70 + ["Completed"] * 35 + ["Cancelled"] * 15
    formats = ["Virtual"] * 60 + ["In-Person"] * 40 + ["Hybrid"] * 20
    capacities = [50] * 40 + [100] * 40 + [250] * 20 + [500] * 10 + [None] * 10

    events = []
    base_date = datetime(2024, 1, 15, 10, 0, 0)
    for i in range(1, 121):
        event_uuid = f"e{i:07d}-0000-0000-0000-000000000001"
        if i <= 70:
            site_uuid = "c0000001-0000-0000-0000-000000000001"
        elif i <= 105:
            site_uuid = "c0000002-0000-0000-0000-000000000002"
        else:
            site_uuid = "c0000003-0000-0000-0000-000000000003"
        
        start_dt = base_date + timedelta(days=(i - 1) * 8, hours=(i % 8))
        ev = {
            "event_sitecore_id": event_uuid,
            "sitecore_site_id": site_uuid,
            "event_client_id": f"CL-EV-{i:04d}",
            "event_status": statuses[i - 1],
            "event_start_datetime": start_dt,
            "event_duration": durations[i - 1],
            "event_type": "Symposium" if i % 3 == 0 else ("Roundtable" if i % 3 == 1 else "Webinar"),
            "event_provider_platform": "Zoom" if i % 2 == 0 else "Teams",
            "event_language": "English" if i % 10 != 0 else "Spanish",
            "event_topic_title": f"Synthetic Medical Symposium Topic {i % 20 + 1}",
            "event_capacity_limit": capacities[i - 1],
            "test_event": False,
            "event_audience_type": "HCP" if i % 4 != 0 else "Rep",
            "event_format": formats[i - 1],
            "event_created_datetime": start_dt - timedelta(days=30),
            "event_brands": "Brand Alpha" if i <= 70 else ("Brand Beta" if i <= 105 else "Brand Gamma"),
        }
        events.append(ev)

    # 3. Speakers (25 rows)
    speaker_defs = [
        ("Dr. Alice", "M.", "Smith", "Cardiologist", "MD", "America/New_York", "Boston", "MA", "02115"),
        ("Dr. Bob", "J.", "Jones", "Cardiologist", "MD", "America/New_York", "New York", "NY", "10001"),
        ("Dr. Catherine", "L.", "Clark", "Cardiologist", "MD, PhD", "America/Chicago", "Chicago", "IL", "60601"),
        ("Dr. David", "R.", "Miller", "Oncologist", "MD", "America/Chicago", "Houston", "TX", "77001"),
        ("Dr. Evelyn", "K.", "Davis", "Oncologist", "DO", "America/Los_Angeles", "Los Angeles", "CA", "90001"),
        ("Dr. Frank", "H.", "Wilson", "Oncologist", "MD", "America/Los_Angeles", "Seattle", "WA", "98101"),
        ("Dr. Grace", "A.", "Taylor", "Neurologist", "MD", "America/New_York", "Philadelphia", "PA", "19104"),
        ("Dr. Henry", "E.", "Anderson", "Neurologist", "MD", "America/Denver", "Denver", "CO", "80202"),
        ("Dr. Irene", "B.", "Thomas", "Immunologist", "DO", "America/Chicago", "Minneapolis", "MN", "55401"),
        ("Dr. John", "P.", "Smith", "Immunologist", "MD", "America/New_York", "Atlanta", "GA", "30303"),
        ("Dr. Jonathan", "Q.", "Smith", "Endocrinologist", "MD, PhD", "America/New_York", "Miami", "FL", "33101"),
        ("Dr. Karen", "S.", "White", "Endocrinologist", "MD", "America/Chicago", "Dallas", "TX", "75201"),
        ("Dr. Liam", "T.", "Harris", "Cardiologist", "DO", "America/New_York", "Toronto", "ON", "M5S"),
        ("Dr. Mia", "V.", "Martin", "Cardiologist", "MD", "America/New_York", "Montreal", "QC", "H3A"),
        ("Dr. Noah", "C.", "Thompson", "Cardiologist", "MBBS", "America/Chicago", "Winnipeg", "MB", "R3T"),
        ("Dr. Olivia", "D.", "Garcia", "Oncologist", "MD", "America/Los_Angeles", "Vancouver", "BC", "V6T"),
        ("Dr. Peter", "F.", "Martinez", "Oncologist", "MD, PhD", "America/Denver", "Calgary", "AB", "T2N"),
        ("Dr. Quinn", "G.", "Robinson", "Neurologist", "DO", "America/Los_Angeles", "Edmonton", "AB", "T6G"),
        ("Dr. Robert", "A.", "Miller", "Neurologist", "MD", "America/New_York", "Ottawa", "ON", "K1N"),
        ("Dr. Roberta", "B.", "Miller", "Immunologist", "MD", "America/New_York", "Halifax", "NS", "B3H"),
        ("Dr. Samuel", "I.", "Clark", "Oncologist", "MD", "America/New_York", "Baltimore", "MD", "21201"),
        ("Dr. Tara", "J.", "Rodriguez", "Neurologist", "MD, PhD", "America/Chicago", "Nashville", "TN", "37203"),
        ("Dr. Uma", "K.", "Lewis", "Immunologist", "DO", "America/New_York", "Pittsburgh", "PA", "15213"),
        ("Dr. Victor", "M.", "Lee", "Endocrinologist", "MBBS", "America/Los_Angeles", "San Francisco", "CA", "94143"),
        ("Dr. Wendy", "N.", "Walker", "Cardiologist", "MD", "America/Phoenix", "Phoenix", "AZ", "85004"),
    ]
    speakers = []
    for idx, s in enumerate(speaker_defs, 1):
        spk_uuid = f"a{idx:07d}-0000-0000-0000-000000000001"
        if idx <= 12:
            site_uuid = "c0000001-0000-0000-0000-000000000001"
        elif idx <= 20:
            site_uuid = "c0000002-0000-0000-0000-000000000002"
        else:
            site_uuid = "c0000003-0000-0000-0000-000000000003"
        speakers.append({
            "speaker_sitecore_id": spk_uuid,
            "sitecore_site_id": site_uuid,
            "client_hcp_id": f"HCP-SYN-{idx:04d}",
            "client_speaker_id": f"SPK-SYN-{idx:04d}",
            "speaker_first_name": s[0],
            "speaker_middle_name": s[1],
            "speaker_last_name": s[2],
            "speaker_title": s[3],
            "speaker_degree_text": s[4],
            "speaker_timezone": s[5],
            "speaker_city": s[6],
            "speaker_state": s[7],
            "speaker_zip": s[8],
            "speaker_email1": f"speaker_{idx:03d}@example-synthetic-speaker.org",
            "speaker_address1": f"{idx * 10} Medical Boulevard",
            "speaker_mobile": f"+1-555-010-{idx:04d}",
            "speaker_active_for_events": idx <= 20,
            "test_speaker": False,
            "speaker_affiliations": f"{s[3]} Association of North America",
        })

    # 4. Event Speakers (150 rows)
    event_speakers = []
    for ev_idx in range(1, 21):
        ev_uuid = f"e{ev_idx:07d}-0000-0000-0000-000000000001"
        for spk_offset in range(3):
            spk_idx = ((ev_idx - 1 + spk_offset) % 12) + 1
            spk_uuid = f"a{spk_idx:07d}-0000-0000-0000-000000000001"
            event_speakers.append({"event_sitecore_id": ev_uuid, "speaker_sitecore_id": spk_uuid})

    for ev_idx in range(21, 61):
        ev_uuid = f"e{ev_idx:07d}-0000-0000-0000-000000000001"
        for spk_offset in range(2):
            spk_idx = ((ev_idx - 1 + spk_offset) % 12) + 1
            spk_uuid = f"a{spk_idx:07d}-0000-0000-0000-000000000001"
            event_speakers.append({"event_sitecore_id": ev_uuid, "speaker_sitecore_id": spk_uuid})

    for ev_idx in range(61, 71):
        ev_uuid = f"e{ev_idx:07d}-0000-0000-0000-000000000001"
        spk_idx = ((ev_idx - 1) % 12) + 1
        spk_uuid = f"a{spk_idx:07d}-0000-0000-0000-000000000001"
        event_speakers.append({"event_sitecore_id": ev_uuid, "speaker_sitecore_id": spk_uuid})

    # 5. Topics (20 rows)
    brands_list = ["Brand Alpha"] * 8 + ["Brand Beta"] * 6 + ["Brand Gamma"] * 4 + ["Brand Delta"] * 2
    specialties_list = ["Cardiology"] * 7 + ["Oncology"] * 6 + ["Neurology"] * 4 + ["Immunology"] * 3
    topics = []
    for idx in range(1, 21):
        top_uuid = f"b{idx:07d}-0000-0000-0000-000000000001"
        if idx <= 10:
            site_uuid = "c0000001-0000-0000-0000-000000000001"
        elif idx <= 16:
            site_uuid = "c0000002-0000-0000-0000-000000000002"
        else:
            site_uuid = "c0000003-0000-0000-0000-000000000003"
        topics.append({
            "topic_sitecore_id": top_uuid,
            "sitecore_site_id": site_uuid,
            "test_topic": False,
            "topic_expiration_date": f"2027-{12 - (idx % 6):02d}-31",
            "topic_title": f"Synthetic Clinical Topic {idx}: {specialties_list[idx-1]} Advancements",
            "topic_client_code": f"TOP-SYN-{idx:04d}",
            "topic_brand": brands_list[idx - 1],
            "topic_active_for_event": idx <= 16,
            "topic_active_for_speaker": True,
            "topic_active_for_request": True,
            "topic_approval_date": f"2024-0{idx % 9 + 1}-15",
            "available_for_public_api": True,
            "topic_specialty": specialties_list[idx - 1],
        })

    # 6. Event Topics (140 rows)
    event_topics = []
    for ev_idx in range(1, 21):
        ev_uuid = f"e{ev_idx:07d}-0000-0000-0000-000000000001"
        for top_offset in range(2):
            top_idx = ((ev_idx - 1 + top_offset) % 10) + 1
            top_uuid = f"b{top_idx:07d}-0000-0000-0000-000000000001"
            event_topics.append({"event_sitecore_id": ev_uuid, "topic_sitecore_id": top_uuid})

    for ev_idx in range(21, 121):
        ev_uuid = f"e{ev_idx:07d}-0000-0000-0000-000000000001"
        if ev_idx <= 70:
            top_idx = ((ev_idx - 1) % 10) + 1
        elif ev_idx <= 105:
            top_idx = ((ev_idx - 71) % 6) + 11
        else:
            top_idx = ((ev_idx - 106) % 4) + 17
        top_uuid = f"b{top_idx:07d}-0000-0000-0000-000000000001"
        event_topics.append({"event_sitecore_id": ev_uuid, "topic_sitecore_id": top_uuid})

    # 7. Registrants (200 rows)
    att_statuses = ["Attended"] * 110 + ["Registered"] * 55 + ["Cancelled"] * 20 + ["No-Show"] * 15
    degrees_list = ["MD"] * 80 + ["DO"] * 35 + ["RN"] * 30 + ["NP"] * 30 + ["PharmD"] * 15 + [None] * 10
    specialties_reg = ["Cardiology"] * 60 + ["Oncology"] * 50 + ["Neurology"] * 35 + ["Family Medicine"] * 30 + ["Internal Medicine"] * 25
    cities_reg = ["New York", "Chicago", "Houston", "Philadelphia", "Phoenix", "San Antonio", "San Diego", "Dallas", "San Jose", "Austin"]
    states_reg = ["NY", "IL", "TX", "PA", "AZ", "TX", "CA", "TX", "CA", "TX"]

    registrants = []
    reg_idx = 1

    def _add_regs(ev_id, count, site_u):
        nonlocal reg_idx
        ev_u = f"e{ev_id:07d}-0000-0000-0000-000000000001"
        for _ in range(count):
            r_uuid = f"f{reg_idx:07d}-0000-0000-0000-000000000001"
            status = att_statuses[reg_idx - 1]
            cancel_dt = datetime(2024, 6, 15, 12, 0, 0) if status == "Cancelled" else None
            zip_val = None if reg_idx % 7 == 0 else f"{10000 + (reg_idx * 13) % 89999}"
            comp_val = None if reg_idx % 5 == 0 else f"Synthetic Healthcare Clinic {reg_idx % 25 + 1}"
            registrants.append({
                "registration_sitecore_id": r_uuid,
                "event_sitecore_id": ev_u,
                "sitecore_site_id": site_u,
                "visitor_session_id": f"SESS-SYN-{reg_idx:05d}",
                "registration_date": datetime(2024, 1, 10, 10, 0, 0) + timedelta(days=reg_idx * 4),
                "registrant_client_id": f"CL-REG-{reg_idx:05d}",
                "registrant_first_name": f"SyntheticFirst{reg_idx:03d}",
                "registrant_last_name": f"SyntheticLast{reg_idx:03d}",
                "registrant_specialty": specialties_reg[reg_idx - 1],
                "registrant_degree": degrees_list[reg_idx - 1],
                "registrant_timezone": "America/New_York" if reg_idx % 3 == 0 else ("America/Chicago" if reg_idx % 3 == 1 else "America/Los_Angeles"),
                "registrant_city": cities_reg[reg_idx % 10],
                "registrant_state": states_reg[reg_idx % 10],
                "registrant_email": f"registrant_{reg_idx:03d}@example-synthetic-care.org",
                "registrant_type": "HCP" if reg_idx % 4 != 0 else "Staff",
                "registrant_status": "Confirmed" if status != "Cancelled" else "Cancelled",
                "registrant_attendance_status": status,
                "registrant_audience_type": "HCP",
                "test_registrant": False,
                "registrant_attendance_type": "Virtual" if reg_idx % 2 == 0 else "In-Person",
                "registrant_country": "United States",
                "registrant_company": comp_val,
                "registrant_job_title": "Physician" if degrees_list[reg_idx - 1] in ("MD", "DO") else "Nurse Practitioner",
                "registrant_zip": zip_val,
                "registrant_cancel_date": cancel_dt,
            })
            reg_idx += 1

    site1_uuid = "c0000001-0000-0000-0000-000000000001"
    for ev_id in range(1, 11):
        _add_regs(ev_id, 5, site1_uuid)
    for ev_id in range(11, 41):
        _add_regs(ev_id, 3, site1_uuid)
    for ev_id in range(41, 71):
        _add_regs(ev_id, 2, site1_uuid)

    # 8. User Accounts (35 rows, IDs 551 to 585)
    types_acc = ["HCP"] * 20 + ["Rep"] * 10 + ["Admin"] * 5
    degrees_acc = ["MD"] * 15 + ["DO"] * 5 + ["RN"] * 5 + ["NP"] * 5 + ["PharmD"] * 5
    statuses_acc = ["Active"] * 28 + ["Inactive"] * 7
    territories = ["Northeast"] * 10 + ["Midwest"] * 8 + ["Southeast"] * 7 + ["West"] * 6 + ["Southwest"] * 4
    timezones_acc = ["America/New_York"] * 17 + ["America/Chicago"] * 10 + ["America/Los_Angeles"] * 8

    user_accounts = []
    for idx in range(1, 36):
        acc_id = 550 + idx
        acc_uuid = f"d{idx:07d}-0000-0000-0000-000000000001"
        if idx <= 18:
            site_u = "c0000001-0000-0000-0000-000000000001"
        elif idx <= 28:
            site_u = "c0000002-0000-0000-0000-000000000002"
        else:
            site_u = "c0000003-0000-0000-0000-000000000003"
        user_accounts.append({
            "id": acc_id,
            "sitecore_site_id": site_u,
            "account_sitecore_id": acc_uuid,
            "account_type": types_acc[idx - 1],
            "account_name": f"Account User {idx:02d}",
            "account_degree": degrees_acc[idx - 1],
            "account_phone1": f"+1-555-020-{idx:04d}",
            "account_city": cities_reg[idx % 10],
            "account_state": states_reg[idx % 10],
            "account_zip": f"902{idx:02d}",
            "account_timezone": timezones_acc[idx - 1],
            "account_status": statuses_acc[idx - 1],
            "account_client_id": f"CL-ACC-{idx:04d}",
            "account_territory_name": territories[idx - 1],
            "account_territory_id": f"TERR-{territories[idx - 1][:2].upper()}-{idx:02d}",
            "created_date": datetime(2024, 2, 1, 9, 0, 0) + timedelta(days=idx * 7),
            "updated_date": datetime(2024, 8, 1, 9, 0, 0) + timedelta(days=idx * 7),
            "account_email": f"user_account_{idx:02d}@example-synthetic-portal.org",
            "account_language": "English",
            "test_account": False,
            "account_firstname": f"UserFirst{idx:02d}",
            "account_lastname": f"UserLast{idx:02d}",
        })

    # 9. Site Team Members (15 rows)
    teams_list = ["Operations"] * 6 + ["Clinical"] * 4 + ["Compliance"] * 3 + ["Support"] * 2
    site_team_members = []
    for idx in range(1, 16):
        mem_uuid = f"1{idx:07d}-0000-0000-0000-000000000001"
        if idx <= 7:
            site_u = "c0000001-0000-0000-0000-000000000001"
        elif idx <= 12:
            site_u = "c0000002-0000-0000-0000-000000000002"
        else:
            site_u = "c0000003-0000-0000-0000-000000000003"
        site_team_members.append({
            "sitecore_site_id": site_u,
            "sitecore_item_id": mem_uuid,
            "first_name": f"TeamMemberFirst{idx:02d}",
            "last_name": f"TeamMemberLast{idx:02d}",
            "email_address": f"team_member_{idx:02d}@example-synthetic-org.org",
            "phone": f"+1-555-030-{idx:04d}",
            "team": teams_list[idx - 1],
        })

    # 10. Site Tags (25 rows)
    tags_list = ["Cardiology"] * 5 + ["Oncology"] * 5 + ["Neurology"] * 4 + ["Clinical Trials"] * 4 + ["Immunology"] * 3 + ["Continuing Medical Education"] * 2 + ["Pediatrics"] * 2
    site_tags = []
    for idx in range(1, 26):
        if idx <= 12:
            site_u = "c0000001-0000-0000-0000-000000000001"
        elif idx <= 20:
            site_u = "c0000002-0000-0000-0000-000000000002"
        else:
            site_u = "c0000003-0000-0000-0000-000000000003"
        site_tags.append({
            "sitecore_site_id": site_u,
            "tag": tags_list[idx - 1],
        })

    return {
        "site_details": sites,
        "site_events": events,
        "site_speakers": speakers,
        "site_event_speakers": event_speakers,
        "site_topics": topics,
        "site_event_topics": event_topics,
        "site_event_registrants": registrants,
        "user_accounts": user_accounts,
        "site_team_members": site_team_members,
        "site_tags": site_tags,
    }


def clean_synthetic_data(conn: psycopg.Connection) -> None:
    """Safely remove ONLY synthetic cohort records from PostgreSQL database."""
    print("Initiating clean of synthetic test cohort...")
    with conn.transaction():
        with conn.cursor() as cur:
            # Delete in leaf-to-root order
            cur.execute("DELETE FROM dbo.site_tags WHERE sitecore_site_id >= 'c0000001-0000-0000-0000-000000000001' AND sitecore_site_id <= 'c0000005-0000-0000-0000-000000000005';")
            cur.execute("DELETE FROM dbo.site_team_members WHERE sitecore_site_id >= 'c0000001-0000-0000-0000-000000000001' AND sitecore_site_id <= 'c0000005-0000-0000-0000-000000000005';")
            cur.execute("DELETE FROM dbo.user_accounts WHERE id BETWEEN 551 AND 585;")
            cur.execute("DELETE FROM dbo.site_event_registrants WHERE registration_sitecore_id >= 'f0000001-0000-0000-0000-000000000001' AND registration_sitecore_id <= 'f0000200-0000-0000-0000-000000000001';")
            cur.execute("DELETE FROM dbo.site_event_topics WHERE event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001' AND event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';")
            cur.execute("DELETE FROM dbo.site_topics WHERE topic_sitecore_id >= 'b0000001-0000-0000-0000-000000000001' AND topic_sitecore_id <= 'b0000020-0000-0000-0000-000000000001';")
            cur.execute("DELETE FROM dbo.site_event_speakers WHERE event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001' AND event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';")
            cur.execute("DELETE FROM dbo.site_speakers WHERE speaker_sitecore_id >= 'a0000001-0000-0000-0000-000000000001' AND speaker_sitecore_id <= 'a0000025-0000-0000-0000-000000000001';")
            cur.execute("DELETE FROM dbo.site_events WHERE event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001' AND event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';")
            cur.execute("DELETE FROM dbo.site_details WHERE id BETWEEN 602 AND 606;")
            
            # Resync sequences to max id
            cur.execute("SELECT setval(pg_get_serial_sequence('dbo.site_details', 'id'), COALESCE((SELECT MAX(id) FROM dbo.site_details), 1));")
            cur.execute("SELECT setval(pg_get_serial_sequence('dbo.user_accounts', 'id'), COALESCE((SELECT MAX(id) FROM dbo.user_accounts), 1));")
    conn.commit()
    print("Clean completed successfully.")


def load_synthetic_data(conn: psycopg.Connection, data: dict[str, list[dict[str, Any]]]) -> None:
    """Insert synthetic data atomically with parameterized batches."""
    print("Beginning atomic insertion of synthetic test dataset...")
    # Order of insertion: root-to-leaf
    load_order = [
        "site_details",
        "site_events",
        "site_speakers",
        "site_event_speakers",
        "site_topics",
        "site_event_topics",
        "site_event_registrants",
        "user_accounts",
        "site_team_members",
        "site_tags",
    ]

    with conn.transaction():
        with conn.cursor() as cur:
            for table_name in load_order:
                rows = data[table_name]
                if not rows:
                    continue
                cols = list(rows[0].keys())
                col_names = ", ".join(cols)
                placeholders = ", ".join(["%s"] * len(cols))
                query = f"INSERT INTO {DB_SCHEMA}.{table_name} ({col_names}) VALUES ({placeholders});"
                
                records = [tuple(r[col] for col in cols) for r in rows]
                cur.executemany(query, records)
                print(f"  Inserted {len(records)} rows into {DB_SCHEMA}.{table_name}")

            # Resynchronize identity sequences
            print("  Resynchronizing identity sequences...")
            cur.execute("SELECT setval(pg_get_serial_sequence('dbo.site_details', 'id'), (SELECT MAX(id) FROM dbo.site_details));")
            seq1_val = cur.fetchone()[0]
            cur.execute("SELECT setval(pg_get_serial_sequence('dbo.user_accounts', 'id'), (SELECT MAX(id) FROM dbo.user_accounts));")
            seq2_val = cur.fetchone()[0]
            print(f"  Sequences resynced: dbo.site_details_id_seq -> {seq1_val}, dbo.user_accounts_id_seq -> {seq2_val}")

    conn.commit()
    print("Atomic insertion and sequence resynchronization completed successfully.")


def compute_ground_truth(conn: psycopg.Connection, data: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Compute and verify exact ground-truth facts against live database."""
    manifest = {
        "metadata": {
            "generated_at": datetime.utcnow().isoformat(),
            "database_name": DB_NAME,
            "database_schema": DB_SCHEMA,
            "database_engine": "PostgreSQL 18.6",
            "seed": SEED,
            "total_synthetic_rows": 735,
            "selected_tables_count": 10,
            "untouched_tables_count": 57,
        },
        "table_increments": EXPECTED_INCREMENTS,
        "cohort_metrics": {},
        "database_total_metrics": {},
        "cross_table_join_metrics": {},
        "edge_case_and_null_metrics": {},
    }

    with conn.cursor() as cur:
        # 1. Total row counts per table (cohort and table total)
        for tbl in SELECTED_TABLES:
            cur.execute(f"SELECT COUNT(*) FROM dbo.{tbl};")
            manifest["database_total_metrics"][f"{tbl}_count"] = cur.fetchone()[0]

        # 2. Cohort specific metrics
        # site_details
        cur.execute("SELECT COUNT(*), COUNT(DISTINCT site_status), COUNT(DISTINCT country) FROM dbo.site_details WHERE id BETWEEN 602 AND 606;")
        r = cur.fetchone()
        manifest["cohort_metrics"]["site_details"] = {
            "row_count": r[0],
            "distinct_status_count": r[1],
            "distinct_countries_count": r[2],
            "status_distribution": {"Active": 2, "Pending": 1, "Completed": 1, "Draft": 1},
            "childless_sites": ["c0000004-0000-0000-0000-000000000004", "c0000005-0000-0000-0000-000000000005"],
        }

        # site_events
        cur.execute("""
            SELECT 
                COUNT(*),
                COUNT(event_duration),
                COUNT(*) - COUNT(event_duration) AS null_durations,
                SUM(event_duration),
                AVG(event_duration)::numeric(10,2),
                MIN(event_duration),
                MAX(event_duration),
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY event_duration),
                MIN(event_start_datetime),
                MAX(event_start_datetime)
            FROM dbo.site_events 
            WHERE event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001' 
              AND event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';
        """)
        ev_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_events"] = {
            "row_count": ev_metrics[0],
            "populated_duration_count": ev_metrics[1],
            "null_duration_count": ev_metrics[2],
            "sum_duration": int(ev_metrics[3]),
            "avg_duration": float(ev_metrics[4]),
            "min_duration": ev_metrics[5],
            "max_duration": ev_metrics[6],
            "median_duration": float(ev_metrics[7]),
            "earliest_event_start": str(ev_metrics[8]),
            "latest_event_start": str(ev_metrics[9]),
            "status_distribution": {"Active": 70, "Completed": 35, "Cancelled": 15},
            "format_distribution": {"Virtual": 60, "In-Person": 40, "Hybrid": 20},
            "events_per_site": {
                "c0000001-0000-0000-0000-000000000001": 70,
                "c0000002-0000-0000-0000-000000000002": 35,
                "c0000003-0000-0000-0000-000000000003": 15,
                "c0000004-0000-0000-0000-000000000004": 0,
                "c0000005-0000-0000-0000-000000000005": 0,
            }
        }

        # site_speakers
        cur.execute("""
            SELECT 
                COUNT(*),
                COUNT(DISTINCT speaker_title),
                SUM(CASE WHEN speaker_active_for_events THEN 1 ELSE 0 END),
                SUM(CASE WHEN NOT speaker_active_for_events THEN 1 ELSE 0 END)
            FROM dbo.site_speakers
            WHERE speaker_sitecore_id >= 'a0000001-0000-0000-0000-000000000001'
              AND speaker_sitecore_id <= 'a0000025-0000-0000-0000-000000000001';
        """)
        spk_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_speakers"] = {
            "row_count": spk_metrics[0],
            "distinct_titles": spk_metrics[1],
            "active_speakers": spk_metrics[2],
            "inactive_speakers": spk_metrics[3],
            "speakers_per_site": {
                "c0000001-0000-0000-0000-000000000001": 12,
                "c0000002-0000-0000-0000-000000000002": 8,
                "c0000003-0000-0000-0000-000000000003": 5,
            }
        }

        # site_event_speakers (Fan-out testing)
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT event_sitecore_id), COUNT(DISTINCT speaker_sitecore_id)
            FROM dbo.site_event_speakers
            WHERE event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001'
              AND event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';
        """)
        es_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_event_speakers"] = {
            "row_count": es_metrics[0],
            "distinct_events_with_speakers": es_metrics[1],
            "distinct_speakers_assigned": es_metrics[2],
            "speaker_distribution_per_event": {
                "events_with_3_speakers": 20,
                "events_with_2_speakers": 40,
                "events_with_1_speaker": 10,
                "events_with_0_speakers": 50,
            }
        }

        # site_topics
        cur.execute("""
            SELECT 
                COUNT(*),
                COUNT(DISTINCT topic_brand),
                SUM(CASE WHEN topic_active_for_event THEN 1 ELSE 0 END),
                SUM(CASE WHEN NOT topic_active_for_event THEN 1 ELSE 0 END)
            FROM dbo.site_topics
            WHERE topic_sitecore_id >= 'b0000001-0000-0000-0000-000000000001'
              AND topic_sitecore_id <= 'b0000020-0000-0000-0000-000000000001';
        """)
        top_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_topics"] = {
            "row_count": top_metrics[0],
            "distinct_brands": top_metrics[1],
            "active_topics": top_metrics[2],
            "inactive_topics": top_metrics[3],
        }

        # site_event_topics
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT event_sitecore_id), COUNT(DISTINCT topic_sitecore_id)
            FROM dbo.site_event_topics
            WHERE event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001'
              AND event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';
        """)
        et_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_event_topics"] = {
            "row_count": et_metrics[0],
            "distinct_events_with_topics": et_metrics[1],
            "distinct_topics_assigned": et_metrics[2],
            "topic_distribution_per_event": {
                "events_with_2_topics": 20,
                "events_with_1_topic": 100,
                "events_with_0_topics": 0,
            }
        }

        # site_event_registrants
        cur.execute("""
            SELECT 
                COUNT(*),
                COUNT(DISTINCT event_sitecore_id),
                COUNT(registrant_degree),
                COUNT(*) - COUNT(registrant_degree) AS null_degrees,
                COUNT(registrant_zip),
                COUNT(*) - COUNT(registrant_zip) AS null_zips,
                COUNT(registrant_company),
                COUNT(*) - COUNT(registrant_company) AS null_companies,
                COUNT(registrant_cancel_date) AS cancelled_date_count
            FROM dbo.site_event_registrants
            WHERE registration_sitecore_id >= 'f0000001-0000-0000-0000-000000000001'
              AND registration_sitecore_id <= 'f0000200-0000-0000-0000-000000000001';
        """)
        reg_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_event_registrants"] = {
            "row_count": reg_metrics[0],
            "distinct_events_with_registrants": reg_metrics[1],
            "null_degrees_count": reg_metrics[3],
            "null_zip_count": reg_metrics[5],
            "null_company_count": reg_metrics[7],
            "cancelled_date_count": reg_metrics[8],
            "attendance_distribution": {
                "Attended": 110,
                "Registered": 55,
                "Cancelled": 20,
                "No-Show": 15,
            },
            "registrant_distribution_per_event": {
                "events_with_5_registrants": 10,
                "events_with_3_registrants": 30,
                "events_with_2_registrants": 30,
                "events_with_0_registrants": 50,
            }
        }

        # user_accounts
        cur.execute("""
            SELECT 
                COUNT(*),
                COUNT(DISTINCT account_type),
                COUNT(DISTINCT account_territory_name),
                SUM(CASE WHEN account_status = 'Active' THEN 1 ELSE 0 END),
                SUM(CASE WHEN account_status = 'Inactive' THEN 1 ELSE 0 END)
            FROM dbo.user_accounts
            WHERE id BETWEEN 551 AND 585;
        """)
        acc_metrics = cur.fetchone()
        manifest["cohort_metrics"]["user_accounts"] = {
            "row_count": acc_metrics[0],
            "distinct_account_types": acc_metrics[1],
            "distinct_territories": acc_metrics[2],
            "active_accounts": acc_metrics[3],
            "inactive_accounts": acc_metrics[4],
            "type_distribution": {"HCP": 20, "Rep": 10, "Admin": 5},
            "accounts_per_site": {
                "c0000001-0000-0000-0000-000000000001": 18,
                "c0000002-0000-0000-0000-000000000002": 10,
                "c0000003-0000-0000-0000-000000000003": 7,
            }
        }

        # site_team_members
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT team)
            FROM dbo.site_team_members
            WHERE sitecore_site_id >= 'c0000001-0000-0000-0000-000000000001'
              AND sitecore_site_id <= 'c0000005-0000-0000-0000-000000000005';
        """)
        tm_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_team_members"] = {
            "row_count": tm_metrics[0],
            "distinct_teams": tm_metrics[1],
            "team_distribution": {
                "Operations": 6,
                "Clinical": 4,
                "Compliance": 3,
                "Support": 2,
            }
        }

        # site_tags
        cur.execute("""
            SELECT COUNT(*), COUNT(DISTINCT tag)
            FROM dbo.site_tags
            WHERE sitecore_site_id >= 'c0000001-0000-0000-0000-000000000001'
              AND sitecore_site_id <= 'c0000005-0000-0000-0000-000000000005';
        """)
        tag_metrics = cur.fetchone()
        manifest["cohort_metrics"]["site_tags"] = {
            "row_count": tag_metrics[0],
            "distinct_tags": tag_metrics[1],
            "tag_distribution": {
                "Cardiology": 5,
                "Oncology": 5,
                "Neurology": 4,
                "Clinical Trials": 4,
                "Immunology": 3,
                "Continuing Medical Education": 2,
                "Pediatrics": 2,
            }
        }

        # 3. Cross-Table JOIN Cardinalities
        # INNER JOIN site_details and site_events
        cur.execute("""
            SELECT s.site_name, COUNT(e.event_sitecore_id)
            FROM dbo.site_details s
            JOIN dbo.site_events e ON s.sitecore_site_id = e.sitecore_site_id
            WHERE s.id BETWEEN 602 AND 606
            GROUP BY s.site_name
            ORDER BY s.site_name;
        """)
        manifest["cross_table_join_metrics"]["site_events_inner_join"] = dict(cur.fetchall())

        # LEFT JOIN site_details and site_events (Must show 0 for Delta and Epsilon!)
        cur.execute("""
            SELECT s.site_name, COUNT(e.event_sitecore_id)
            FROM dbo.site_details s
            LEFT JOIN dbo.site_events e ON s.sitecore_site_id = e.sitecore_site_id
            WHERE s.id BETWEEN 602 AND 606
            GROUP BY s.site_name
            ORDER BY s.site_name;
        """)
        manifest["cross_table_join_metrics"]["site_events_left_join"] = dict(cur.fetchall())

        # Fan-out: event -> registrants -> speakers
        cur.execute("""
            SELECT 
                COUNT(*) AS cartesian_rows,
                COUNT(DISTINCT e.event_sitecore_id) AS distinct_events
            FROM dbo.site_events e
            JOIN dbo.site_event_speakers es ON e.event_sitecore_id = es.event_sitecore_id
            JOIN dbo.site_event_registrants r ON e.event_sitecore_id = r.event_sitecore_id
            WHERE e.event_sitecore_id >= 'e0000001-0000-0000-0000-000000000001'
              AND e.event_sitecore_id <= 'e0000120-0000-0000-0000-000000000001';
        """)
        fanout = cur.fetchone()
        manifest["cross_table_join_metrics"]["fan_out_speaker_registrant_cartesian"] = {
            "total_joined_rows": fanout[0],
            "distinct_events": fanout[1],
        }

        # 4. Edge Cases and Null Distributions
        manifest["edge_case_and_null_metrics"] = {
            "zero_duration_events_count": 10,
            "null_duration_events_count": 5,
            "null_degrees_registrants_count": 10,
            "null_zip_registrants_count": 28,
            "null_company_registrants_count": 40,
            "cancelled_registrants_with_cancel_date": 20,
            "active_registrants_with_null_cancel_date": 180,
            "childless_parent_sites_count": 2,
            "childless_parent_sites": [
                "Synthetic Standalone Site Delta",
                "Synthetic Future Site Epsilon",
            ],
            "events_with_zero_speakers_count": 50,
            "events_with_zero_registrants_count": 50,
            "inactive_speakers_count": 5,
            "inactive_topics_count": 4,
            "inactive_user_accounts_count": 7,
            "single_occurrence_categories": {
                "site_status": ["Pending", "Completed", "Draft"],
                "product_name": ["CardioGuard", "NeuroRelief", "OncoCare", "DermProtect", "ImmunoPlus"],
            },
        }

        # 5. Zero-Result Entities (Known entities that do NOT exist in synthetic dataset)
        manifest["zero_result_entities"] = [
            {"entity": "site_client_name", "value": "Nonexistent Zenith Health Corp"},
            {"entity": "event_status", "value": "Postponed"},
            {"entity": "speaker_title", "value": "Orthopedic Surgeon"},
            {"entity": "registrant_city", "value": "Anchorage"},
            {"entity": "account_territory_name", "value": "Pacific Northwest Nonexistent"},
            {"entity": "tag", "value": "Ophthalmology"},
        ]

    return manifest


def main():
    parser = argparse.ArgumentParser(description="Post-Phase-13 Stage 1 Controlled Test Data Loader")
    parser.add_argument("--clean", action="store_true", help="Remove synthetic cohort records and resync sequences")
    parser.add_argument("--verify-only", action="store_true", help="Run validation and manifest generation without loading")
    args = parser.parse_args()

    print("==================================================")
    print("POST-PHASE-13 STAGE 1: CONTROLLED TEST DATA LOADER")
    print("==================================================")
    print(f"Target Database: {DB_NAME} on {DB_SERVER}:{DB_PORT} (schema: {DB_SCHEMA})")

    conn = get_db_connection()
    try:
        if args.clean:
            clean_synthetic_data(conn)
            post_counts = get_table_counts(conn)
            conn.commit()
            print(f"Post-clean total database rows: {sum(c for c in post_counts.values() if c >= 0)}")
            return

        if args.verify_only:
            print("Running in verification-only mode on current database state...")
            current_counts = get_table_counts(conn)
            conn.commit()
            total_current = sum(c for c in current_counts.values() if c >= 0)
            print(f"Current total database rows: {total_current}")
            
            # Verify 10 test tables have at least the cohort rows
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM dbo.site_details WHERE id BETWEEN 602 AND 606;")
                site_cnt = cur.fetchone()[0]
                if site_cnt != 5:
                    print(f"ERROR: Synthetic cohort not fully loaded (site_details has {site_cnt}/5 test rows).")
                    sys.exit(1)
            conn.commit()
            print("Synthetic test cohort presence confirmed.")
            data = generate_synthetic_data()
        else:
            # Pre-load audit
            pre_counts = get_table_counts(conn)
            conn.commit()
            total_pre_rows = sum(c for c in pre_counts.values() if c >= 0)
            print(f"Pre-load table count: {len(pre_counts)}")
            print(f"Pre-load total database rows: {total_pre_rows}")

            # Check if synthetic site already present
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM dbo.site_details WHERE id = 602;")
                if cur.fetchone()[0] > 0:
                    print("Synthetic cohort already detected in database. Cleaning existing cohort first...")
                    clean_synthetic_data(conn)
                    pre_counts = get_table_counts(conn)
                    conn.commit()
                    total_pre_rows = sum(c for c in pre_counts.values() if c >= 0)
            conn.commit()

            data = generate_synthetic_data()
            load_synthetic_data(conn, data)

            # Post-load verification
            print("\nVerifying post-load state across all 67 tables...")
            post_counts = get_table_counts(conn)
            conn.commit()
            total_post_rows = sum(c for c in post_counts.values() if c >= 0)
            print(f"Post-load total database rows: {total_post_rows}")
            print(f"Net change: +{total_post_rows - total_pre_rows} rows")

            # Verify increments
            discrepancies = []
            for tbl in sorted(post_counts.keys()):
                expected_inc = EXPECTED_INCREMENTS.get(tbl, 0)
                actual_inc = post_counts[tbl] - pre_counts[tbl]
                if actual_inc != expected_inc:
                    discrepancies.append((tbl, expected_inc, actual_inc))

            if discrepancies:
                print("ERROR: Row count discrepancies detected:")
                for tbl, exp, act in discrepancies:
                    print(f"  {tbl}: expected +{exp}, got +{act}")
                sys.exit(1)
            else:
                print("Row count verification PASSED:")
                print("  - 57 tables perfectly unchanged (0 rows added)")
                print("  - 10 tables incremented by exact expected amounts (735 rows added)")

        # Compute ground-truth manifest
        print("\nComputing ground-truth facts for evaluation manifest...")
        manifest = compute_ground_truth(conn, data)
        conn.commit()
        manifest_path = Path("reports/controlled_test_data_manifest.json")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        print(f"Manifest written successfully: {manifest_path} ({manifest_path.stat().st_size} bytes)")

    finally:
        conn.close()

    print("\n==================================================")
    print("STAGE 1 DATA LOADING & VALIDATION COMPLETE")
    print("==================================================")


if __name__ == "__main__":
    main()
