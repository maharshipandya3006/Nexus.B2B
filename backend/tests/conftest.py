import pytest
from app.rate_limit import limiter, lockout_manager

@pytest.fixture(autouse=True)
def reset_rate_limits():
    """Ensure in-memory rate limits and lockouts are clean across test runs."""
    lockout_manager.clear_all()
    try:
        limiter._storage.storage.clear()
    except Exception:
        pass
    yield
    lockout_manager.clear_all()
    try:
        limiter._storage.storage.clear()
    except Exception:
        pass
