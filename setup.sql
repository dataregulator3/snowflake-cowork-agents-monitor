-- =============================================================================
-- Setup for the CoWork Agents Monitor (Streamlit container runtime)
--
-- 1. Replace the placeholders:
--      <APP_DATABASE>.<APP_SCHEMA>   where the Streamlit app will live
--      <APP_WAREHOUSE>               warehouse that runs the app's queries
--      <YOUR_USER>                   user who deploys the app
-- 2. Run the whole script as ACCOUNTADMIN.
-- 3. Optional blocks at the end: uncomment what you need.
-- =============================================================================

USE ROLE ACCOUNTADMIN;

-- -----------------------------------------------------------------------------
-- Role that owns and runs the app
-- -----------------------------------------------------------------------------
CREATE ROLE IF NOT EXISTS AGENTS_MONITOR_ROLE;
GRANT ROLE AGENTS_MONITOR_ROLE TO USER <YOUR_USER>;

-- Read access to SNOWFLAKE.ACCOUNT_USAGE
-- (SNOWFLAKE_COWORK_USAGE_HISTORY, CORTEX_AGENT_USAGE_HISTORY, WAREHOUSE_METERING_HISTORY)
GRANT DATABASE ROLE SNOWFLAKE.USAGE_VIEWER TO ROLE AGENTS_MONITOR_ROLE;

-- Warehouse for the app's queries
GRANT USAGE ON WAREHOUSE <APP_WAREHOUSE> TO ROLE AGENTS_MONITOR_ROLE;

-- Compute pool for the container runtime (SYSTEM_COMPUTE_POOL_CPU exists by default)
GRANT USAGE ON COMPUTE POOL SYSTEM_COMPUTE_POOL_CPU TO ROLE AGENTS_MONITOR_ROLE;

-- -----------------------------------------------------------------------------
-- Location of the Streamlit app
-- -----------------------------------------------------------------------------
CREATE DATABASE IF NOT EXISTS <APP_DATABASE>;
CREATE SCHEMA IF NOT EXISTS <APP_DATABASE>.<APP_SCHEMA>;
GRANT USAGE ON DATABASE <APP_DATABASE> TO ROLE AGENTS_MONITOR_ROLE;
GRANT USAGE ON SCHEMA <APP_DATABASE>.<APP_SCHEMA> TO ROLE AGENTS_MONITOR_ROLE;
GRANT CREATE STREAMLIT ON SCHEMA <APP_DATABASE>.<APP_SCHEMA> TO ROLE AGENTS_MONITOR_ROLE;

-- -----------------------------------------------------------------------------
-- PyPI access, so the container runtime can install the dependencies from pyproject.toml.
-- Skip this block if your account already has an integration for PyPI, and put
-- its name into snowflake.yml (external_access_integrations).
-- -----------------------------------------------------------------------------
CREATE NETWORK RULE IF NOT EXISTS <APP_DATABASE>.<APP_SCHEMA>.PYPI_NETWORK_RULE
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('pypi.org', 'pypi.python.org', 'pythonhosted.org', 'files.pythonhosted.org');

CREATE EXTERNAL ACCESS INTEGRATION IF NOT EXISTS PYPI_ACCESS_INTEGRATION
  ALLOWED_NETWORK_RULES = (<APP_DATABASE>.<APP_SCHEMA>.PYPI_NETWORK_RULE)
  ENABLED = TRUE;

GRANT USAGE ON INTEGRATION PYPI_ACCESS_INTEGRATION TO ROLE AGENTS_MONITOR_ROLE;

-- =============================================================================
-- Optional
-- =============================================================================

-- Show AUTO_SUSPEND on the "Cost & compute" page.
-- Use the warehouse(s) you listed in config.AGENT_WAREHOUSES.
-- GRANT MONITOR ON WAREHOUSE <AGENT_WAREHOUSE> TO ROLE AGENTS_MONITOR_ROLE;

-- Real credit prices from SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY.
-- Only available in an account with ORGADMIN enabled (or the organization account)
-- and not for contracts signed through a reseller. Without it, the app uses the
-- FALLBACK_* prices from config.py.
-- GRANT DATABASE ROLE SNOWFLAKE.ORGANIZATION_BILLING_VIEWER TO ROLE AGENTS_MONITOR_ROLE;

-- Let other roles open the app (run after the first deploy):
-- GRANT USAGE ON DATABASE <APP_DATABASE> TO ROLE <VIEWER_ROLE>;
-- GRANT USAGE ON SCHEMA <APP_DATABASE>.<APP_SCHEMA> TO ROLE <VIEWER_ROLE>;
-- GRANT USAGE ON STREAMLIT <APP_DATABASE>.<APP_SCHEMA>.COWORK_AGENTS_MONITOR TO ROLE <VIEWER_ROLE>;
