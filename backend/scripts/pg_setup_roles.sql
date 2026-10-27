-- SuperPlanner least-privilege PostgreSQL setup (docs/DEPLOY.md "Database roles").
--
-- Creates (idempotently) two LOGIN roles and the database:
--   :owner  owns the database and the public schema; runs the migrations (MIGRATION_DATABASE_URL). No superuser.
--   :app    the API / worker role (DATABASE_URL): CONNECT + TEMPORARY, USAGE on schema public, and only
--           SELECT/INSERT/UPDATE/DELETE on tables and USAGE/SELECT/UPDATE on sequences - no DDL, no TRUNCATE.
-- Default privileges make every table/sequence the owner creates later (each migration) usable by :app.
--
-- Run as a superuser (or a role with CREATEROLE and CREATEDB) against the maintenance database:
--   psql -h HOST -U postgres -d postgres -v ON_ERROR_STOP=1 \
--        -v db=superplanner -v owner=superplanner_owner -v owner_password='...' \
--        -v app=superplanner_app -v app_password='...' -f backend/scripts/pg_setup_roles.sql
-- or use the wrapper backend/scripts/pg_setup_roles.sh (reads the passwords from the environment).
-- Re-running it is safe: it resets the passwords and re-applies the grants.

\set ON_ERROR_STOP on

SELECT format('CREATE ROLE %I LOGIN', :'owner') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'owner')
\gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD %L',
              :'owner', :'owner_password')
\gexec
SELECT format('CREATE ROLE %I LOGIN', :'app') WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'app')
\gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD %L',
              :'app', :'app_password')
\gexec

-- The owner role must be grantable by the current (non-superuser CREATEROLE) user on PostgreSQL 16+.
SELECT format('GRANT %I TO CURRENT_USER', :'owner')
 WHERE NOT pg_has_role(current_user, :'owner', 'MEMBER')
   AND NOT (SELECT rolsuper FROM pg_roles WHERE rolname = current_user)
\gexec

SELECT format('CREATE DATABASE %I OWNER %I ENCODING ''UTF8'' TEMPLATE template0', :'db', :'owner')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'db')
\gexec
SELECT format('ALTER DATABASE %I OWNER TO %I', :'db', :'owner')
\gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', :'db')
\gexec
SELECT format('GRANT CONNECT, TEMPORARY ON DATABASE %I TO %I', :'db', :'app')
\gexec

\connect :"db"

-- Nobody but the owner may create objects in the schema (PostgreSQL < 15 grants CREATE to PUBLIC by default).
ALTER SCHEMA public OWNER TO :"owner";
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO :"app";

-- Existing objects (re-run after a restore or on an already migrated database) ...
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO :"app";
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO :"app";
-- ... and every object the owner creates from now on (migrations).
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO :"app";
ALTER DEFAULT PRIVILEGES FOR ROLE :"owner" IN SCHEMA public
  GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO :"app";
