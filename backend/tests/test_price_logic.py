import pytest
from langchain_core.messages import AIMessage, HumanMessage
from app.agents.price_parser import extract_agreed_price
from app import models, auth
from app.database import Base, get_db
from app.main import app
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import app.database as db_module

def test_extract_agreed_price_various_notations():
    # Various LLM format outputs
    test_cases = [
        ("PROPOSAL_AGREED: 58000", 58000.0),
        ("PROPOSAL_AGREED: 58,000", 58000.0),
        ("PROPOSAL_AGREED: 58000.00", 58000.0),
        ("PROPOSAL_AGREED: [58000]", 58000.0),
        ("PROPOSAL_AGREED: [₹58,000]", 58000.0),
        ("PROPOSAL_AGREED: ₹58,000", 58000.0),
        ("PROPOSAL_AGREED: ₹ 58,000.00", 58000.0),
        ("PROPOSAL_AGREED: Rs. 58000", 58000.0),
        ("PROPOSAL_AGREED: Rs 58,000", 58000.0),
        ("PROPOSAL_AGREED: INR 58000", 58000.0),
        ("PROPOSAL_AGREED: [₹58,000 INR]", 58000.0),
        ("PROPOSAL_AGREED: $58000", 58000.0),
        ("We are pleased to accept your offer at ₹58,000 per unit. PROPOSAL_AGREED: 58000", 58000.0),
        ("PROPOSAL_AGREED: ₹58,000 per unit", 58000.0),
        ("We confirm the deal at ₹58,000.", 58000.0),
        ("We accept your offer of ₹58,000.", 58000.0),
    ]

    for text, expected in test_cases:
        extracted = extract_agreed_price(text)
        assert extracted == expected, f"Failed on '{text}': expected {expected}, got {extracted}"


def test_extract_agreed_price_fallback_to_dialogue():
    # When PROPOSAL_AGREED has no inline number, fall back to recent quote in history
    history = [
        HumanMessage(content="We can offer ₹55,000 per unit."),
        AIMessage(content="We counter at ₹58,000 per unit."),
        HumanMessage(content="That works for us. PROPOSAL_AGREED"),
    ]
    last_msg = history[-1].content
    extracted = extract_agreed_price(last_msg, history)
    assert extracted == 58000.0, f"Expected 58000.0, got {extracted}"


# In-memory test SQLite DB
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

@pytest.fixture(scope="function")
def db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session = TestingSessionLocal()

    buyer = models.User(
        username="price_buyer",
        hashed_password=auth.get_password_hash("buyer123"),
        role="buyer"
    )
    merchant = models.User(
        username="price_merchant",
        hashed_password=auth.get_password_hash("merchant123"),
        role="merchant"
    )
    session.add_all([buyer, merchant])
    session.commit()
    session.refresh(buyer)
    session.refresh(merchant)

    profile = models.MerchantProfile(
        user_id=merchant.id,
        display_name="Elite Wholesaler",
    )
    session.add(profile)
    session.commit()

    item = models.Inventory(
        sku="TEST-CHIP-65K",
        name="High-End Processor",
        current_stock=50,
        base_price=65000.0,
        minimum_margin_limit=50000.0,
        demand_velocity=1.0,
        wholesaler_name="Elite Wholesaler",
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


def test_negotiated_price_is_authoritative_and_independent(client, db):
    # Log in as buyer
    login_res = client.post("/api/auth/token", data={"username": "price_buyer", "password": "buyer123"})
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    item = db.query(models.Inventory).first()
    assert item.base_price == 65000.0

    # 1. Initiate negotiation with budget of 58,000 (below 65k catalog, above 50k floor)
    res = client.post(
        "/api/negotiate",
        headers=headers,
        json={
            "sku": item.sku,
            "quantity": 2,
            "buyer_max_budget": 58000.0,
            "inventory_id": item.id,
        }
    )
    assert res.status_code == 200
    data = res.json()
    
    # Must NOT be 65000.0 catalog price
    assert data["final_price"] is not None
    assert data["final_price"] <= 58000.0
    assert data["final_price"] >= 50000.0
    assert data["final_price"] != 65000.0  # Must not fall back to catalog listed price

    negotiated_price_tx1 = data["final_price"]
    tx_id_1 = data["transaction_id"]

    # Verify transaction record has the exact negotiated price
    tx_res_1 = client.get(f"/api/transactions/{tx_id_1}", headers=headers)
    assert tx_res_1.status_code == 200
    assert tx_res_1.json()["final_price"] == negotiated_price_tx1

    # 2. Initiate a SECOND independent transaction with a DIFFERENT budget (54,000)
    res_2 = client.post(
        "/api/negotiate",
        headers=headers,
        json={
            "sku": item.sku,
            "quantity": 3,
            "buyer_max_budget": 54000.0,
            "inventory_id": item.id,
        }
    )
    assert res_2.status_code == 200
    data_2 = res_2.json()
    negotiated_price_tx2 = data_2["final_price"]
    tx_id_2 = data_2["transaction_id"]

    assert negotiated_price_tx2 is not None
    assert negotiated_price_tx2 < 65000.0  # Not catalog price
    assert negotiated_price_tx2 >= 50000.0  # Above merchant floor
    assert tx_id_1 != tx_id_2

    # Verify both transactions maintain their own independent prices
    tx_check_1 = client.get(f"/api/transactions/{tx_id_1}", headers=headers).json()
    tx_check_2 = client.get(f"/api/transactions/{tx_id_2}", headers=headers).json()

    assert tx_check_1["final_price"] == negotiated_price_tx1
    assert tx_check_2["final_price"] == negotiated_price_tx2
    assert tx_check_1["id"] != tx_check_2["id"]
    # Verify the prices are different and independent
    assert tx_check_1["final_price"] != tx_check_2["final_price"]
