"""One-time PostgreSQL setup for salt_portal. Run: python setup_postgres.py"""
import getpass
import sys

import psycopg2

DB_NAME = "salt_portal"
APP_USER = "salt_user"
APP_PASSWORD = "ChooseAStrongpassword"

GRANTS = """
GRANT CONNECT ON DATABASE salt_portal TO salt_user;
GRANT ALL ON SCHEMA public TO salt_user;
GRANT CREATE ON SCHEMA public TO salt_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO salt_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO salt_user;
"""


def main():
    print("PostgreSQL setup for salt_portal")
    print("Enter the postgres superuser password (set when PostgreSQL was installed).")
    postgres_password = getpass.getpass("postgres password: ")

    try:
        conn = psycopg2.connect(
            host="localhost",
            database=DB_NAME,
            user="postgres",
            password=postgres_password,
        )
    except psycopg2.Error as exc:
        print(f"\nCould not connect as postgres: {exc}")
        print("Check the password, or run the SQL in pgAdmin manually.")
        sys.exit(1)

    conn.autocommit = True
    cur = conn.cursor()

    for statement in GRANTS.strip().split(";"):
        statement = statement.strip()
        if statement:
            cur.execute(statement)

    cur.close()
    conn.close()

    try:
        test = psycopg2.connect(
            host="localhost",
            database=DB_NAME,
            user=APP_USER,
            password=APP_PASSWORD,
        )
        test.autocommit = True
        tcur = test.cursor()
        tcur.execute("CREATE TABLE IF NOT EXISTS _setup_test (id SERIAL PRIMARY KEY)")
        tcur.execute("DROP TABLE IF EXISTS _setup_test")
        tcur.close()
        test.close()
    except psycopg2.Error as exc:
        print(f"\nGrants applied, but salt_user still cannot create tables: {exc}")
        sys.exit(1)

    print("\nDone. salt_user can now create tables.")
    print("Start the app with: python app.py")


if __name__ == "__main__":
    main()
