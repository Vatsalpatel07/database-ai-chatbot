# Phase 13 Step 3: SQL Server to PostgreSQL Data & Schema Validation Report

- **Validation Date**: 2026-10-01 10:30:46
- **Source Database**: Microsoft SQL Server (`mnghealthreportingdb.dbo`)
- **Target Database**: PostgreSQL 18.6 (`mnghealthreportingdb.dbo`)
- **Overall Status**: **PASSED — 100% DATA & SCHEMA MATCH**
- **Total Tables Validated**: 67
- **Total Authoritative Rows**: 27,233

## 1. Table-by-Table Validation Summary Matrix

| # | Table Name | SQL Server Rows | PostgreSQL Rows | Row Count Match | PK Uniqueness | Column Checks | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 01 | `SchemaVersions` | 150 | 150 | MATCH | PASSED | PASSED | **PASS** |
| 02 | `chatbot_conversation` | 58 | 58 | MATCH | PASSED | PASSED | **PASS** |
| 03 | `portal_hcp_resource_registration` | 600 | 600 | MATCH | N/A | PASSED | **PASS** |
| 04 | `rep_portal_invites` | 550 | 550 | MATCH | N/A | PASSED | **PASS** |
| 05 | `site_commd_activity_discussion` | 700 | 700 | MATCH | N/A | PASSED | **PASS** |
| 06 | `site_commd_activity_document_collaboration` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 07 | `site_commd_activity_pulse_survey` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 08 | `site_commd_activity_pulse_survey_form` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 09 | `site_commd_activity_pulse_survey_form_list` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 10 | `site_commd_module_activity` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 11 | `site_commd_resources` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 12 | `site_commd_user_resource_views` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 13 | `site_commd_user_setup_audit` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 14 | `site_commd_workspace` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 15 | `site_commd_workspace_event_resources` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 16 | `site_commd_workspace_modules` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 17 | `site_commd_workspace_resources` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 18 | `site_commd_workspace_team` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 19 | `site_detail_template` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 20 | `site_details` | 600 | 600 | MATCH | PASSED | PASSED | **PASS** |
| 21 | `site_details_activity_report` | 500 | 500 | MATCH | PASSED | PASSED | **PASS** |
| 22 | `site_details_internal_affiliates` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 23 | `site_event_formats` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 24 | `site_event_leads` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 25 | `site_event_registrant_custom_questions` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 26 | `site_event_registrants` | 600 | 600 | MATCH | N/A | PASSED | **PASS** |
| 27 | `site_event_registrants_analytics_report` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 28 | `site_event_registrants_audit` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 29 | `site_event_registrants_standardized_fields` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 30 | `site_event_setup` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 31 | `site_event_speakers` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 32 | `site_event_staff` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 33 | `site_event_telecom` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 34 | `site_event_topics` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 35 | `site_event_venue_details` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 36 | `site_events` | 600 | 600 | MATCH | N/A | PASSED | **PASS** |
| 37 | `site_events_account_activity` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 38 | `site_events_country_block` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 39 | `site_media_content` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 40 | `site_media_content_account_activity` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 41 | `site_module_resource` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 42 | `site_project_codes` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 43 | `site_speaker_affiliations` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 44 | `site_speaker_approved_topics` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 45 | `site_speaker_certifications` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 46 | `site_speaker_degrees` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 47 | `site_speaker_specialties` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 48 | `site_speakers` | 550 | 550 | MATCH | N/A | PASSED | **PASS** |
| 49 | `site_tags` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 50 | `site_team_members` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 51 | `site_topic_details_specialities` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 52 | `site_topic_details_therapeutic_area` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 53 | `site_topics` | 550 | 550 | MATCH | N/A | PASSED | **PASS** |
| 54 | `site_view_only_registation_audit` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 55 | `sitecore_campaign_details` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 56 | `table_group` | 24 | 24 | MATCH | N/A | PASSED | **PASS** |
| 57 | `table_load_settings` | 1 | 1 | MATCH | PASSED | PASSED | **PASS** |
| 58 | `user_account_content_shares` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 59 | `user_account_event_email_invites` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 60 | `user_account_event_requests` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 61 | `user_account_logins` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 62 | `user_account_pdf_invite_downloads` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 63 | `user_account_session_audit` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 64 | `user_accounts` | 550 | 550 | MATCH | N/A | PASSED | **PASS** |
| 65 | `user_accounts_activity_report` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 66 | `visitor_session` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |
| 67 | `visitor_session_analytics_report` | 400 | 400 | MATCH | N/A | PASSED | **PASS** |

## 2. Identity Sequence Validation Matrix

| Table Name | Identity Column | Attached Sequence | Table MAX(ID) | Sequence Last Value | Valid |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SchemaVersions` | `Id` | `dbo."SchemaVersions_Id_seq"` | 150 | 150 | VALID |
| `chatbot_conversation` | `id` | `dbo.chatbot_conversation_id_seq` | 20024 | 20024 | VALID |
| `site_details` | `id` | `dbo.site_details_id_seq` | 601 | 601 | VALID |
| `site_event_venue_details` | `id` | `dbo.site_event_venue_details_id_seq` | 400 | 400 | VALID |
| `table_group` | `id` | `dbo.table_group_id_seq` | 24 | 24 | VALID |
| `table_load_settings` | `id` | `dbo.table_load_settings_id_seq` | 1 | 1 | VALID |
| `user_accounts` | `id` | `dbo.user_accounts_id_seq` | 550 | 550 | VALID |
| `visitor_session` | `id` | `dbo.visitor_session_id_seq` | 400 | 400 | VALID |

## 3. Structural Guarantees & Invariance Verification

- **Row Fidelity**: Exactly 27,233 rows present in SQL Server source; exactly 27,233 rows migrated into PostgreSQL target.
- **Zero Skipped Rows**: No filters, truncations, or dropping of records occurred.
- **Type Parity**: All 838 columns map losslessly (UUIDs, datetimes, booleans, bounded strings, text, binaries, integers).
- **Null Fidelity**: NULL counts across all 838 columns match between source and target 100%.
- **Foreign Keys Rule**: SQL Server has 0 declared foreign keys. Target PostgreSQL database has 0 foreign keys.
- **SQL Server Integrity**: SQL Server database was accessed read-only; no tables, rows, or schemas were altered.
- **Application Code / Config Isolation**: Zero modifications to application source (`app/`), `.env`, or active runtime.