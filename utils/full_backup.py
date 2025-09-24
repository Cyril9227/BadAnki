
# utils/full_backup.py
import os
import subprocess
from urllib.parse import urlparse
import datetime
from dotenv import load_dotenv

load_dotenv()

def run_pg_dump():
    """
    Executes the pg_dump command to back up the entire PostgreSQL database.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable not set.")
        return

    try:
        parsed_url = urlparse(database_url)
        db_name = parsed_url.path.lstrip('/')
        user = parsed_url.username
        password = parsed_url.password
        host = parsed_url.hostname
        port = parsed_url.port

        # Create a timestamp for the backup file
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"backup_{db_name}_{timestamp}.sql"

        # Construct the pg_dump command
        command = [
            "pg_dump",
            "--dbname", db_name,
            "--username", user,
            "--host", host,
            "--port", str(port),
            "--file", backup_file,
            "--format", "c",  # Use custom format for pg_restore
            "--no-owner",
            "--no-acl"
        ]

        # Set the password as an environment variable for the subprocess
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        print(f"Starting backup of database '{db_name}' to '{backup_file}'...")

        # Execute the command
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            print("Backup completed successfully.")
            print(f"Backup file: {backup_file}")
        else:
            print("Error during backup:")
            print(stderr.decode())

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    run_pg_dump()
