# Phase 13 Step 3: SQL Server to PostgreSQL Migration Report

- **Migration Execution Date**: 2026-10-01T10:30:21.978381
- **Source Server / Database**: Microsoft SQL Server (`localhost` / `mnghealthreportingdb.dbo`)
- **Target Server / Database**: PostgreSQL 18.6 (`localhost:5432` / `mnghealthreportingdb.dbo`)
- **Total Tables Migrated**: 67
- **Total Authoritative Rows Migrated**: 27,233
- **Migration Execution Duration**: 2.13 seconds
- **Migration Status**: **COMPLETE & 100% VERIFIED**

## 1. Executive Summary

Phase 13 Step 3 executed the schema alignment and complete data migration from Microsoft SQL Server to PostgreSQL 18.6 for the `mnghealthreportingdb` database. In accordance with strict phase boundaries:

- All 67 production tables in the `dbo` schema were migrated without a single row filtered or dropped.
- All 27,233 rows were transferred losslessly using parameterized bulk batches (`executemany`) via psycopg 3.
- All 8 identity columns were synchronized using `setval` to ensure future sequence generation starts at `MAX(id) + 1`.
- SQL Server source database was accessed in strictly read-only mode and remains unaltered.
- Application code (`app/*`) and configuration (`.env`) remain untouched; SQL Server remains the active database for the chatbot.
- Zero foreign keys were created in PostgreSQL, matching the source SQL Server catalog (0 declared FKs).
- No vector embeddings or pipelines were executed in this step.

## 2. Table-by-Table Migration Ledger

| # | Table Name | Source Rows (SQL Server) | Target Rows (PostgreSQL) | Migration Status |
| :--- | :--- | :--- | :--- | :--- |
| 01 | `SchemaVersions` | 150 | 150 | **SUCCESS** |
| 02 | `chatbot_conversation` | 58 | 58 | **SUCCESS** |
| 03 | `portal_hcp_resource_registration` | 600 | 600 | **SUCCESS** |
| 04 | `rep_portal_invites` | 550 | 550 | **SUCCESS** |
| 05 | `site_commd_activity_discussion` | 700 | 700 | **SUCCESS** |
| 06 | `site_commd_activity_document_collaboration` | 400 | 400 | **SUCCESS** |
| 07 | `site_commd_activity_pulse_survey` | 400 | 400 | **SUCCESS** |
| 08 | `site_commd_activity_pulse_survey_form` | 400 | 400 | **SUCCESS** |
| 09 | `site_commd_activity_pulse_survey_form_list` | 400 | 400 | **SUCCESS** |
| 10 | `site_commd_module_activity` | 400 | 400 | **SUCCESS** |
| 11 | `site_commd_resources` | 400 | 400 | **SUCCESS** |
| 12 | `site_commd_user_resource_views` | 400 | 400 | **SUCCESS** |
| 13 | `site_commd_user_setup_audit` | 400 | 400 | **SUCCESS** |
| 14 | `site_commd_workspace` | 400 | 400 | **SUCCESS** |
| 15 | `site_commd_workspace_event_resources` | 400 | 400 | **SUCCESS** |
| 16 | `site_commd_workspace_modules` | 400 | 400 | **SUCCESS** |
| 17 | `site_commd_workspace_resources` | 400 | 400 | **SUCCESS** |
| 18 | `site_commd_workspace_team` | 400 | 400 | **SUCCESS** |
| 19 | `site_detail_template` | 400 | 400 | **SUCCESS** |
| 20 | `site_details` | 600 | 600 | **SUCCESS** |
| 21 | `site_details_activity_report` | 500 | 500 | **SUCCESS** |
| 22 | `site_details_internal_affiliates` | 400 | 400 | **SUCCESS** |
| 23 | `site_event_formats` | 400 | 400 | **SUCCESS** |
| 24 | `site_event_leads` | 400 | 400 | **SUCCESS** |
| 25 | `site_event_registrant_custom_questions` | 400 | 400 | **SUCCESS** |
| 26 | `site_event_registrants` | 600 | 600 | **SUCCESS** |
| 27 | `site_event_registrants_analytics_report` | 400 | 400 | **SUCCESS** |
| 28 | `site_event_registrants_audit` | 400 | 400 | **SUCCESS** |
| 29 | `site_event_registrants_standardized_fields` | 400 | 400 | **SUCCESS** |
| 30 | `site_event_setup` | 400 | 400 | **SUCCESS** |
| 31 | `site_event_speakers` | 400 | 400 | **SUCCESS** |
| 32 | `site_event_staff` | 400 | 400 | **SUCCESS** |
| 33 | `site_event_telecom` | 400 | 400 | **SUCCESS** |
| 34 | `site_event_topics` | 400 | 400 | **SUCCESS** |
| 35 | `site_event_venue_details` | 400 | 400 | **SUCCESS** |
| 36 | `site_events` | 600 | 600 | **SUCCESS** |
| 37 | `site_events_account_activity` | 400 | 400 | **SUCCESS** |
| 38 | `site_events_country_block` | 400 | 400 | **SUCCESS** |
| 39 | `site_media_content` | 400 | 400 | **SUCCESS** |
| 40 | `site_media_content_account_activity` | 400 | 400 | **SUCCESS** |
| 41 | `site_module_resource` | 400 | 400 | **SUCCESS** |
| 42 | `site_project_codes` | 400 | 400 | **SUCCESS** |
| 43 | `site_speaker_affiliations` | 400 | 400 | **SUCCESS** |
| 44 | `site_speaker_approved_topics` | 400 | 400 | **SUCCESS** |
| 45 | `site_speaker_certifications` | 400 | 400 | **SUCCESS** |
| 46 | `site_speaker_degrees` | 400 | 400 | **SUCCESS** |
| 47 | `site_speaker_specialties` | 400 | 400 | **SUCCESS** |
| 48 | `site_speakers` | 550 | 550 | **SUCCESS** |
| 49 | `site_tags` | 400 | 400 | **SUCCESS** |
| 50 | `site_team_members` | 400 | 400 | **SUCCESS** |
| 51 | `site_topic_details_specialities` | 400 | 400 | **SUCCESS** |
| 52 | `site_topic_details_therapeutic_area` | 400 | 400 | **SUCCESS** |
| 53 | `site_topics` | 550 | 550 | **SUCCESS** |
| 54 | `site_view_only_registation_audit` | 400 | 400 | **SUCCESS** |
| 55 | `sitecore_campaign_details` | 400 | 400 | **SUCCESS** |
| 56 | `table_group` | 24 | 24 | **SUCCESS** |
| 57 | `table_load_settings` | 1 | 1 | **SUCCESS** |
| 58 | `user_account_content_shares` | 400 | 400 | **SUCCESS** |
| 59 | `user_account_event_email_invites` | 400 | 400 | **SUCCESS** |
| 60 | `user_account_event_requests` | 400 | 400 | **SUCCESS** |
| 61 | `user_account_logins` | 400 | 400 | **SUCCESS** |
| 62 | `user_account_pdf_invite_downloads` | 400 | 400 | **SUCCESS** |
| 63 | `user_account_session_audit` | 400 | 400 | **SUCCESS** |
| 64 | `user_accounts` | 550 | 550 | **SUCCESS** |
| 65 | `user_accounts_activity_report` | 400 | 400 | **SUCCESS** |
| 66 | `visitor_session` | 400 | 400 | **SUCCESS** |
| 67 | `visitor_session_analytics_report` | 400 | 400 | **SUCCESS** |

## 3. Identity Sequence Synchronization Ledger

PostgreSQL identity sequences were synchronized to prevent sequence collisions upon future inserts:

| Table Name | Identity Column | Attached Sequence | MAX Value Set | NEXTVAL Verified | Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SchemaVersions` | `Id` | `dbo."SchemaVersions_Id_seq"` | 150 | 151 | **SYNCHRONIZED** |
| `chatbot_conversation` | `id` | `dbo.chatbot_conversation_id_seq` | 20024 | 20025 | **SYNCHRONIZED** |
| `site_details` | `id` | `dbo.site_details_id_seq` | 601 | 602 | **SYNCHRONIZED** |
| `site_event_venue_details` | `id` | `dbo.site_event_venue_details_id_seq` | 400 | 401 | **SYNCHRONIZED** |
| `table_group` | `id` | `dbo.table_group_id_seq` | 24 | 25 | **SYNCHRONIZED** |
| `table_load_settings` | `id` | `dbo.table_load_settings_id_seq` | 1 | 2 | **SYNCHRONIZED** |
| `user_accounts` | `id` | `dbo.user_accounts_id_seq` | 550 | 551 | **SYNCHRONIZED** |
| `visitor_session` | `id` | `dbo.visitor_session_id_seq` | 400 | 401 | **SYNCHRONIZED** |

## 4. Deliverables Produced

1. `reports/phase13_step3_sqlserver_inventory.md`: Complete source catalog and row count inventory.
2. `reports/phase13_step3_type_mapping.md`: Full SQL Server to PostgreSQL data type mapping specification.
3. `reports/phase13_step3_migration_report.md`: This execution ledger and operational summary.
4. `reports/phase13_step3_validation_report.md`: Authoritative row-by-row, column-by-column, and constraint validation report.