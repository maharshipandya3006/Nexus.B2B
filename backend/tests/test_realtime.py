import pytest
import json
from starlette.testclient import TestClient
from app.main import app
from app.auth import create_access_token
from app.database import Base, engine, get_db, SessionLocal
from app import models

client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    # Ensure seed users exist
    buyer = db.query(models.User).filter(models.User.username == "rt_buyer").first()
    if not buyer:
        buyer = models.User(username="rt_buyer", hashed_password="pw", role="buyer")
        db.add(buyer)
    merchant = db.query(models.User).filter(models.User.username == "rt_merchant").first()
    if not merchant:
        merchant = models.User(username="rt_merchant", hashed_password="pw", role="merchant")
        db.add(merchant)
    intruder = db.query(models.User).filter(models.User.username == "rt_intruder").first()
    if not intruder:
        intruder = models.User(username="rt_intruder", hashed_password="pw", role="buyer")
        db.add(intruder)
    db.commit()
    db.close()
    yield
    # clean up could go here if needed


def test_websocket_auth_unauthorized():
    """Verify unauthorized WebSocket connection is rejected."""
    with pytest.raises(Exception):
        with client.websocket_connect("/api/ws/transactions/99999") as ws:
            pass


def test_websocket_auth_forbidden():
    """Verify user not party to transaction is rejected with 4403."""
    db = SessionLocal()
    buyer = db.query(models.User).filter(models.User.username == "rt_buyer").first()
    merchant = db.query(models.User).filter(models.User.username == "rt_merchant").first()
    intruder = db.query(models.User).filter(models.User.username == "rt_intruder").first()

    tx = models.Transaction(
        sku="TEST-SKU",
        quantity=1,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        final_price=1000.0,
        status=models.TransactionStatus.AI_NEGOTIATION_COMPLETED
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    tx_id = tx.id
    db.close()

    intruder_token = create_access_token({"sub": "rt_intruder", "role": "buyer"})
    with pytest.raises(Exception):
        with client.websocket_connect(f"/api/ws/transactions/{tx_id}?token={intruder_token}") as ws:
            pass


def test_websocket_realtime_broadcast_between_buyer_and_merchant():
    """
    Test dual WebSocket rooms:
    1. Buyer connects to transaction room.
    2. Merchant connects to transaction room.
    3. Action occurs (quote revision, approval, termination).
    4. Both sockets immediately receive real-time JSON payloads.
    """
    db = SessionLocal()
    buyer = db.query(models.User).filter(models.User.username == "rt_buyer").first()
    merchant = db.query(models.User).filter(models.User.username == "rt_merchant").first()

    import uuid
    dynamic_sku = f"RT-SKU-{uuid.uuid4().hex[:8]}"

    inv = models.Inventory(
        merchant_id=merchant.id,
        sku=dynamic_sku,
        name="RT M4 Pro",
        current_stock=10,
        reserved_stock=0,
        base_price=25000.0,
        minimum_margin_limit=20000.0,
        demand_velocity=1.0,
        wholesaler_name="RT Wholesaler",
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    tx = models.Transaction(
        sku=dynamic_sku,
        quantity=1,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        final_price=22000.0,
        status=models.TransactionStatus.AI_NEGOTIATION_COMPLETED,
        buyer_approved=0,
        merchant_approved=0,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    tx_id = tx.id
    db.close()

    buyer_token = create_access_token({"sub": "rt_buyer", "role": "buyer"})
    merchant_token = create_access_token({"sub": "rt_merchant", "role": "merchant"})

    buyer_headers = {"Authorization": f"Bearer {buyer_token}"}
    merchant_headers = {"Authorization": f"Bearer {merchant_token}"}

    # Open concurrent WebSockets for both buyer and merchant
    with client.websocket_connect(f"/api/ws/transactions/{tx_id}?token={buyer_token}") as buyer_ws:
        with client.websocket_connect(f"/api/ws/transactions/{tx_id}?token={merchant_token}") as merchant_ws:
            # Consume initial CONNECTED welcome frames
            buyer_init = json.loads(buyer_ws.receive_text())
            assert buyer_init["event_type"] == "CONNECTED"
            merchant_init = json.loads(merchant_ws.receive_text())
            assert merchant_init["event_type"] == "CONNECTED"

            # 1. Buyer proposes revised quote via REST
            resp = client.post(
                f"/api/transactions/{tx_id}/quotes",
                headers=buyer_headers,
                json={"amount": 21500.0, "note": "Realtime quote test"}
            )
            assert resp.status_code == 200

            # Buyer should receive QUOTE_UPDATED
            buyer_msg1 = json.loads(buyer_ws.receive_text())
            assert buyer_msg1["event_type"] == "QUOTE_UPDATED"
            assert buyer_msg1["data"]["quote"]["amount"] == 21500.0

            # Merchant should ALSO receive QUOTE_UPDATED immediately
            merchant_msg1 = json.loads(merchant_ws.receive_text())
            assert merchant_msg1["event_type"] == "QUOTE_UPDATED"
            assert merchant_msg1["data"]["quote"]["amount"] == 21500.0

            # Next message is TRANSACTION_STATUS_CHANGED
            buyer_msg2 = json.loads(buyer_ws.receive_text())
            assert buyer_msg2["event_type"] == "TRANSACTION_STATUS_CHANGED"
            merchant_msg2 = json.loads(merchant_ws.receive_text())
            assert merchant_msg2["event_type"] == "TRANSACTION_STATUS_CHANGED"

            quote_id = resp.json()["id"]

            # 2. Merchant accepts the revised quote via REST
            resp_accept = client.post(
                f"/api/transactions/{tx_id}/quotes/{quote_id}/accept",
                headers=merchant_headers
            )
            assert resp_accept.status_code == 200

            # Both sockets must immediately receive PRICE_ACCEPTED
            buyer_acc = json.loads(buyer_ws.receive_text())
            assert buyer_acc["event_type"] == "PRICE_ACCEPTED"
            assert buyer_acc["data"]["status"] == "mutually_approved"

            merchant_acc = json.loads(merchant_ws.receive_text())
            assert merchant_acc["event_type"] == "PRICE_ACCEPTED"
            assert merchant_acc["data"]["status"] == "mutually_approved"

            # 3. Terminate transaction test
            resp_term = client.post(
                f"/api/transactions/{tx_id}/terminate",
                headers=buyer_headers
            )
            assert resp_term.status_code == 200

            # Both receive TRANSACTION_TERMINATED
            # drain any status changed
            buyer_ev = json.loads(buyer_ws.receive_text())
            if buyer_ev["event_type"] == "TRANSACTION_STATUS_CHANGED":
                buyer_ev = json.loads(buyer_ws.receive_text())
            assert buyer_ev["event_type"] == "TRANSACTION_TERMINATED"
            assert buyer_ev["data"]["status"] == "terminated"

            merch_ev = json.loads(merchant_ws.receive_text())
            if merch_ev["event_type"] == "TRANSACTION_STATUS_CHANGED":
                merch_ev = json.loads(merchant_ws.receive_text())
            assert merch_ev["event_type"] == "TRANSACTION_TERMINATED"
            assert merch_ev["data"]["status"] == "terminated"


def test_dashboard_websocket_broadcast():
    """Verify user dashboard WebSocket receives transaction status change notifications."""
    db = SessionLocal()
    buyer = db.query(models.User).filter(models.User.username == "rt_buyer").first()
    merchant = db.query(models.User).filter(models.User.username == "rt_merchant").first()

    import uuid
    dynamic_sku = f"RT-DASH-{uuid.uuid4().hex[:8]}"

    inv = models.Inventory(
        merchant_id=merchant.id,
        sku=dynamic_sku,
        name="RT Dashboard SKU",
        current_stock=10,
        reserved_stock=0,
        base_price=30000.0,
        minimum_margin_limit=25000.0,
        demand_velocity=1.0,
        wholesaler_name="RT Wholesaler",
    )
    db.add(inv)
    db.commit()
    db.refresh(inv)

    tx = models.Transaction(
        sku=dynamic_sku,
        quantity=1,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        final_price=27000.0,
        status=models.TransactionStatus.AI_NEGOTIATION_COMPLETED,
        buyer_approved=0,
        merchant_approved=0,
    )
    db.add(tx)
    db.commit()
    db.refresh(tx)
    tx_id = tx.id
    db.close()

    buyer_token = create_access_token({"sub": "rt_buyer", "role": "buyer"})
    merchant_token = create_access_token({"sub": "rt_merchant", "role": "merchant"})

    buyer_headers = {"Authorization": f"Bearer {buyer_token}"}

    # Connect to dashboard WebSocket
    with client.websocket_connect(f"/api/ws/dashboard?token={merchant_token}") as dash_ws:
        init_frame = json.loads(dash_ws.receive_text())
        assert init_frame["event_type"] == "CONNECTED"

        # Buyer proposes quote via REST
        resp = client.post(
            f"/api/transactions/{tx_id}/quotes",
            headers=buyer_headers,
            json={"amount": 26500.0, "note": "Dashboard push test"}
        )
        assert resp.status_code == 200

        # Merchant's dashboard stream should receive event
        dash_ev = json.loads(dash_ws.receive_text())
        assert dash_ev["event_type"] in ("QUOTE_UPDATED", "TRANSACTION_STATUS_CHANGED")
        assert dash_ev["data"]["transaction_id"] == tx_id

