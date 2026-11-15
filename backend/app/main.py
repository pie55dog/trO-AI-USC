"""Tro backend entry point.

Run locally (from the backend/ folder):   uvicorn app.main:app --reload
Interactive API docs are then at http://localhost:8000/docs
"""

from .factory import create_app

app = create_app()
