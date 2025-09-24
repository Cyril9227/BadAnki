
# utils/full_restore.py
import os
import subprocess
from urllib.parse import urlparse
import argparse
from dotenv import load_dotenv

load_dotenv()

def run_pg_restore(backup_file):
    """
    Executes the pg_restore command to restore the database from a backup file.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("Error: DATABASE_URL environment variable not set.")
        return

    if not os.path.exists(backup_file):
        print(f"Error: Backup file '{backup_file}' not found.")
        return

    try:
        parsed_url = urlparse(database_url)
        db_name = parsed_url.path.lstrip('/')
        user = parsed_url.username
        password = parsed_url.password
        host = parsed_url.hostname
        port = parsed_url.port

        # Construct the pg_restore command
        command = [
            "pg_restore",
            "--dbname", db_name,
            "--username", user,
            "--host", host,
            "--port", str(port),
            "--clean",  # Drop database objects before recreating them
            "--if-exists",
            "--no-owner",
            "--no-acl",
            backup_file
        ]

        # Set the password as an environment variable for the subprocess
        env = os.environ.copy()
        if password:
            env["PGPASSWORD"] = password

        print(f"Starting restore of database '{db_name}' from '{backup_file}'...")

        # Execute the command
        process = subprocess.Popen(command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()

        if process.returncode == 0:
            print("Restore completed successfully.")
        else:
            print("Error during restore:")
            print(stderr.decode())

    except Exception as e:
        print(f"An error occurred: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Restore PostgreSQL database from a backup file.")
    parser.add_argument("backup_file", help="The path to the backup file to restore.")
    args = parser.parse_args()
    
    run_pg_restore(args.backup_file)
