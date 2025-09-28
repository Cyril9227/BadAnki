# tests/test_main.py
import pytest
from fastapi.testclient import TestClient

# We need to import our app from main
from main import app

client = TestClient(app)

def test_read_main():
    """
    Tests that the root endpoint ("/") is accessible without authentication.
    """
    response = client.get("/")
    assert response.status_code == 200
    # Check for a more specific element in the home page template
    assert 'Personal Learning App' in response.text