-- =============================================================================
-- CoWork Agents Monitor: scheduled usage report by email
--
-- Sends an HTML email with AI credits, estimated cost, requests and users
-- per agent: totals since the first request, today's usage per agent and user,
-- and totals per agent and user. Links to the Streamlit app.
--
-- 1. Replace the placeholders:
--      <APP_DATABASE>.<APP_SCHEMA>   where the task will live (same as the app)
--      <APP_WAREHOUSE>               warehouse that runs the task
--      <RECIPIENT_EMAIL>             who receives the report (must be a verified email
--                                    of a user in this account)
--      <APP_URL>                     URL of the Streamlit app (printed by snow streamlit deploy)
-- 2. Optional: adjust schedule, fallback price and currency below.
-- 3. Run the whole script as ACCOUNTADMIN in a Snowsight worksheet.
--
-- The task runs as AGENTS_MONITOR_ROLE (created by setup.sql).
--
-- Updating an existing task:
--   CREATE TASK IF NOT EXISTS below does not change a task that already exists,
--   so rerunning this script keeps the task and its run history.
--   Don't use CREATE OR REPLACE: it creates a new task object, and the run history
--   in Snowsight starts from zero (old runs stay only in ACCOUNT_USAGE.TASK_HISTORY).
--   To change an existing task instead:
--     ALTER TASK <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT SUSPEND;
--     ALTER TASK <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT SET SCHEDULE = '...';
--     ALTER TASK <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT MODIFY AS <everything after AS below>;
--     ALTER TASK <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT RESUME;
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- -----------------------------------------------------------------------------
-- Email integration. Skip if you already have one and use its name below.
-- -----------------------------------------------------------------------------
CREATE NOTIFICATION INTEGRATION IF NOT EXISTS AGENTS_MONITOR_EMAIL
  TYPE = EMAIL
  ENABLED = TRUE
  ALLOWED_RECIPIENTS = ('<RECIPIENT_EMAIL>');

GRANT USAGE ON INTEGRATION AGENTS_MONITOR_EMAIL TO ROLE AGENTS_MONITOR_ROLE;
GRANT CREATE TASK, CREATE TABLE ON SCHEMA <APP_DATABASE>.<APP_SCHEMA> TO ROLE AGENTS_MONITOR_ROLE;
GRANT EXECUTE TASK ON ACCOUNT TO ROLE AGENTS_MONITOR_ROLE;

-- -----------------------------------------------------------------------------
-- Report task
-- -----------------------------------------------------------------------------
USE ROLE AGENTS_MONITOR_ROLE;

CREATE TASK IF NOT EXISTS <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT
  WAREHOUSE = <APP_WAREHOUSE>
  -- Weekdays at 12:00 and 18:00. Adjust the cron expression and time zone as needed.
  SCHEDULE = 'USING CRON 0 12,18 * * 1-5 UTC'
  COMMENT = 'CoWork Agents Monitor: usage report email for all agents in the account'
AS
DECLARE
  -- Price per AI credit if ORGANIZATION_USAGE.RATE_SHEET_DAILY is not accessible
  fallback_rate FLOAT DEFAULT 2.00;
  currency VARCHAR DEFAULT '$';
  -- Optional second currency, e.g. '&euro;' and 0.92. Leave fx_rate at 0 to disable.
  fx_symbol VARCHAR DEFAULT '';
  fx_rate FLOAT DEFAULT 0;

  rate FLOAT;
  rate_source VARCHAR DEFAULT 'fallback';
  total_credits FLOAT;
  total_requests NUMBER;
  unique_users NUMBER;
  num_agents NUMBER;
  agent_table VARCHAR;
  today_table VARCHAR;
  user_table VARCHAR;
  fx_header VARCHAR DEFAULT '';
  email_body VARCHAR;
  email_subject VARCHAR;
BEGIN
  -- Real price per AI credit from the rate sheet, if the role can read it
  BEGIN
    SELECT MAX_BY(EFFECTIVE_RATE, DATE) INTO :rate
    FROM SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY
    WHERE SERVICE_TYPE = 'SNOWFLAKE_COWORK'
      AND ACCOUNT_LOCATOR = CURRENT_ACCOUNT()
      AND DATE >= DATEADD(day, -60, CURRENT_DATE());
  EXCEPTION
    WHEN OTHER THEN
      rate := NULL;
  END;
  IF (rate IS NULL) THEN
    rate := fallback_rate;
  ELSE
    rate_source := 'rate sheet';
  END IF;

  -- CoWork chats and direct Cortex Agent API calls; REQUEST_IDs don't overlap
  CREATE OR REPLACE TEMPORARY TABLE agent_usage AS
    SELECT START_TIME, USER_NAME, REQUEST_ID, AGENT_NAME, TOKEN_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.SNOWFLAKE_COWORK_USAGE_HISTORY
    WHERE AGENT_NAME IS NOT NULL AND AGENT_NAME != ''
    UNION ALL
    SELECT START_TIME, USER_NAME, REQUEST_ID, AGENT_NAME, TOKEN_CREDITS
    FROM SNOWFLAKE.ACCOUNT_USAGE.CORTEX_AGENT_USAGE_HISTORY
    WHERE AGENT_NAME IS NOT NULL AND AGENT_NAME != '';

  SELECT
      COALESCE(SUM(TOKEN_CREDITS), 0),
      COUNT(DISTINCT REQUEST_ID),
      COUNT(DISTINCT USER_NAME),
      COUNT(DISTINCT AGENT_NAME)
  INTO :total_credits, :total_requests, :unique_users, :num_agents
  FROM agent_usage;

  IF (fx_rate > 0) THEN
    fx_header := '<th>' || fx_symbol || '</th>';
  END IF;

  -- Totals per agent
  SELECT COALESCE(LISTAGG(row_html, '') WITHIN GROUP (ORDER BY credits DESC), '')
  INTO :agent_table
  FROM (
    SELECT
      SUM(TOKEN_CREDITS) AS credits,
      '<tr><td>' || AGENT_NAME || '</td>'
      || '<td style="text-align:right">' || ROUND(SUM(TOKEN_CREDITS), 2)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || :currency || ROUND(SUM(TOKEN_CREDITS) * :rate, 2)::VARCHAR || '</td>'
      || IFF(:fx_rate > 0, '<td style="text-align:right">' || :fx_symbol || ROUND(SUM(TOKEN_CREDITS) * :rate * :fx_rate, 2)::VARCHAR || '</td>', '')
      || '<td style="text-align:right">' || COUNT(DISTINCT REQUEST_ID)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || COUNT(DISTINCT USER_NAME)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || TO_VARCHAR(MIN(START_TIME), 'YYYY-MM-DD') || '</td>'
      || '<td style="text-align:right">' || TO_VARCHAR(MAX(START_TIME), 'YYYY-MM-DD') || '</td></tr>' AS row_html
    FROM agent_usage
    GROUP BY AGENT_NAME
  );

  -- Today per agent and user
  SELECT COALESCE(LISTAGG(row_html, '') WITHIN GROUP (ORDER BY agent_name ASC, credits DESC), '')
  INTO :today_table
  FROM (
    SELECT
      AGENT_NAME AS agent_name,
      SUM(TOKEN_CREDITS) AS credits,
      '<tr><td>' || AGENT_NAME || '</td>'
      || '<td>' || USER_NAME || '</td>'
      || '<td style="text-align:right">' || ROUND(SUM(TOKEN_CREDITS), 2)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || :currency || ROUND(SUM(TOKEN_CREDITS) * :rate, 2)::VARCHAR || '</td>'
      || IFF(:fx_rate > 0, '<td style="text-align:right">' || :fx_symbol || ROUND(SUM(TOKEN_CREDITS) * :rate * :fx_rate, 2)::VARCHAR || '</td>', '')
      || '<td style="text-align:right">' || COUNT(DISTINCT REQUEST_ID)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || TO_VARCHAR(MIN(START_TIME), 'HH24:MI') || '</td>'
      || '<td style="text-align:right">' || TO_VARCHAR(MAX(START_TIME), 'HH24:MI') || '</td></tr>' AS row_html
    FROM agent_usage
    WHERE DATE(START_TIME) = CURRENT_DATE()
    GROUP BY AGENT_NAME, USER_NAME
  );

  -- Totals per agent and user
  SELECT COALESCE(LISTAGG(row_html, '') WITHIN GROUP (ORDER BY agent_name ASC, credits DESC), '')
  INTO :user_table
  FROM (
    SELECT
      AGENT_NAME AS agent_name,
      SUM(TOKEN_CREDITS) AS credits,
      '<tr><td>' || AGENT_NAME || '</td>'
      || '<td>' || USER_NAME || '</td>'
      || '<td style="text-align:right">' || ROUND(SUM(TOKEN_CREDITS), 2)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || :currency || ROUND(SUM(TOKEN_CREDITS) * :rate, 2)::VARCHAR || '</td>'
      || IFF(:fx_rate > 0, '<td style="text-align:right">' || :fx_symbol || ROUND(SUM(TOKEN_CREDITS) * :rate * :fx_rate, 2)::VARCHAR || '</td>', '')
      || '<td style="text-align:right">' || COUNT(DISTINCT REQUEST_ID)::VARCHAR || '</td>'
      || '<td style="text-align:right">' || TO_VARCHAR(MIN(START_TIME), 'YYYY-MM-DD HH24:MI') || '</td>'
      || '<td style="text-align:right">' || TO_VARCHAR(MAX(START_TIME), 'YYYY-MM-DD HH24:MI') || '</td></tr>' AS row_html
    FROM agent_usage
    GROUP BY AGENT_NAME, USER_NAME
  );

  email_body := '<!DOCTYPE html><html><head><style>'
    || 'body{font-family:Arial,sans-serif;color:#333;}'
    || 'h2{color:#11567F;}'
    || 'h3{color:#11567F;margin-top:24px;}'
    || 'table{border-collapse:collapse;width:100%;margin-top:12px;}'
    || 'th,td{border:1px solid #ddd;padding:8px;font-size:13px;}'
    || 'th{background-color:#29B5E8;color:white;}'
    || '.metric{display:inline-block;margin:0 20px 10px 0;text-align:center;}'
    || '.metric-value{font-size:24px;font-weight:bold;color:#11567F;}'
    || '.metric-label{font-size:12px;color:#666;}'
    || '.today-box{background:#f0f9ff;border:1px solid #29B5E8;border-radius:8px;padding:16px;margin:16px 0;}'
    || '</style></head><body>'
    || '<h2>CoWork Agents Usage Report</h2>'
    || '<p>As of ' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI') || ' | AI credit: ' || currency || TO_VARCHAR(rate, 'FM999990.00')
    || ' (' || rate_source || ') | Agents: ' || num_agents::VARCHAR || '</p>'
    || '<div>'
    || '<div class="metric"><div class="metric-value">' || ROUND(total_credits, 2)::VARCHAR || '</div><div class="metric-label">AI credits</div></div>'
    || '<div class="metric"><div class="metric-value">' || currency || ROUND(total_credits * rate, 2)::VARCHAR || '</div><div class="metric-label">Est. cost</div></div>'
    || IFF(fx_rate > 0, '<div class="metric"><div class="metric-value">' || fx_symbol || ROUND(total_credits * rate * fx_rate, 2)::VARCHAR || '</div><div class="metric-label">Est. cost</div></div>', '')
    || '<div class="metric"><div class="metric-value">' || total_requests::VARCHAR || '</div><div class="metric-label">Requests</div></div>'
    || '<div class="metric"><div class="metric-value">' || unique_users::VARCHAR || '</div><div class="metric-label">Users</div></div>'
    || '</div>';

  email_body := email_body
    || '<h3>Usage by agent (all time)</h3>'
    || '<table><tr><th>Agent</th><th>AI credits</th><th>' || currency || '</th>' || fx_header
    || '<th>Requests</th><th>Users</th><th>First use</th><th>Last use</th></tr>'
    || agent_table
    || '</table>';

  email_body := email_body
    || '<div class="today-box">'
    || '<h3 style="margin-top:0;">Today (' || TO_VARCHAR(CURRENT_DATE(), 'YYYY-MM-DD') || ')</h3>';

  IF (today_table != '') THEN
    email_body := email_body
      || '<table><tr><th>Agent</th><th>User</th><th>AI credits</th><th>' || currency || '</th>' || fx_header
      || '<th>Requests</th><th>First</th><th>Last</th></tr>'
      || today_table
      || '</table>';
  ELSE
    email_body := email_body || '<p style="color:#666;">No usage yet today.</p>';
  END IF;

  email_body := email_body || '</div>';

  email_body := email_body
    || '<h3>Usage by agent and user (all time)</h3>'
    || '<table><tr><th>Agent</th><th>User</th><th>AI credits</th><th>' || currency || '</th>' || fx_header
    || '<th>Requests</th><th>First use</th><th>Last use</th></tr>'
    || user_table
    || '</table>'
    || '<p style="margin-top:20px;font-size:11px;color:#999;">Sent by the CoWork Agents Monitor. '
    || 'Usage data can lag by a few hours.<br>'
    || '<a href="<APP_URL>">Open dashboard</a></p>'
    || '</body></html>';

  email_subject := 'CoWork Agents Usage Report - ' || TO_VARCHAR(CURRENT_TIMESTAMP(), 'YYYY-MM-DD HH24:MI');

  CALL SYSTEM$SEND_EMAIL(
    'AGENTS_MONITOR_EMAIL',
    '<RECIPIENT_EMAIL>',
    :email_subject,
    :email_body,
    'text/html'
  );
END;

-- Send one report right away to check that it works
EXECUTE TASK <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT;

-- Start the schedule
ALTER TASK <APP_DATABASE>.<APP_SCHEMA>.T_AGENT_USAGE_REPORT RESUME;
