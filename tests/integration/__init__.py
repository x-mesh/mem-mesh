"""Integration tests against a live mem-mesh API server (localhost:8000).

Prerequisites:
    - API server running: python -m app.web --reload
    - Real data in database (for test_realdata_scenarios)

Run:
    pytest tests/integration/ -v
"""
