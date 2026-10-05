# SQL Server Source Database Inventory (`mnghealthreportingdb`)

- **Inventory Date**: 2026-10-01 10:11:53
- **Source Server**: `localhost` (Windows Authentication)
- **Source Database**: `mnghealthreportingdb`
- **Source Schema**: `dbo`
- **Total Tables**: 67
- **Total Authoritative Rows**: 27,233
- **Total Foreign Keys**: 0
- **Distinct SQL Server Types**: bigint, binary, bit, datetime, datetime2, int, nvarchar, uniqueidentifier, varchar

## Table Inventory Summary

| Table Name | Row Count | Column Count | Primary Key | Identity Column | Non-PK Indexes |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `SchemaVersions` | 150 | 3 | Id | Id | 0 |
| `chatbot_conversation` | 58 | 8 | id | id | 0 |
| `portal_hcp_resource_registration` | 600 | 16 | None | None | 0 |
| `rep_portal_invites` | 550 | 10 | None | None | 0 |
| `site_commd_activity_discussion` | 700 | 11 | None | None | 0 |
| `site_commd_activity_document_collaboration` | 400 | 7 | None | None | 0 |
| `site_commd_activity_pulse_survey` | 400 | 8 | None | None | 0 |
| `site_commd_activity_pulse_survey_form` | 400 | 7 | None | None | 0 |
| `site_commd_activity_pulse_survey_form_list` | 400 | 7 | None | None | 0 |
| `site_commd_module_activity` | 400 | 5 | None | None | 0 |
| `site_commd_resources` | 400 | 3 | None | None | 0 |
| `site_commd_user_resource_views` | 400 | 8 | None | None | 0 |
| `site_commd_user_setup_audit` | 400 | 9 | None | None | 0 |
| `site_commd_workspace` | 400 | 5 | None | None | 0 |
| `site_commd_workspace_event_resources` | 400 | 10 | None | None | 0 |
| `site_commd_workspace_modules` | 400 | 7 | None | None | 0 |
| `site_commd_workspace_resources` | 400 | 3 | None | None | 0 |
| `site_commd_workspace_team` | 400 | 5 | None | None | 0 |
| `site_detail_template` | 400 | 3 | None | None | 0 |
| `site_details` | 600 | 34 | id | id | 0 |
| `site_details_activity_report` | 500 | 27 | id | None | 0 |
| `site_details_internal_affiliates` | 400 | 5 | None | None | 0 |
| `site_event_formats` | 400 | 5 | None | None | 0 |
| `site_event_leads` | 400 | 6 | None | None | 0 |
| `site_event_registrant_custom_questions` | 400 | 3 | None | None | 0 |
| `site_event_registrants` | 600 | 61 | None | None | 0 |
| `site_event_registrants_analytics_report` | 400 | 43 | None | None | 0 |
| `site_event_registrants_audit` | 400 | 5 | None | None | 0 |
| `site_event_registrants_standardized_fields` | 400 | 7 | None | None | 0 |
| `site_event_setup` | 400 | 5 | None | None | 0 |
| `site_event_speakers` | 400 | 2 | None | None | 0 |
| `site_event_staff` | 400 | 9 | None | None | 0 |
| `site_event_telecom` | 400 | 10 | None | None | 0 |
| `site_event_topics` | 400 | 2 | None | None | 0 |
| `site_event_venue_details` | 400 | 12 | None | id | 0 |
| `site_events` | 600 | 109 | None | None | 0 |
| `site_events_account_activity` | 400 | 90 | None | None | 0 |
| `site_events_country_block` | 400 | 6 | None | None | 0 |
| `site_media_content` | 400 | 9 | None | None | 0 |
| `site_media_content_account_activity` | 400 | 9 | None | None | 0 |
| `site_module_resource` | 400 | 3 | None | None | 0 |
| `site_project_codes` | 400 | 5 | None | None | 0 |
| `site_speaker_affiliations` | 400 | 2 | None | None | 0 |
| `site_speaker_approved_topics` | 400 | 2 | None | None | 0 |
| `site_speaker_certifications` | 400 | 3 | None | None | 0 |
| `site_speaker_degrees` | 400 | 2 | None | None | 0 |
| `site_speaker_specialties` | 400 | 2 | None | None | 0 |
| `site_speakers` | 550 | 29 | None | None | 0 |
| `site_tags` | 400 | 2 | None | None | 0 |
| `site_team_members` | 400 | 7 | None | None | 0 |
| `site_topic_details_specialities` | 400 | 5 | None | None | 0 |
| `site_topic_details_therapeutic_area` | 400 | 5 | None | None | 0 |
| `site_topics` | 550 | 13 | None | None | 0 |
| `site_view_only_registation_audit` | 400 | 7 | None | None | 0 |
| `sitecore_campaign_details` | 400 | 6 | None | None | 0 |
| `table_group` | 24 | 4 | None | id | 0 |
| `table_load_settings` | 1 | 9 | id | id | 0 |
| `user_account_content_shares` | 400 | 6 | None | None | 0 |
| `user_account_event_email_invites` | 400 | 8 | None | None | 0 |
| `user_account_event_requests` | 400 | 9 | None | None | 0 |
| `user_account_logins` | 400 | 3 | None | None | 0 |
| `user_account_pdf_invite_downloads` | 400 | 5 | None | None | 0 |
| `user_account_session_audit` | 400 | 5 | None | None | 0 |
| `user_accounts` | 550 | 29 | None | id | 0 |
| `user_accounts_activity_report` | 400 | 27 | None | None | 0 |
| `visitor_session` | 400 | 23 | None | id | 0 |
| `visitor_session_analytics_report` | 400 | 23 | None | None | 0 |

## Detailed Schema and Column Breakdown

### `SchemaVersions`
- **Row count**: 150
- **Primary Key**: PK_SchemaVersions_Id (Id)
- **Identity Column**: `Id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `Id` | int | NOT NULL | YES |  |
| 2 | `ScriptName` | nvarchar(255) | NOT NULL | NO |  |
| 3 | `Applied` | datetime | NOT NULL | NO |  |

### `chatbot_conversation`
- **Row count**: 58
- **Primary Key**: PK__chatbot___3213E83F7CD9559A (id)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | bigint | NOT NULL | YES |  |
| 2 | `session_id` | nvarchar(100) | NOT NULL | NO |  |
| 3 | `reference_id` | nvarchar(100) | NOT NULL | NO |  |
| 4 | `question` | nvarchar(max) | NOT NULL | NO |  |
| 5 | `result_columns` | nvarchar(max) | NULL | NO |  |
| 6 | `result_data` | nvarchar(max) | NULL | NO |  |
| 7 | `created_at` | datetime2 | NOT NULL | NO | `(sysutcdatetime())` |
| 8 | `query_context` | nvarchar(max) | NULL | NO |  |

### `portal_hcp_resource_registration`
- **Row count**: 600
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `search_source_id` | nvarchar(200) | NULL | NO |  |
| 2 | `registrant_first_name` | nvarchar(1000) | NULL | NO |  |
| 3 | `registrant_last_name` | nvarchar(1000) | NULL | NO |  |
| 4 | `registrant_specialty` | nvarchar(max) | NULL | NO |  |
| 5 | `registrant_degree` | nvarchar(max) | NULL | NO |  |
| 6 | `registration_date` | datetime | NULL | NO |  |
| 7 | `registrant_address` | nvarchar(max) | NULL | NO |  |
| 8 | `registrant_city` | nvarchar(max) | NULL | NO |  |
| 9 | `registrant_state` | nvarchar(max) | NULL | NO |  |
| 10 | `registrant_email` | nvarchar(max) | NULL | NO |  |
| 11 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 12 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 13 | `content_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 14 | `group_registration_id` | uniqueidentifier | NULL | NO |  |
| 15 | `email_status` | nvarchar(20) | NULL | NO |  |
| 16 | `registrant_country` | nvarchar(max) | NULL | NO |  |

### `rep_portal_invites`
- **Row count**: 550
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `first_name` | nvarchar(100) | NOT NULL | NO |  |
| 2 | `last_name` | nvarchar(100) | NOT NULL | NO |  |
| 3 | `email_address` | nvarchar(255) | NOT NULL | NO |  |
| 4 | `tenant_id` | uniqueidentifier | NOT NULL | NO |  |
| 5 | `event_id` | uniqueidentifier | NOT NULL | NO |  |
| 6 | `rep_name` | nvarchar(200) | NOT NULL | NO |  |
| 7 | `invite_sent_datetime` | datetime2 | NOT NULL | NO |  |
| 8 | `sitecore_invitation_id` | uniqueidentifier | NOT NULL | NO |  |
| 9 | `invitation_mail_id` | int | NOT NULL | NO |  |
| 10 | `rep_account_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_commd_activity_discussion`
- **Row count**: 700
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `account_workspace_id` | uniqueidentifier | NULL | NO |  |
| 3 | `account_module_id` | uniqueidentifier | NULL | NO |  |
| 4 | `account_activity_id` | uniqueidentifier | NULL | NO |  |
| 5 | `account_email` | nvarchar(max) | NULL | NO |  |
| 6 | `comment` | nvarchar(max) | NULL | NO |  |
| 7 | `comment_date` | datetime | NULL | NO |  |
| 8 | `reply_to_account_id` | nvarchar(max) | NULL | NO |  |
| 9 | `comment_id` | uniqueidentifier | NULL | NO |  |
| 10 | `parent_comment_id` | uniqueidentifier | NULL | NO |  |
| 11 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_commd_activity_document_collaboration`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `account_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `account_activity_id` | uniqueidentifier | NULL | NO |  |
| 4 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 5 | `account_name` | nvarchar(400) | NULL | NO |  |
| 6 | `annotation_details` | nvarchar(max) | NULL | NO |  |
| 7 | `annotation_date` | datetime2 | NULL | NO |  |

### `site_commd_activity_pulse_survey`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_activity_id` | uniqueidentifier | NULL | NO |  |
| 4 | `sitecore_form_id` | uniqueidentifier | NULL | NO |  |
| 5 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 6 | `field_name` | nvarchar(max) | NULL | NO |  |
| 7 | `field_answer` | nvarchar(max) | NULL | NO |  |
| 8 | `survey_answer_date` | datetime2 | NULL | NO |  |

### `site_commd_activity_pulse_survey_form`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_activity_id` | uniqueidentifier | NULL | NO |  |
| 4 | `sitecore_form_id` | uniqueidentifier | NULL | NO |  |
| 5 | `field_type` | nvarchar(max) | NULL | NO |  |
| 6 | `field_name` | nvarchar(max) | NULL | NO |  |
| 7 | `field_title` | nvarchar(max) | NULL | NO |  |

### `site_commd_activity_pulse_survey_form_list`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_activity_id` | uniqueidentifier | NULL | NO |  |
| 4 | `sitecore_form_id` | uniqueidentifier | NULL | NO |  |
| 5 | `field_name` | nvarchar(max) | NULL | NO |  |
| 6 | `choice_value` | nvarchar(max) | NULL | NO |  |
| 7 | `choice_text` | nvarchar(max) | NULL | NO |  |

### `site_commd_module_activity`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | nvarchar(max) | NULL | NO |  |
| 2 | `sitecore_module_id` | nvarchar(max) | NULL | NO |  |
| 3 | `sitecore_activity_discussion_id` | nvarchar(max) | NULL | NO |  |
| 4 | `activity_name` | nvarchar(max) | NULL | NO |  |
| 5 | `activity_type` | nvarchar(max) | NULL | NO |  |

### `site_commd_resources`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_resource_id` | uniqueidentifier | NULL | NO |  |
| 2 | `resource_type` | nvarchar(max) | NULL | NO |  |
| 3 | `resource_name` | nvarchar(max) | NULL | NO |  |

### `site_commd_user_resource_views`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_activity_id` | uniqueidentifier | NULL | NO |  |
| 4 | `account_email_id` | nvarchar(max) | NULL | NO |  |
| 5 | `visitor_session_id` | nvarchar(max) | NULL | NO |  |
| 6 | `sitecore_resource_id` | uniqueidentifier | NULL | NO |  |
| 7 | `view_date` | datetime2 | NULL | NO |  |
| 8 | `was_downloaded` | bit | NULL | NO |  |

### `site_commd_user_setup_audit`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_workspace_id` | uniqueidentifier | NULL | NO |  |
| 3 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 4 | `email_sent_date` | datetime2 | NULL | NO |  |
| 5 | `wlecome_setup_complete` | bit | NULL | NO |  |
| 6 | `first_time_accessed_date` | datetime2 | NULL | NO |  |
| 7 | `agreement_accepted_date` | datetime2 | NULL | NO |  |
| 8 | `mobile_opt_in` | bit | NULL | NO |  |
| 9 | `profile_photo_uploaded` | bit | NULL | NO |  |

### `site_commd_workspace`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_workspace_id` | uniqueidentifier | NULL | NO |  |
| 3 | `workspace_name` | nvarchar(max) | NULL | NO |  |
| 4 | `workspace_description` | nvarchar(max) | NULL | NO |  |
| 5 | `is_test` | bit | NULL | NO |  |

### `site_commd_workspace_event_resources`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_resource_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_event_landing_page_id` | uniqueidentifier | NULL | NO |  |
| 4 | `resource_type` | nvarchar(max) | NULL | NO |  |
| 5 | `resource_name` | nvarchar(max) | NULL | NO |  |
| 6 | `sitecore_workspace_id` | uniqueidentifier | NULL | NO |  |
| 7 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 8 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 9 | `updated_date` | datetime | NULL | NO | `(getdate())` |
| 10 | `sitecore_event_id` | uniqueidentifier | NULL | NO |  |

### `site_commd_workspace_modules`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_workspace_id` | uniqueidentifier | NULL | NO |  |
| 4 | `module_name` | nvarchar(max) | NULL | NO |  |
| 5 | `module_open_date` | nvarchar(max) | NULL | NO |  |
| 6 | `module_close_date` | nvarchar(max) | NULL | NO |  |
| 7 | `module_status` | nvarchar(max) | NULL | NO |  |

### `site_commd_workspace_resources`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_workspace_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_resource_id` | uniqueidentifier | NULL | NO |  |

### `site_commd_workspace_team`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_workspace_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 4 | `account_email` | nvarchar(max) | NULL | NO |  |
| 5 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_detail_template`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `template` | nvarchar(2000) | NULL | NO |  |
| 3 | `template_type_id` | uniqueidentifier | NULL | NO |  |

### `site_details`
- **Row count**: 600
- **Primary Key**: PK__site_det__3213E83F439B08FD (id)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | YES |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `site_client_name` | nvarchar(255) | NULL | NO |  |
| 4 | `site_brands` | nvarchar(255) | NULL | NO |  |
| 5 | `site_vanity_link` | nvarchar(150) | NULL | NO |  |
| 6 | `site_prod_link` | nvarchar(150) | NULL | NO |  |
| 7 | `site_test_link` | nvarchar(150) | NULL | NO |  |
| 8 | `site_go_live_date` | datetime | NULL | NO |  |
| 9 | `site_type` | nvarchar(150) | NULL | NO |  |
| 10 | `site_client_id` | nvarchar(150) | NULL | NO |  |
| 11 | `site_status` | nvarchar(150) | NULL | NO |  |
| 12 | `site_created_date` | datetime | NULL | NO |  |
| 13 | `site_expiration_date` | datetime | NULL | NO |  |
| 14 | `site_branded` | bit | NULL | NO |  |
| 15 | `site_name` | nvarchar(150) | NULL | NO |  |
| 16 | `test_site` | nvarchar(20) | NULL | NO |  |
| 17 | `site_template` | nvarchar(max) | NULL | NO |  |
| 18 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 19 | `updated_date` | datetime | NULL | NO | `(getdate())` |
| 20 | `site_brand_id` | nvarchar(4000) | NULL | NO |  |
| 21 | `promo_activity_id` | nvarchar(4000) | NULL | NO |  |
| 22 | `product_name` | nvarchar(4000) | NULL | NO |  |
| 23 | `product_id` | nvarchar(4000) | NULL | NO |  |
| 24 | `subproduct_name` | nvarchar(max) | NULL | NO |  |
| 25 | `subproduct_id` | nvarchar(max) | NULL | NO |  |
| 26 | `therapeutic_area` | nvarchar(max) | NULL | NO |  |
| 27 | `internal_affiliates` | nvarchar(max) | NULL | NO |  |
| 28 | `site_project_id` | nvarchar(max) | NULL | NO |  |
| 29 | `sms_reminders` | bit | NULL | NO | `((0))` |
| 30 | `indication` | nvarchar(150) | NULL | NO |  |
| 31 | `site_reference_number` | nvarchar(5) | NULL | NO |  |
| 32 | `country` | nvarchar(max) | NULL | NO |  |
| 33 | `business_unit` | nvarchar(max) | NULL | NO | `(NULL)` |
| 34 | `rep_portal` | nvarchar(20) | NULL | NO | `('False')` |

### `site_details_activity_report`
- **Row count**: 500
- **Primary Key**: PK__site_det__3213E83F8111D6B9 (id)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `site_client_name` | nvarchar(255) | NULL | NO |  |
| 4 | `site_brands` | nvarchar(255) | NULL | NO |  |
| 5 | `site_vanity_link` | nvarchar(150) | NULL | NO |  |
| 6 | `site_prod_link` | nvarchar(150) | NULL | NO |  |
| 7 | `site_test_link` | nvarchar(150) | NULL | NO |  |
| 8 | `site_go_live_date` | datetime | NULL | NO |  |
| 9 | `site_type` | nvarchar(150) | NULL | NO |  |
| 10 | `site_client_id` | nvarchar(150) | NULL | NO |  |
| 11 | `site_status` | nvarchar(150) | NULL | NO |  |
| 12 | `site_created_date` | datetime | NULL | NO |  |
| 13 | `site_expiration_date` | datetime | NULL | NO |  |
| 14 | `site_branded` | bit | NULL | NO |  |
| 15 | `site_name` | nvarchar(150) | NULL | NO |  |
| 16 | `test_site` | nvarchar(20) | NULL | NO |  |
| 18 | `created_date` | datetime | NULL | NO |  |
| 19 | `updated_date` | datetime | NULL | NO |  |
| 20 | `site_brand_id` | nvarchar(4000) | NULL | NO |  |
| 21 | `promo_activity_id` | nvarchar(4000) | NULL | NO |  |
| 22 | `product_name` | nvarchar(4000) | NULL | NO |  |
| 23 | `product_id` | nvarchar(4000) | NULL | NO |  |
| 24 | `subproduct_name` | nvarchar(max) | NULL | NO |  |
| 25 | `subproduct_id` | nvarchar(max) | NULL | NO |  |
| 26 | `site_template` | nvarchar(max) | NULL | NO |  |
| 27 | `site_reference_number` | nvarchar(5) | NULL | NO |  |
| 28 | `country` | nvarchar(max) | NULL | NO |  |

### `site_details_internal_affiliates`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `site_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `affiliates_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `affiliates_type` | nvarchar(255) | NULL | NO |  |
| 4 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 5 | `updated_date` | datetime | NULL | NO | `(getdate())` |

### `site_event_formats`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `format_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `formats_type` | nvarchar(255) | NULL | NO |  |
| 4 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 5 | `updated_date` | datetime | NULL | NO | `(getdate())` |

### `site_event_leads`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `registration_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `first_name` | nvarchar(500) | NULL | NO |  |
| 4 | `last_name` | nvarchar(500) | NULL | NO |  |
| 5 | `email` | nvarchar(500) | NULL | NO |  |
| 6 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_event_registrant_custom_questions`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `registration_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `custom_question` | nvarchar(1000) | NULL | NO |  |
| 3 | `custom_answer` | nvarchar(1000) | NULL | NO |  |

### `site_event_registrants`
- **Row count**: 600
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `registration_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 4 | `visitor_session_id` | nvarchar(250) | NULL | NO |  |
| 5 | `registration_date` | datetime | NULL | NO |  |
| 7 | `registrant_client_id` | nvarchar(250) | NULL | NO |  |
| 8 | `event_provider_registration_id` | nvarchar(250) | NULL | NO |  |
| 9 | `registrant_first_name` | nvarchar(550) | NULL | NO |  |
| 10 | `registrant_last_name` | nvarchar(550) | NULL | NO |  |
| 11 | `registrant_specialty` | nvarchar(550) | NULL | NO |  |
| 12 | `registrant_degree` | nvarchar(550) | NULL | NO |  |
| 13 | `registrant_timezone` | nvarchar(250) | NULL | NO |  |
| 14 | `registrant_address` | nvarchar(4000) | NULL | NO |  |
| 15 | `registrant_city` | nvarchar(250) | NULL | NO |  |
| 16 | `registrant_state` | nvarchar(250) | NULL | NO |  |
| 17 | `registrant_email` | nvarchar(550) | NULL | NO |  |
| 18 | `registrant_type` | nvarchar(250) | NULL | NO |  |
| 19 | `registrant_access_link` | nvarchar(550) | NULL | NO |  |
| 20 | `registrant_status` | nvarchar(250) | NULL | NO |  |
| 21 | `registrant_data_source` | nvarchar(250) | NULL | NO |  |
| 22 | `registrant_form_npi` | nvarchar(250) | NULL | NO |  |
| 24 | `registrant_sign_in_link` | nvarchar(1000) | NULL | NO |  |
| 25 | `registrant_parent_sign_in_status` | nvarchar(550) | NULL | NO |  |
| 26 | `registrant_attendance_status` | nvarchar(550) | NULL | NO |  |
| 27 | `registrant_audience_type` | nvarchar(550) | NULL | NO |  |
| 28 | `test_registrant` | bit | NULL | NO |  |
| 29 | `registrant_decrypted_npi` | nvarchar(550) | NULL | NO |  |
| 30 | `registrant_uac` | nvarchar(550) | NULL | NO |  |
| 31 | `registrant_zip` | nvarchar(550) | NULL | NO |  |
| 32 | `search_source_id_type` | nvarchar(500) | NULL | NO |  |
| 33 | `search_source_id` | nvarchar(500) | NULL | NO |  |
| 34 | `rep_account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 35 | `registrant_cancel_date` | datetime2 | NULL | NO |  |
| 36 | `registrant_event_lead` | bit | NULL | NO |  |
| 37 | `registrant_event_staff` | bit | NULL | NO |  |
| 38 | `registrant_event_staff_role` | nvarchar(1000) | NULL | NO |  |
| 39 | `visitor_origin` | nvarchar(255) | NULL | NO |  |
| 40 | `registrant_attendance_type` | nvarchar(255) | NULL | NO |  |
| 41 | `event_venue_id` | nvarchar(255) | NULL | NO |  |
| 42 | `event_venue_name` | nvarchar(255) | NULL | NO |  |
| 43 | `event_venue_address` | nvarchar(255) | NULL | NO |  |
| 44 | `view_only_stream` | bit | NULL | NO |  |
| 45 | `is_venue_registration` | bit | NULL | NO | `((0))` |
| 46 | `venu_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 47 | `sms_opt_in` | bit | NULL | NO |  |
| 48 | `event_signin_origin` | varchar(50) | NULL | NO |  |
| 49 | `view_stream_watch_count` | int | NULL | NO |  |
| 50 | `view_stream_watch_duration` | int | NULL | NO |  |
| 51 | `registrant_parent_sign_in_status_date` | datetime2 | NULL | NO |  |
| 52 | `referral_link_url` | nvarchar(4000) | NULL | NO |  |
| 53 | `registrant_country` | nvarchar(max) | NULL | NO |  |
| 54 | `registrant_extension_phone` | nvarchar(4000) | NULL | NO |  |
| 55 | `registrant_fax` | nvarchar(4000) | NULL | NO |  |
| 56 | `registrant_company` | nvarchar(4000) | NULL | NO |  |
| 57 | `registrant_job_title` | nvarchar(4000) | NULL | NO |  |
| 58 | `registrant_reference_number` | nvarchar(5) | NULL | NO |  |
| 59 | `waitlist_status` | nvarchar(255) | NULL | NO |  |
| 60 | `field_approval_status` | nvarchar(255) | NULL | NO |  |
| 61 | `capacity_waitlist_status` | nvarchar(255) | NULL | NO |  |
| 62 | `incomplete_referral_link_url` | nvarchar(4000) | NULL | NO |  |
| 63 | `row_hash` | binary | NULL | NO |  |

### `site_event_registrants_analytics_report`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `registration_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 4 | `visitor_session_id` | nvarchar(250) | NULL | NO |  |
| 5 | `registration_date` | datetime | NULL | NO |  |
| 6 | `registrant_client_id` | nvarchar(250) | NULL | NO |  |
| 7 | `event_provider_registration_id` | nvarchar(250) | NULL | NO |  |
| 8 | `registrant_first_name` | nvarchar(550) | NULL | NO |  |
| 9 | `registrant_last_name` | nvarchar(550) | NULL | NO |  |
| 10 | `registrant_specialty` | nvarchar(550) | NULL | NO |  |
| 11 | `registrant_degree` | nvarchar(550) | NULL | NO |  |
| 12 | `registrant_timezone` | nvarchar(250) | NULL | NO |  |
| 13 | `registrant_address` | nvarchar(4000) | NULL | NO |  |
| 14 | `registrant_city` | nvarchar(250) | NULL | NO |  |
| 15 | `registrant_state` | nvarchar(250) | NULL | NO |  |
| 16 | `registrant_email` | nvarchar(550) | NULL | NO |  |
| 17 | `registrant_type` | nvarchar(250) | NULL | NO |  |
| 18 | `registrant_access_link` | nvarchar(550) | NULL | NO |  |
| 19 | `registrant_status` | nvarchar(250) | NULL | NO |  |
| 20 | `registrant_data_source` | nvarchar(250) | NULL | NO |  |
| 21 | `registrant_form_npi` | nvarchar(250) | NULL | NO |  |
| 22 | `registrant_sign_in_link` | nvarchar(1000) | NULL | NO |  |
| 23 | `registrant_parent_sign_in_status` | nvarchar(550) | NULL | NO |  |
| 24 | `registrant_attendance_status` | nvarchar(550) | NULL | NO |  |
| 25 | `registrant_audience_type` | nvarchar(550) | NULL | NO |  |
| 26 | `test_registrant` | bit | NULL | NO |  |
| 27 | `registrant_decrypted_npi` | nvarchar(550) | NULL | NO |  |
| 28 | `registrant_uac` | nvarchar(550) | NULL | NO |  |
| 29 | `registrant_zip` | nvarchar(550) | NULL | NO |  |
| 30 | `search_source_id_type` | nvarchar(500) | NULL | NO |  |
| 31 | `search_source_id` | nvarchar(500) | NULL | NO |  |
| 32 | `rep_account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 33 | `registrant_cancel_date` | datetime2 | NULL | NO |  |
| 34 | `registrant_event_lead` | bit | NULL | NO |  |
| 35 | `registrant_event_staff` | bit | NULL | NO |  |
| 36 | `registrant_event_staff_role` | nvarchar(1000) | NULL | NO |  |
| 37 | `visitor_origin` | nvarchar(255) | NULL | NO |  |
| 38 | `view_only_stream` | bit | NULL | NO |  |
| 39 | `sms_opt_in` | bit | NULL | NO |  |
| 40 | `event_signin_origin` | varchar(50) | NULL | NO |  |
| 41 | `view_stream_watch_count` | int | NULL | NO |  |
| 42 | `view_stream_watch_duration` | int | NULL | NO |  |
| 43 | `registrant_reference_number` | nvarchar(5) | NULL | NO |  |

### `site_event_registrants_audit`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `registration_sitecore_id` | uniqueidentifier | NOT NULL | NO |  |
| 2 | `field_name` | nvarchar(2000) | NULL | NO |  |
| 3 | `field_value_old` | nvarchar(4000) | NULL | NO |  |
| 4 | `field_value_new` | nvarchar(4000) | NULL | NO |  |
| 5 | `updated_datetime` | datetime | NULL | NO |  |

### `site_event_registrants_standardized_fields`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `registration_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 4 | `registration_form_field_id` | nvarchar(4000) | NULL | NO |  |
| 5 | `standardized_field_id` | nvarchar(4000) | NULL | NO |  |
| 6 | `standardized_field_text` | nvarchar(4000) | NULL | NO |  |
| 7 | `standardized_field_abbrev` | nvarchar(4000) | NULL | NO |  |

### `site_event_setup`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `setup_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `setup_type` | nvarchar(255) | NULL | NO |  |
| 4 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 5 | `updated_date` | datetime | NULL | NO | `(getdate())` |

### `site_event_speakers`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_event_staff`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `first_name` | nvarchar(250) | NULL | NO |  |
| 4 | `last_name` | nvarchar(250) | NULL | NO |  |
| 5 | `email_address` | nvarchar(550) | NULL | NO |  |
| 6 | `timezone` | nvarchar(250) | NULL | NO |  |
| 7 | `staff_status` | nvarchar(250) | NULL | NO |  |
| 8 | `staff_role` | nvarchar(250) | NULL | NO |  |
| 9 | `staff_team` | nvarchar(250) | NULL | NO |  |

### `site_event_telecom`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `telecom_provider` | nvarchar(250) | NULL | NO |  |
| 3 | `telecom_provider_name` | nvarchar(250) | NULL | NO |  |
| 4 | `telecom_reservation_id` | int | NULL | NO |  |
| 5 | `mng_telecom_label` | nvarchar(250) | NULL | NO |  |
| 6 | `bridge_leader_pin` | nvarchar(250) | NULL | NO |  |
| 7 | `presenter_dial_in` | nvarchar(250) | NULL | NO |  |
| 8 | `presenter_passcode` | nvarchar(250) | NULL | NO |  |
| 9 | `attendee_passcode` | nvarchar(250) | NULL | NO |  |
| 10 | `moderator_passcode` | nvarchar(250) | NULL | NO |  |

### `site_event_topics`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `topic_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_event_venue_details`
- **Row count**: 400
- **Primary Key**: None (None)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | YES |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `venue_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 4 | `venue_name` | nvarchar(255) | NULL | NO |  |
| 5 | `venue_address1` | nvarchar(max) | NULL | NO |  |
| 6 | `venue_address2` | nvarchar(max) | NULL | NO |  |
| 7 | `venue_city_venue_state` | nvarchar(500) | NULL | NO |  |
| 8 | `venue_zip` | nvarchar(16) | NULL | NO |  |
| 9 | `venue_phone1` | nvarchar(20) | NULL | NO |  |
| 10 | `longitude` | nvarchar(max) | NULL | NO |  |
| 11 | `latitude` | nvarchar(max) | NULL | NO |  |
| 12 | `venue_capacity` | int | NULL | NO |  |

### `site_events`
- **Row count**: 600
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `event_client_id` | nvarchar(250) | NULL | NO |  |
| 4 | `event_status` | nvarchar(150) | NULL | NO |  |
| 5 | `event_start_datetime` | datetime2 | NULL | NO |  |
| 6 | `event_duration` | int | NULL | NO |  |
| 8 | `event_type` | nvarchar(250) | NULL | NO |  |
| 9 | `event_provider_platform` | nvarchar(250) | NULL | NO |  |
| 10 | `event_provider_platform_id` | nvarchar(150) | NULL | NO |  |
| 11 | `event_language` | nvarchar(150) | NULL | NO |  |
| 12 | `event_cancel_datetime` | datetime2 | NULL | NO |  |
| 13 | `event_speaker_sitecore_id` | nvarchar(4000) | NULL | NO |  |
| 14 | `event_topic_sitecore_id` | nvarchar(4000) | NULL | NO |  |
| 15 | `event_format` | nvarchar(250) | NULL | NO |  |
| 16 | `event_precon_time` | nvarchar(150) | NULL | NO |  |
| 17 | `event_client_precon_time` | nvarchar(150) | NULL | NO |  |
| 18 | `event_brands` | nvarchar(250) | NULL | NO |  |
| 19 | `event_capacity_limit` | int | NULL | NO |  |
| 20 | `event_topic_title` | nvarchar(500) | NULL | NO |  |
| 21 | `event_platform_host_account` | nvarchar(250) | NULL | NO |  |
| 22 | `event_provider_template` | nvarchar(250) | NULL | NO |  |
| 23 | `event_signin_page_url` | nvarchar(550) | NULL | NO |  |
| 24 | `event_rep_page_url` | nvarchar(550) | NULL | NO |  |
| 25 | `event_dial_in` | nvarchar(250) | NULL | NO |  |
| 26 | `event_telecom` | nvarchar(250) | NULL | NO |  |
| 27 | `event_requested_by` | nvarchar(250) | NULL | NO |  |
| 28 | `event_private` | nvarchar(50) | NULL | NO |  |
| 29 | `event_project_id` | nvarchar(250) | NULL | NO |  |
| 30 | `test_event` | bit | NULL | NO |  |
| 31 | `enforce_capacity_limit` | bit | NULL | NO |  |
| 32 | `event_created_datetime` | datetime2 | NULL | NO |  |
| 33 | `event_other` | nvarchar(250) | NULL | NO |  |
| 34 | `event_description` | nvarchar(4000) | NULL | NO |  |
| 35 | `event_image_link` | nvarchar(250) | NULL | NO |  |
| 36 | `run_slides` | nvarchar(1000) | NULL | NO |  |
| 37 | `polls_WB` | bit | NULL | NO |  |
| 38 | `record_event` | bit | NULL | NO |  |
| 39 | `breakout_room` | bit | NULL | NO |  |
| 40 | `breakout_room_notes` | nvarchar(4000) | NULL | NO |  |
| 41 | `international_callers` | bit | NULL | NO |  |
| 42 | `special_events_calendar` | bit | NULL | NO |  |
| 43 | `cc_email_address` | nvarchar(250) | NULL | NO |  |
| 44 | `speaker_paid` | bit | NULL | NO |  |
| 45 | `cause_of_cancelation` | nvarchar(4000) | NULL | NO |  |
| 46 | `cancel_notes` | nvarchar(4000) | NULL | NO |  |
| 47 | `trigger_cancelation_emails_speakers` | bit | NULL | NO |  |
| 48 | `trigger_cancelation_emails_hcp` | bit | NULL | NO |  |
| 49 | `trigger_cancelation_emails_reps` | bit | NULL | NO |  |
| 50 | `trigger_cancelation_emails_other` | bit | NULL | NO |  |
| 51 | `actual_start_time` | datetime2 | NULL | NO |  |
| 52 | `actual_end_time` | datetime2 | NULL | NO |  |
| 53 | `adverse_event_mentioned` | bit | NULL | NO |  |
| 54 | `describe_adverse_events` | nvarchar(4000) | NULL | NO |  |
| 55 | `number_of_attendees_on_camera` | nvarchar(4000) | NULL | NO |  |
| 56 | `number_of_verbal_questions_asked` | nvarchar(4000) | NULL | NO |  |
| 59 | `items_to_note_for_chat_box_or_messages` | nvarchar(4000) | NULL | NO |  |
| 60 | `speaker_arrival_time` | nvarchar(250) | NULL | NO |  |
| 61 | `speaker_connected_to_audio_time` | nvarchar(250) | NULL | NO |  |
| 62 | `speaker_feedback` | nvarchar(250) | NULL | NO |  |
| 63 | `speaker_rating` | nvarchar(250) | NULL | NO |  |
| 64 | `speaker_issues` | nvarchar(4000) | NULL | NO |  |
| 65 | `speaker_issue_notes` | nvarchar(4000) | NULL | NO |  |
| 66 | `event_lead_joined_program` | bit | NULL | NO |  |
| 67 | `event_lead_connected_to_audio_time` | nvarchar(250) | NULL | NO |  |
| 68 | `names_of_compliance_officers_on_call` | nvarchar(4000) | NULL | NO |  |
| 69 | `help_needed_from_MNG_slack_support` | bit | NULL | NO |  |
| 70 | `compliance` | nvarchar(4000) | NULL | NO |  |
| 71 | `other_notes` | nvarchar(4000) | NULL | NO |  |
| 72 | `phone_only_attendees` | bit | NULL | NO |  |
| 73 | `phone_only_attendees_number_or_name_if_received` | nvarchar(4000) | NULL | NO |  |
| 74 | `number_of_chat_box_questions_content_only` | nvarchar(4000) | NULL | NO |  |
| 75 | `paste_content_related_questions` | nvarchar(4000) | NULL | NO |  |
| 76 | `event_issues` | nvarchar(4000) | NULL | NO |  |
| 77 | `event_issues_notes` | nvarchar(4000) | NULL | NO |  |
| 78 | `mng_platform_or_tech_issue` | nvarchar(4000) | NULL | NO |  |
| 79 | `event_lead_technical_issue` | nvarchar(4000) | NULL | NO |  |
| 80 | `event_lead_non_technical_issue` | nvarchar(4000) | NULL | NO |  |
| 81 | `post_program_report_complete` | bit | NULL | NO |  |
| 82 | `event_updated_datetime` | datetime2 | NULL | NO |  |
| 83 | `event_page_url` | nvarchar(500) | NULL | NO |  |
| 84 | `available_for_public_api` | bit | NULL | NO |  |
| 85 | `promo_activity_id` | nvarchar(max) | NULL | NO |  |
| 86 | `is_venue_enabled` | bit | NULL | NO | `((0))` |
| 87 | `default_venue_sitecore_id` | nvarchar(50) | NULL | NO |  |
| 88 | `venue_map_enabled` | bit | NULL | NO | `((0))` |
| 89 | `form_serial_number` | int | NULL | NO | `((-1))` |
| 90 | `venue_locations` | nvarchar(max) | NULL | NO |  |
| 91 | `sso_registration` | bit | NULL | NO | `((1))` |
| 92 | `medscape_interface` | bit | NULL | NO | `((1))` |
| 93 | `event_display` | bit | NULL | NO | `((1))` |
| 94 | `venue_capacity` | int | NULL | NO |  |
| 95 | `venue_site_notes` | nvarchar(4000) | NULL | NO |  |
| 96 | `event_audience_type` | nvarchar(50) | NULL | NO |  |
| 97 | `registration_confirmation_url` | nvarchar(500) | NULL | NO |  |
| 98 | `event_specialty_for_api` | nvarchar(max) | NULL | NO |  |
| 99 | `limited_entry_event` | bit | NULL | NO | `((0))` |
| 100 | `event_is_accredited` | bit | NULL | NO | `((0))` |
| 101 | `event_reference_number` | nvarchar(5) | NULL | NO |  |
| 102 | `promo_email_launch` | datetime | NULL | NO |  |
| 103 | `web_banner_go_live` | datetime | NULL | NO |  |
| 104 | `digital_on_demand_go_live` | datetime | NULL | NO |  |
| 105 | `event_created_date` | datetime | NULL | NO |  |
| 106 | `rep_requested_event_confirmed_date` | datetime | NULL | NO |  |
| 107 | `paste_all_event_chat_box_messages` | nvarchar(max) | NULL | NO |  |
| 108 | `paste_all_external_slack_chat_messages_non_content` | nvarchar(max) | NULL | NO |  |
| 109 | `live_stream_event_id` | nvarchar(255) | NULL | NO |  |
| 112 | `post_event_redirect` | datetime2 | NULL | NO |  |
| 113 | `pre_event_join_window` | int | NULL | NO |  |
| 114 | `reg_sign_in_cut_off_window` | int | NULL | NO |  |

### `site_events_account_activity`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `event_client_id` | nvarchar(250) | NULL | NO |  |
| 4 | `event_status` | nvarchar(150) | NULL | NO |  |
| 5 | `event_start_datetime` | datetime2 | NULL | NO |  |
| 6 | `event_duration` | int | NULL | NO |  |
| 7 | `event_type` | nvarchar(250) | NULL | NO |  |
| 8 | `event_provider_platform` | nvarchar(250) | NULL | NO |  |
| 9 | `event_provider_platform_id` | nvarchar(150) | NULL | NO |  |
| 10 | `event_language` | nvarchar(150) | NULL | NO |  |
| 11 | `event_cancel_datetime` | datetime2 | NULL | NO |  |
| 12 | `event_speaker_sitecore_id` | nvarchar(4000) | NULL | NO |  |
| 13 | `event_topic_sitecore_id` | nvarchar(4000) | NULL | NO |  |
| 14 | `event_format` | nvarchar(250) | NULL | NO |  |
| 15 | `event_precon_time` | nvarchar(150) | NULL | NO |  |
| 16 | `event_client_precon_time` | nvarchar(150) | NULL | NO |  |
| 17 | `event_brands` | nvarchar(250) | NULL | NO |  |
| 18 | `event_capacity_limit` | int | NULL | NO |  |
| 19 | `event_topic_title` | nvarchar(500) | NULL | NO |  |
| 20 | `event_platform_host_account` | nvarchar(250) | NULL | NO |  |
| 21 | `event_provider_template` | nvarchar(250) | NULL | NO |  |
| 22 | `event_signin_page_url` | nvarchar(550) | NULL | NO |  |
| 23 | `event_rep_page_url` | nvarchar(550) | NULL | NO |  |
| 24 | `event_dial_in` | nvarchar(250) | NULL | NO |  |
| 25 | `event_telecom` | nvarchar(250) | NULL | NO |  |
| 26 | `event_requested_by` | nvarchar(250) | NULL | NO |  |
| 27 | `event_private` | nvarchar(50) | NULL | NO |  |
| 28 | `event_project_id` | nvarchar(250) | NULL | NO |  |
| 29 | `test_event` | bit | NULL | NO |  |
| 30 | `enforce_capacity_limit` | bit | NULL | NO |  |
| 31 | `event_created_datetime` | datetime2 | NULL | NO |  |
| 32 | `event_other` | nvarchar(250) | NULL | NO |  |
| 33 | `event_description` | nvarchar(4000) | NULL | NO |  |
| 34 | `event_image_link` | nvarchar(250) | NULL | NO |  |
| 35 | `run_slides` | nvarchar(1000) | NULL | NO |  |
| 36 | `polls_WB` | bit | NULL | NO |  |
| 37 | `record_event` | bit | NULL | NO |  |
| 38 | `breakout_room` | bit | NULL | NO |  |
| 39 | `breakout_room_notes` | nvarchar(4000) | NULL | NO |  |
| 40 | `international_callers` | bit | NULL | NO |  |
| 41 | `special_events_calendar` | bit | NULL | NO |  |
| 42 | `cc_email_address` | nvarchar(250) | NULL | NO |  |
| 43 | `speaker_paid` | bit | NULL | NO |  |
| 44 | `cause_of_cancelation` | nvarchar(4000) | NULL | NO |  |
| 45 | `cancel_notes` | nvarchar(4000) | NULL | NO |  |
| 46 | `trigger_cancelation_emails_speakers` | bit | NULL | NO |  |
| 47 | `trigger_cancelation_emails_hcp` | bit | NULL | NO |  |
| 48 | `trigger_cancelation_emails_reps` | bit | NULL | NO |  |
| 49 | `trigger_cancelation_emails_other` | bit | NULL | NO |  |
| 50 | `actual_start_time` | datetime2 | NULL | NO |  |
| 51 | `actual_end_time` | datetime2 | NULL | NO |  |
| 52 | `adverse_event_mentioned` | bit | NULL | NO |  |
| 53 | `describe_adverse_events` | nvarchar(4000) | NULL | NO |  |
| 54 | `number_of_attendees_on_camera` | nvarchar(4000) | NULL | NO |  |
| 55 | `number_of_verbal_questions_asked` | nvarchar(4000) | NULL | NO |  |
| 58 | `items_to_note_for_chat_box_or_messages` | nvarchar(4000) | NULL | NO |  |
| 59 | `speaker_arrival_time` | nvarchar(250) | NULL | NO |  |
| 60 | `speaker_connected_to_audio_time` | nvarchar(250) | NULL | NO |  |
| 61 | `speaker_feedback` | nvarchar(250) | NULL | NO |  |
| 62 | `speaker_rating` | nvarchar(250) | NULL | NO |  |
| 63 | `speaker_issues` | nvarchar(4000) | NULL | NO |  |
| 64 | `speaker_issue_notes` | nvarchar(4000) | NULL | NO |  |
| 65 | `event_lead_joined_program` | bit | NULL | NO |  |
| 66 | `event_lead_connected_to_audio_time` | nvarchar(250) | NULL | NO |  |
| 67 | `names_of_compliance_officers_on_call` | nvarchar(4000) | NULL | NO |  |
| 68 | `help_needed_from_MNG_slack_support` | bit | NULL | NO |  |
| 69 | `compliance` | nvarchar(4000) | NULL | NO |  |
| 70 | `other_notes` | nvarchar(4000) | NULL | NO |  |
| 71 | `phone_only_attendees` | bit | NULL | NO |  |
| 72 | `phone_only_attendees_number_or_name_if_received` | nvarchar(4000) | NULL | NO |  |
| 73 | `number_of_chat_box_questions_content_only` | nvarchar(4000) | NULL | NO |  |
| 74 | `paste_content_related_questions` | nvarchar(4000) | NULL | NO |  |
| 75 | `event_issues` | nvarchar(4000) | NULL | NO |  |
| 76 | `event_issues_notes` | nvarchar(4000) | NULL | NO |  |
| 77 | `mng_platform_or_tech_issue` | nvarchar(4000) | NULL | NO |  |
| 78 | `event_lead_technical_issue` | nvarchar(4000) | NULL | NO |  |
| 79 | `event_lead_non_technical_issue` | nvarchar(4000) | NULL | NO |  |
| 80 | `post_program_report_complete` | bit | NULL | NO |  |
| 81 | `event_updated_datetime` | datetime2 | NULL | NO |  |
| 82 | `event_page_url` | nvarchar(500) | NULL | NO |  |
| 83 | `available_for_public_api` | bit | NULL | NO |  |
| 84 | `promo_activity_id` | nvarchar(max) | NULL | NO |  |
| 85 | `event_reference_number` | nvarchar(5) | NULL | NO |  |
| 86 | `promo_email_launch` | datetime | NULL | NO |  |
| 87 | `web_banner_go_live` | datetime | NULL | NO |  |
| 88 | `digital_on_demand_go_live` | datetime | NULL | NO |  |
| 89 | `event_created_date` | datetime | NULL | NO |  |
| 90 | `rep_requested_event_confirmed_date` | datetime | NULL | NO |  |
| 91 | `paste_all_event_chat_box_messages` | nvarchar(max) | NULL | NO |  |
| 92 | `paste_all_external_slack_chat_messages_non_content` | nvarchar(max) | NULL | NO |  |

### `site_events_country_block`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_event_id` | uniqueidentifier | NOT NULL | NO |  |
| 2 | `tenant_id` | uniqueidentifier | NULL | NO |  |
| 3 | `block_country_text` | nvarchar(100) | NULL | NO |  |
| 4 | `block_country_value` | nvarchar(100) | NULL | NO |  |
| 5 | `approved_country_text` | nvarchar(100) | NULL | NO |  |
| 6 | `approved_country_value` | nvarchar(100) | NULL | NO |  |

### `site_media_content`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `content_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `content_name` | nvarchar(1000) | NULL | NO |  |
| 4 | `content_type` | nvarchar(500) | NULL | NO |  |
| 5 | `content_duration` | nvarchar(500) | NULL | NO |  |
| 6 | `content_added_date` | datetime2 | NULL | NO |  |
| 7 | `content_expiration` | datetime2 | NULL | NO |  |
| 8 | `test_content` | bit | NULL | NO |  |
| 9 | `brightcove_video_id` | nvarchar(500) | NULL | NO |  |

### `site_media_content_account_activity`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `content_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `content_name` | nvarchar(1000) | NULL | NO |  |
| 4 | `content_type` | nvarchar(500) | NULL | NO |  |
| 5 | `content_duration` | nvarchar(500) | NULL | NO |  |
| 6 | `content_added_date` | datetime2 | NULL | NO |  |
| 7 | `content_expiration` | datetime2 | NULL | NO |  |
| 8 | `test_content` | bit | NULL | NO |  |
| 9 | `brightcove_video_id` | nvarchar(500) | NULL | NO |  |

### `site_module_resource`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_module_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_resource_id` | uniqueidentifier | NULL | NO |  |

### `site_project_codes`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 5 | `site_project_id` | nvarchar(4000) | NULL | NO |  |
| 6 | `meeting_count` | int | NULL | NO |  |
| 7 | `project_description` | nvarchar(4000) | NULL | NO |  |
| 8 | `target_audience_count` | int | NULL | NO |  |

### `site_speaker_affiliations`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `speaker_affiliation` | nvarchar(1000) | NULL | NO |  |

### `site_speaker_approved_topics`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `topic_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `site_speaker_certifications`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `certification_name` | nvarchar(4000) | NULL | NO |  |
| 3 | `certification_value` | nvarchar(4000) | NULL | NO |  |

### `site_speaker_degrees`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `speaker_degree` | nvarchar(1000) | NULL | NO |  |

### `site_speaker_specialties`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `speaker_specialty` | nvarchar(1000) | NULL | NO |  |

### `site_speakers`
- **Row count**: 550
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `speaker_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `client_hcp_id` | nvarchar(1000) | NULL | NO |  |
| 4 | `client_speaker_id` | nvarchar(1000) | NULL | NO |  |
| 5 | `speaker_first_name` | nvarchar(500) | NULL | NO |  |
| 6 | `speaker_middle_name` | nvarchar(500) | NULL | NO |  |
| 7 | `speaker_last_name` | nvarchar(500) | NULL | NO |  |
| 8 | `speaker_timezone` | nvarchar(1500) | NULL | NO |  |
| 9 | `speaker_city` | nvarchar(1000) | NULL | NO |  |
| 10 | `speaker_zip` | nvarchar(250) | NULL | NO |  |
| 11 | `speaker_state` | nvarchar(250) | NULL | NO |  |
| 12 | `speaker_title` | nvarchar(250) | NULL | NO |  |
| 13 | `speaker_email1` | nvarchar(250) | NULL | NO |  |
| 14 | `speaker_address1` | nvarchar(250) | NULL | NO |  |
| 15 | `speaker_mobile` | nvarchar(250) | NULL | NO |  |
| 16 | `speaker_active_for_events` | bit | NULL | NO |  |
| 17 | `test_speaker` | bit | NULL | NO |  |
| 18 | `speaker_email2` | nvarchar(550) | NULL | NO |  |
| 19 | `speaker_email3` | nvarchar(550) | NULL | NO |  |
| 20 | `speaker_address2` | nvarchar(1500) | NULL | NO |  |
| 21 | `speaker_phone_office` | nvarchar(250) | NULL | NO |  |
| 22 | `speaker_phone_other` | nvarchar(250) | NULL | NO |  |
| 23 | `speaker_admin_name` | nvarchar(550) | NULL | NO |  |
| 24 | `speaker_admin_email` | nvarchar(550) | NULL | NO |  |
| 26 | `speaker_uac_id` | nvarchar(500) | NULL | NO |  |
| 27 | `speaker_mng_target_id` | nvarchar(500) | NULL | NO |  |
| 28 | `speaker_image` | nvarchar(4000) | NULL | NO |  |
| 29 | `speaker_affiliations` | nvarchar(4000) | NULL | NO |  |
| 30 | `speaker_degree_text` | nvarchar(4000) | NULL | NO |  |

### `site_tags`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `tag` | nvarchar(2000) | NULL | NO |  |

### `site_team_members`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_item_id` | uniqueidentifier | NULL | NO |  |
| 3 | `first_name` | nvarchar(150) | NULL | NO |  |
| 4 | `last_name` | nvarchar(150) | NULL | NO |  |
| 5 | `email_address` | nvarchar(150) | NULL | NO |  |
| 6 | `phone` | nvarchar(150) | NULL | NO |  |
| 7 | `team` | nvarchar(10) | NULL | NO |  |

### `site_topic_details_specialities`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `topic_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `topic_speciality_id` | uniqueidentifier | NULL | NO |  |
| 4 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 5 | `updated_date` | datetime | NULL | NO | `(getdate())` |

### `site_topic_details_therapeutic_area`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `topic_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `therapeuticarea_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 4 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 5 | `updated_date` | datetime | NULL | NO | `(getdate())` |

### `site_topics`
- **Row count**: 550
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `topic_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `test_topic` | bit | NULL | NO |  |
| 4 | `topic_expiration_date` | nvarchar(250) | NULL | NO |  |
| 5 | `topic_title` | nvarchar(4000) | NULL | NO |  |
| 6 | `topic_client_code` | nvarchar(1000) | NULL | NO |  |
| 7 | `topic_brand` | nvarchar(1000) | NULL | NO |  |
| 8 | `topic_active_for_event` | bit | NULL | NO |  |
| 9 | `topic_active_for_speaker` | bit | NULL | NO |  |
| 10 | `topic_active_for_request` | bit | NULL | NO |  |
| 11 | `topic_approval_date` | nvarchar(250) | NULL | NO |  |
| 12 | `available_for_public_api` | bit | NULL | NO |  |
| 13 | `topic_specialty` | nvarchar(max) | NULL | NO |  |

### `site_view_only_registation_audit`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `session_id` | nvarchar(100) | NULL | NO |  |
| 2 | `site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `event_id` | uniqueidentifier | NULL | NO |  |
| 4 | `email_address` | nvarchar(255) | NULL | NO |  |
| 5 | `registration_id` | uniqueidentifier | NULL | NO |  |
| 6 | `enter_timestamp` | datetime | NULL | NO |  |
| 7 | `exit_timestamp` | datetime | NULL | NO |  |

### `sitecore_campaign_details`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_campaign_id` | uniqueidentifier | NULL | NO |  |
| 2 | `campaign_name` | nvarchar(4000) | NULL | NO |  |
| 3 | `campaign_description` | nvarchar(max) | NULL | NO |  |
| 4 | `campaign_startdate` | datetime2 | NULL | NO |  |
| 5 | `campaign_enddate` | datetime2 | NULL | NO |  |
| 6 | `campaign_status` | bit | NULL | NO |  |

### `table_group`
- **Row count**: 24
- **Primary Key**: None (None)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | YES |  |
| 2 | `group_id` | int | NULL | NO |  |
| 3 | `group_name` | nvarchar(1000) | NULL | NO |  |
| 4 | `table_name` | nvarchar(250) | NULL | NO |  |

### `table_load_settings`
- **Row count**: 1
- **Primary Key**: PK__table_lo__3213E83F9DC2E4F6 (id)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | YES |  |
| 2 | `table_name` | nvarchar(250) | NULL | NO |  |
| 3 | `table_load_status` | nvarchar(20) | NULL | NO |  |
| 5 | `tables_stats` | nvarchar(max) | NULL | NO |  |
| 6 | `table_load_start_date` | datetime2 | NULL | NO |  |
| 7 | `table_load_end_date` | datetime2 | NULL | NO |  |
| 8 | `table_load_hour` | int | NULL | NO | `((24))` |
| 9 | `last_count` | int | NULL | NO |  |
| 10 | `current_count` | int | NULL | NO |  |

### `user_account_content_shares`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 4 | `shared_datetime` | datetime | NULL | NO |  |
| 5 | `campaign_manager_id` | int | NULL | NO |  |
| 6 | `group_id` | uniqueidentifier | NULL | NO |  |
| 7 | `content_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `user_account_event_email_invites`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `event_id` | uniqueidentifier | NULL | NO |  |
| 4 | `speaker` | uniqueidentifier | NULL | NO |  |
| 5 | `topic` | uniqueidentifier | NULL | NO |  |
| 6 | `campaign_manager_id` | int | NULL | NO |  |
| 7 | `group_id` | uniqueidentifier | NULL | NO |  |
| 8 | `invited_datetime` | datetime | NULL | NO |  |

### `user_account_event_requests`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `primary_speaker` | uniqueidentifier | NULL | NO |  |
| 4 | `secondary_speaker` | uniqueidentifier | NULL | NO |  |
| 5 | `topic` | uniqueidentifier | NULL | NO |  |
| 6 | `event_date` | datetime | NULL | NO |  |
| 7 | `event_time` | nvarchar(100) | NULL | NO |  |
| 8 | `time_zone` | nvarchar(250) | NULL | NO |  |
| 9 | `event_id` | uniqueidentifier | NULL | NO |  |

### `user_account_logins`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 2 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 3 | `login_datetime` | datetime | NULL | NO |  |

### `user_account_pdf_invite_downloads`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `pdf_filename` | nvarchar(500) | NULL | NO |  |
| 4 | `download_datetime` | datetime | NULL | NO |  |
| 5 | `event_sitecore_id` | uniqueidentifier | NULL | NO |  |

### `user_account_session_audit`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `account_sitecore_id` | uniqueidentifier | NOT NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `session_start_date` | datetime | NULL | NO |  |
| 4 | `session_end_date` | datetime | NULL | NO |  |
| 5 | `browser_closing_date` | datetime | NULL | NO |  |

### `user_accounts`
- **Row count**: 550
- **Primary Key**: None (None)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | YES |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 4 | `account_type` | nvarchar(150) | NULL | NO |  |
| 5 | `account_name` | nvarchar(250) | NULL | NO |  |
| 6 | `account_degree` | nvarchar(250) | NULL | NO |  |
| 7 | `account_phone1` | nvarchar(150) | NULL | NO |  |
| 8 | `account_address1` | nvarchar(250) | NULL | NO |  |
| 9 | `account_address2` | nvarchar(250) | NULL | NO |  |
| 10 | `account_city` | nvarchar(150) | NULL | NO |  |
| 11 | `account_state` | nvarchar(150) | NULL | NO |  |
| 12 | `account_zip` | nvarchar(100) | NULL | NO |  |
| 13 | `account_timezone` | nvarchar(150) | NULL | NO |  |
| 14 | `account_status` | nvarchar(150) | NULL | NO |  |
| 16 | `account_client_id` | nvarchar(150) | NULL | NO |  |
| 17 | `account_territory_name` | nvarchar(250) | NULL | NO |  |
| 18 | `account_territory_id` | nvarchar(150) | NULL | NO |  |
| 19 | `account_affiliations` | nvarchar(150) | NULL | NO |  |
| 20 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 21 | `updated_date` | datetime | NULL | NO | `(getdate())` |
| 22 | `account_email` | nvarchar(1000) | NULL | NO |  |
| 23 | `account_medical_credentials` | nvarchar(4000) | NULL | NO |  |
| 24 | `account_entered_mobile_number` | nvarchar(250) | NULL | NO |  |
| 25 | `account_language` | nvarchar(250) | NULL | NO |  |
| 27 | `test_account` | bit | NULL | NO |  |
| 28 | `account_text_reminders` | bit | NULL | NO |  |
| 29 | `account_client_rep_id` | nvarchar(150) | NULL | NO |  |
| 30 | `account_firstname` | nvarchar(500) | NULL | NO |  |
| 31 | `account_lastname` | nvarchar(500) | NULL | NO |  |

### `user_accounts_activity_report`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `account_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 4 | `account_type` | nvarchar(150) | NULL | NO |  |
| 5 | `account_name` | nvarchar(250) | NULL | NO |  |
| 6 | `account_degree` | nvarchar(250) | NULL | NO |  |
| 7 | `account_phone1` | nvarchar(150) | NULL | NO |  |
| 8 | `account_address1` | nvarchar(250) | NULL | NO |  |
| 9 | `account_address2` | nvarchar(250) | NULL | NO |  |
| 10 | `account_city` | nvarchar(150) | NULL | NO |  |
| 11 | `account_state` | nvarchar(150) | NULL | NO |  |
| 12 | `account_zip` | nvarchar(100) | NULL | NO |  |
| 13 | `account_timezone` | nvarchar(150) | NULL | NO |  |
| 14 | `account_status` | nvarchar(150) | NULL | NO |  |
| 15 | `account_client_id` | nvarchar(150) | NULL | NO |  |
| 16 | `account_territory_name` | nvarchar(250) | NULL | NO |  |
| 17 | `account_territory_id` | nvarchar(150) | NULL | NO |  |
| 18 | `account_affiliations` | nvarchar(150) | NULL | NO |  |
| 19 | `created_date` | datetime | NULL | NO |  |
| 20 | `updated_date` | datetime | NULL | NO |  |
| 21 | `account_email` | nvarchar(1000) | NULL | NO |  |
| 22 | `account_medical_credentials` | nvarchar(4000) | NULL | NO |  |
| 23 | `account_entered_mobile_number` | nvarchar(250) | NULL | NO |  |
| 24 | `account_language` | nvarchar(250) | NULL | NO |  |
| 25 | `test_account` | bit | NULL | NO |  |
| 26 | `account_text_reminders` | bit | NULL | NO |  |
| 27 | `account_client_rep_id` | nvarchar(150) | NULL | NO |  |

### `visitor_session`
- **Row count**: 400
- **Primary Key**: None (None)
- **Identity Column**: `id`

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | YES |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `visitor_session_id` | nvarchar(max) | NULL | NO |  |
| 4 | `visitor_email_recipient_id` | uniqueidentifier | NULL | NO |  |
| 5 | `visitor_mng_target_id` | nvarchar(max) | NULL | NO |  |
| 6 | `visitor_start_date` | datetime | NULL | NO |  |
| 7 | `visitor_end_date` | datetime | NULL | NO |  |
| 8 | `visitor_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 9 | `visitor_sitecore_resource_id` | uniqueidentifier | NULL | NO |  |
| 10 | `visitor_campaign_id` | nvarchar(max) | NULL | NO |  |
| 11 | `visitor_npi` | nvarchar(max) | NULL | NO |  |
| 12 | `visitor_invited_by_email` | nvarchar(max) | NULL | NO |  |
| 13 | `visitor_uac_id` | nvarchar(max) | NULL | NO |  |
| 14 | `visitor_origin` | nvarchar(max) | NULL | NO |  |
| 15 | `visitor_referral_link` | nvarchar(max) | NULL | NO |  |
| 16 | `visitor_page_views` | int | NULL | NO |  |
| 17 | `created_date` | datetime | NULL | NO | `(getdate())` |
| 18 | `updated_date` | datetime | NULL | NO | `(getdate())` |
| 19 | `content_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 20 | `resource_downloaded` | bit | NULL | NO |  |
| 21 | `sitecore_page_id` | uniqueidentifier | NULL | NO |  |
| 22 | `rep_email` | nvarchar(max) | NULL | NO |  |
| 23 | `visitor_origin_description` | nvarchar(2000) | NULL | NO |  |

### `visitor_session_analytics_report`
- **Row count**: 400
- **Primary Key**: None (None)

| Col # | Column Name | SQL Server Type | Nullable | Identity | Default |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | `id` | int | NOT NULL | NO |  |
| 2 | `sitecore_site_id` | uniqueidentifier | NULL | NO |  |
| 3 | `visitor_session_id` | nvarchar(max) | NULL | NO |  |
| 4 | `visitor_email_recipient_id` | uniqueidentifier | NULL | NO |  |
| 5 | `visitor_mng_target_id` | nvarchar(max) | NULL | NO |  |
| 6 | `visitor_start_date` | datetime | NULL | NO |  |
| 7 | `visitor_end_date` | datetime | NULL | NO |  |
| 8 | `visitor_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 9 | `visitor_sitecore_resource_id` | uniqueidentifier | NULL | NO |  |
| 10 | `visitor_campaign_id` | nvarchar(max) | NULL | NO |  |
| 11 | `visitor_npi` | nvarchar(max) | NULL | NO |  |
| 12 | `visitor_invited_by_email` | nvarchar(max) | NULL | NO |  |
| 13 | `visitor_uac_id` | nvarchar(max) | NULL | NO |  |
| 14 | `visitor_origin` | nvarchar(max) | NULL | NO |  |
| 15 | `visitor_referral_link` | nvarchar(max) | NULL | NO |  |
| 16 | `visitor_page_views` | int | NULL | NO |  |
| 17 | `created_date` | datetime | NULL | NO |  |
| 18 | `updated_date` | datetime | NULL | NO |  |
| 19 | `content_sitecore_id` | uniqueidentifier | NULL | NO |  |
| 20 | `resource_downloaded` | bit | NULL | NO |  |
| 21 | `sitecore_page_id` | uniqueidentifier | NULL | NO |  |
| 22 | `rep_email` | nvarchar(max) | NULL | NO |  |
| 23 | `visitor_origin_description` | nvarchar(2000) | NULL | NO |  |
