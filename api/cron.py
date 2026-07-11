import os
import secrets
import requests
from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        scheduler_secret = os.environ.get("SCHEDULER_SECRET")
        app_url = os.environ.get("APP_URL")
        cron_secret = os.environ.get("CRON_SECRET")

        # Fail closed: without a configured CRON_SECRET nothing may trigger
        # the notification fan-out, regardless of environment.
        authorization = self.headers.get("authorization", "")
        if not cron_secret or not secrets.compare_digest(authorization, f"Bearer {cron_secret}"):
            self.send_response(401)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        if not scheduler_secret or not app_url:
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(b"Missing SCHEDULER_SECRET or APP_URL environment variables.")
            return

        trigger_url = f"{app_url.rstrip('/')}/api/trigger-scheduler"

        try:
            response = requests.get(
                trigger_url,
                headers={"X-Scheduler-Secret": scheduler_secret},
                # Covers webhook checks + the notification fan-out with room
                # to spare; the sends themselves run concurrently.
                timeout=55,
            )
            response.raise_for_status()  # Raise an exception for bad status codes
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(response.content)

        except requests.exceptions.RequestException as e:
            self.send_response(500)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(f"Failed to trigger scheduler: {e}".encode('utf-8'))
