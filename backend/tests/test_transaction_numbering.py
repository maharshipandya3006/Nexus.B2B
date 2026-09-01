import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.database as db_module
from app.database import Base, get_db
from app.main import app
from app import models, auth

# In-memory test SQLite DB with StaticPool
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()

    # Seed buyer
    buyer = models.User(
        username="test_buyer",
        hashed_password=auth.get_password_hash("buyer123"),
        role="buyer"
    )
    # Seed merchant
    merchant = models.User(
        username="test_merchant",
        hashed_password=auth.get_password_hash("merchant123"),
        role="merchant"
    )
    session.add_all([buyer, merchant])
    session.commit()
    session.refresh(buyer)
    session.refresh(merchant)

    # Seed merchant profile
    profile = models.MerchantProfile(
        user_id=merchant.id,
        display_name="Test Merchant Corp",
    )
    session.add(profile)
    session.commit()

    # Seed inventory
    item = models.Inventory(
        sku="TEST-SKU-1",
        name="Test Component Item",
        current_stock=100,
        base_price=5000.0,
        minimum_margin_limit=4000.0,
        demand_velocity=1.0,
        wholesaler_name="Test Merchant Corp",
        merchant_id=merchant.id,
    )
    session.add(item)
    session.commit()
    session.refresh(item)

    try:
        yield session
    finally:
        session.close()

@pytest.fixture(scope="function")
def client(db):
    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    test_client = TestClient(app)
    yield test_client
    app.dependency_overrides.clear()


def test_initiate_negotiation_generates_persistent_transaction_number(client, db):
    # Log in as buyer
    login_res = client.post("/api/auth/token", data={"username": "test_buyer", "password": "buyer123"})
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    item = db.query(models.Inventory).first()

    # Initiate targeted negotiation
    res = client.post(
        "/api/negotiate",
        headers=headers,
        json={
            "sku": item.sku,
            "quantity": 5,
            "buyer_max_budget": 4800.0,
            "inventory_id": item.id,
        }
    )
    assert res.status_code == 200
    data = res.json()
    assert "transaction_id" in data
    assert "transaction_number" in data
    assert data["transaction_number"] == f"NXS-{data['transaction_id']:04d}"

    # Verify persistent in database
    tx = db.query(models.Transaction).filter(models.Transaction.id == data["transaction_id"]).first()
    assert tx is not None
    assert tx.transaction_number == data["transaction_number"]

    # Verify returned on GET /api/transactions
    list_res = client.get("/api/transactions", headers=headers)
    assert list_res.status_code == 200
    txs = list_res.json()
    assert len(txs) >= 1
    matching = next(t for t in txs if t["id"] == tx.id)
    assert matching["transaction_number"] == tx.transaction_number

    # Verify returned on GET /api/transactions/{id}
    detail_res = client.get(f"/api/transactions/{tx.id}", headers=headers)
    assert detail_res.status_code == 200
    assert detail_res.json()["transaction_number"] == tx.transaction_number


def test_multi_negotiation_generates_transaction_numbers_for_all_offers(client, db):
    merchant = db.query(models.User).filter(models.User.role == "merchant").first()

    # Create second merchant with same SKU
    merchant2 = models.User(
        username="test_merchant_2",
        hashed_password=auth.get_password_hash("merchant123"),
        role="merchant"
    )
    db.add(merchant2)
    db.commit()
    db.refresh(merchant2)

    item2 = models.Inventory(
        sku="TEST-SKU-1",
        name="Test Component Item (Alt)",
        current_stock=50,
        base_price=4900.0,
        minimum_margin_limit=3900.0,
        demand_velocity=1.0,
        wholesaler_name="Test Merchant 2",
        merchant_id=merchant2.id,
    )
    db.add(item2)
    db.commit()

    # Login as buyer
    login_res = client.post("/api/auth/token", data={"username": "test_buyer", "password": "buyer123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Run multi negotiation
    res = client.post(
        "/api/negotiate/multi",
        headers=headers,
        json={
            "sku": "TEST-SKU-1",
            "quantity": 10,
            "buyer_max_budget": 4500.0,
        }
    )
    assert res.status_code == 200
    multi_data = res.json()
    assert len(multi_data["offers"]) == 2
    for offer in multi_data["offers"]:
        assert offer["transaction_number"] is not None
        assert offer["transaction_number"].startswith("NXS-")
        assert offer["transaction_number"] == f"NXS-{offer['transaction_id']:04d}"
