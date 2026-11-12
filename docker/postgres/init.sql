-- Creates the app role without a password. Set it with set-app-password.sh, never in this file.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'api_app') THEN
    CREATE ROLE api_app LOGIN;
  END IF;
END
$$;
GRANT USAGE ON SCHEMA public TO api_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO api_app;

-- The job queue uses sequences, so let the app role advance them too.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO api_app;
