import pytest
from starlette.testclient import TestClient
from app.database import Base, engine, SessionLocal, get_db
from app.main import app
from app import models, auth
from app.rate_limit import lockout_manager
import uuid

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield


@pytest.fixture(scope="function")
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


# =========================================================================
# 1. Server-Side Input Validation Tests
# =========================================================================

def test_register_valid_user():
    username = f"safe_trader_{uuid.uuid4().hex[:6]}"
    res = client.post("/api/auth/register", json={
        "username": username,
        "password": "strongpassword123",
        "role": "buyer"
    })
    assert res.status_code == 201
    data = res.json()
    assert data["username"] == username
    assert data["role"] == "buyer"
    assert "id" in data


def test_register_invalid_username_characters():
    # Special characters/HTML/script tags must be rejected
    res = client.post("/api/auth/register", json={
        "username": "<script>alert(1)</script>",
        "password": "validpassword123",
        "role": "buyer"
    })
    assert res.status_code == 422


def test_register_username_too_short():
    res = client.post("/api/auth/register", json={
        "username": "ab",
        "password": "validpassword123",
        "role": "buyer"
    })
    assert res.status_code == 422


def test_register_username_too_long():
    res = client.post("/api/auth/register", json={
        "username": "a" * 31,
        "password": "validpassword123",
        "role": "buyer"
    })
    assert res.status_code == 422


def test_register_password_too_short():
    res = client.post("/api/auth/register", json={
        "username": "valid_user",
        "password": "123",
        "role": "buyer"
    })
    assert res.status_code == 422


def test_register_invalid_role():
    # Roles outside "buyer" and "merchant" (e.g. attempting to grant "admin") must be rejected
    res = client.post("/api/auth/register", json={
        "username": "attacker_user",
        "password": "validpassword123",
        "role": "superadmin"
    })
    assert res.status_code == 422


def test_register_duplicate_username():
    unique_username = f"dup_{uuid.uuid4().hex[:6]}"
    # Register once
    res1 = client.post("/api/auth/register", json={
        "username": unique_username,
        "password": "validpassword123",
        "role": "merchant"
    })
    assert res1.status_code == 201

    # Attempt second registration with same username
    res2 = client.post("/api/auth/register", json={
        "username": unique_username,
        "password": "validpassword123",
        "role": "merchant"
    })
    assert res2.status_code == 400
    assert res2.json()["detail"] == "Username already registered"


# =========================================================================
# 2. Account Lockout & Brute-Force Defense Tests
# =========================================================================

def test_account_lockout_after_max_failed_attempts(db_session):
    username = f"target_user_{uuid.uuid4().hex[:6]}"
    correct_pwd = "safePassword123"

    # Seed target user
    user = models.User(
        username=username,
        hashed_password=auth.get_password_hash(correct_pwd),
        role="buyer"
    )
    db_session.add(user)
    db_session.commit()

    # Reset any lockout tracking for test purity
    lockout_manager.reset_attempts(username)

    # 4 consecutive bad attempts -> should return 401
    for i in range(4):
        res = client.post("/api/auth/token", data={"username": username, "password": "wrong_password"})
        assert res.status_code == 401
        assert res.json()["detail"] == "Incorrect username or password"

    # 5th bad attempt triggers the lockout (status 429)
    res5 = client.post("/api/auth/token", data={"username": username, "password": "wrong_password"})
    assert res5.status_code == 429
    assert "temporarily locked" in res5.json()["detail"].lower()

    # 6th attempt with the CORRECT password is still locked out
    res6 = client.post("/api/auth/token", data={"username": username, "password": correct_pwd})
    assert res6.status_code == 429
    assert "temporarily locked" in res6.json()["detail"].lower()

    # Reset lockout and verify correct password now succeeds
    lockout_manager.reset_attempts(username)
    res_success = client.post("/api/auth/token", data={"username": username, "password": correct_pwd})
    assert res_success.status_code == 200
    assert "access_token" in res_success.json()


# =========================================================================
# 3. Password Hashing Work Factor & UTF-8 Tests
# =========================================================================

def test_bcrypt_work_factor():
    pwd = "superSecretPassword123"
    hashed = auth.get_password_hash(pwd)
    # Check that bcrypt hash prefix indicates 12 rounds ($2b$12$)
    assert hashed.startswith("$2b$12$") or hashed.startswith("$2a$12$")
    assert auth.verify_password(pwd, hashed) is True
    assert auth.verify_password("wrong", hashed) is False


# =========================================================================
# 4. Broken Object-Level Authorization (BOLA) Tests
# =========================================================================

def test_user_cannot_modify_or_delete_other_users(db_session):
    # Create User A and User B
    username_a = f"alice_{uuid.uuid4().hex[:6]}"
    username_b = f"bob_{uuid.uuid4().hex[:6]}"
    user_a = models.User(username=username_a, hashed_password=auth.get_password_hash("pass12345"), role="buyer")
    user_b = models.User(username=username_b, hashed_password=auth.get_password_hash("pass12345"), role="merchant")
    db_session.add_all([user_a, user_b])
    db_session.commit()
    db_session.refresh(user_a)
    db_session.refresh(user_b)

    # Alice logs in
    token_a = auth.create_access_token(data={"sub": user_a.username})
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Alice attempts to update Bob's account (id = user_b.id)
    res_put = client.put(f"/api/users/{user_b.id}", json={"role": "merchant"}, headers=headers_a)
    assert res_put.status_code == 403

    # Alice attempts to delete Bob's account
    res_del = client.delete(f"/api/users/{user_b.id}", headers=headers_a)
    assert res_del.status_code == 403

    # Alice updates her OWN account -> succeeds
    res_put_self = client.put(f"/api/users/{user_a.id}", json={"role": "buyer"}, headers=headers_a)
    assert res_put_self.status_code == 200
