import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime

from app.database import Base
from app import models, schemas
from app.agents.merchant import MerchantAgent, _clamp_price
from app.payment.service import PaymentService, payment_provider
from app.agents.orchestrator import generate_cart_mandate

from sqlalchemy.pool import StaticPool
import app.database as db_module

# Test in-memory SQLite with StaticPool
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    yield session
    session.close()


def test_merchant_zone_strategy_above_buyer_bid():
    """Verify merchant agent counters ABOVE buyer's offer when buyer is already above floor."""
    merchant = MerchantAgent()
    catalog_price = 24000.0
    merchant_floor = 19500.0
    buyer_bid = 21000.0

    state = {
        "messages": [
            type("Msg", (), {"content": f"Offer is {buyer_bid}"})()
        ],
        "quantity": 10,
    }

    # Test heuristic response across all 5 turns
    for turn in range(5):
        res = merchant._heuristic_merchant_response(
            state=state,
            turns=turn,
            max_turns=5,
            merchant_floor=merchant_floor,
            catalog_price=catalog_price,
            merchant_name="Test Wholesaler",
            buyer_bid=buyer_bid
        )
        msg = res["messages"][0].content
        # Merchant must NOT have agreed below buyer_bid or countered below buyer_bid
        if "PROPOSAL_AGREED" in msg:
            import re
            m = re.search(r'PROPOSAL_AGREED:\s*([\d\.]+)', msg)
            assert m is not None
            agreed = float(m.group(1))
            assert agreed >= buyer_bid
            assert agreed >= merchant_floor
        else:
            import re
            m = re.search(r'₹([\d,]+\.?\d*)', msg)
            if m:
                counter = float(m.group(1).replace(',', ''))
                assert counter >= buyer_bid, f"Turn {turn}: Counter {counter} was below buyer bid {buyer_bid}"
                assert counter >= merchant_floor
                assert counter <= catalog_price


def test_deterministic_guardrails_clamp():
    """Verify _clamp_price strictly enforces boundaries."""
    # 1. Buyer offered 21,000 (above floor 19,500). Counter of 19,000 must be clamped to at least 21,000
    clamped = _clamp_price(19000.0, buyer_bid=21000.0, merchant_floor=19500.0, catalog_price=24000.0)
    assert clamped >= 21000.0

    # 2. Counter below floor with buyer below floor must clamp to floor
    clamped_floor = _clamp_price(18000.0, buyer_bid=17000.0, merchant_floor=19500.0, catalog_price=24000.0)
    assert clamped_floor == 19500.0

    # 3. Counter above catalog price must clamp to catalog price
    clamped_ceil = _clamp_price(26000.0, buyer_bid=21000.0, merchant_floor=19500.0, catalog_price=24000.0)
    assert clamped_ceil == 24000.0


def test_quote_lifecycle_and_rejection_restoration(db):
    """
    Test creating AI quote, revising quote, rejecting quote,
    and verifying restoration to prior agreed quote.
    """
    # 1. Seed buyer and merchant
    buyer = models.User(username="buyer_test", hashed_password="pw", role="buyer")
    merchant = models.User(username="merch_test", hashed_password="pw", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()

    profile = models.MerchantProfile(user_id=merchant.id, display_name="Test Merchant")
    db.add(profile)
    db.commit()

    inv = models.Inventory(
        sku="TEST-SKU",
        name="Test Item",
        current_stock=100,
        reserved_stock=0,
        base_price=24000.0,
        minimum_margin_limit=19500.0,
        wholesaler_name="Test Merchant",
        merchant_id=merchant.id
    )
    db.add(inv)
    db.commit()

    tx = models.Transaction(
        sku="TEST-SKU",
        quantity=5,
        final_price=22000.0,
        status=models.TransactionStatus.QUOTE_AGREED,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        buyer_approved=1,
        merchant_approved=1,
        cryptographic_signature=generate_cart_mandate("TEST-SKU", 5, 22000.0, merchant.id, inv.id)
    )
    db.add(tx)
    db.commit()

    # Initial AI quote
    ai_quote = models.Quote(
        transaction_id=tx.id,
        amount=22000.0,
        proposed_by="AI",
        source=models.QuoteSource.AI_NEGOTIATION,
        merchant_accepted=True,
        buyer_accepted=True,
        status=models.QuoteStatus.ACCEPTED,
        created_at=datetime.utcnow(),
        accepted_at=datetime.utcnow()
    )
    db.add(ai_quote)
    db.commit()
    tx.agreed_quote_id = ai_quote.id
    db.commit()

    # Merchant proposes revised quote of 23,000
    revised_quote = models.Quote(
        transaction_id=tx.id,
        amount=23000.0,
        proposed_by="MERCHANT",
        source=models.QuoteSource.MANUAL_MERCHANT,
        merchant_accepted=True,
        buyer_accepted=None,
        status=models.QuoteStatus.PENDING,
        created_at=datetime.utcnow()
    )
    db.add(revised_quote)
    tx.status = models.TransactionStatus.REVISION_PENDING
    db.commit()

    # 1. Payment should be blocked while revision_pending
    with pytest.raises(ValueError, match="Negotiation is not ready for payment"):
        PaymentService.create_order(tx.id, buyer.id, db)

    # 2. Even if status was spoofed to QUOTE_AGREED, pending quote check must block payment
    tx.status = models.TransactionStatus.QUOTE_AGREED
    db.commit()
    with pytest.raises(ValueError, match="revised quote is currently pending"):
        PaymentService.create_order(tx.id, buyer.id, db)

    # Buyer rejects the 23,000 quote
    revised_quote.status = models.QuoteStatus.REJECTED
    revised_quote.buyer_accepted = False
    
    # Restore prior accepted quote
    prev_accepted = db.query(models.Quote).filter(
        models.Quote.transaction_id == tx.id,
        models.Quote.status == models.QuoteStatus.ACCEPTED
    ).order_by(models.Quote.id.desc()).first()

    assert prev_accepted is not None
    assert prev_accepted.id == ai_quote.id
    tx.agreed_quote_id = prev_accepted.id
    tx.final_price = prev_accepted.amount
    tx.status = models.TransactionStatus.QUOTE_AGREED
    db.commit()

    # Now payment should succeed on the restored price (22,000 * 5 = 110,000)
    order = PaymentService.create_order(tx.id, buyer.id, db)
    assert order.agreed_price == 22000.0
    assert order.total_amount == 110000.0
    assert order.order_status == models.OrderStatus.PENDING


def test_revised_quote_both_accept_and_pay(db):
    """Test full cycle: propose revision -> counter-party accepts -> payment locks in revised amount."""
    buyer = models.User(username="b2", hashed_password="pw", role="buyer")
    merchant = models.User(username="m2", hashed_password="pw", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()

    inv = models.Inventory(
        sku="TEST-SKU-2",
        name="Test Item 2",
        current_stock=50,
        reserved_stock=0,
        base_price=10000.0,
        minimum_margin_limit=8000.0,
        wholesaler_name="M2 Wholesaler",
        merchant_id=merchant.id
    )
    db.add(inv)
    db.commit()

    tx = models.Transaction(
        sku="TEST-SKU-2",
        quantity=2,
        final_price=9000.0,
        status=models.TransactionStatus.QUOTE_AGREED,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
        buyer_approved=1,
        merchant_approved=1,
        cryptographic_signature=generate_cart_mandate("TEST-SKU-2", 2, 9000.0, merchant.id, inv.id)
    )
    db.add(tx)
    db.commit()

    initial_quote = models.Quote(
        transaction_id=tx.id,
        amount=9000.0,
        proposed_by="AI",
        source=models.QuoteSource.AI_NEGOTIATION,
        merchant_accepted=True,
        buyer_accepted=True,
        status=models.QuoteStatus.ACCEPTED
    )
    db.add(initial_quote)
    db.commit()
    tx.agreed_quote_id = initial_quote.id
    db.commit()

    # Buyer proposes 8,500
    buyer_rev = models.Quote(
        transaction_id=tx.id,
        amount=8500.0,
        proposed_by="BUYER",
        source=models.QuoteSource.MANUAL_BUYER,
        merchant_accepted=None,
        buyer_accepted=True,
        status=models.QuoteStatus.PENDING
    )
    db.add(buyer_rev)
    tx.status = models.TransactionStatus.REVISION_PENDING
    db.commit()

    # Merchant accepts 8,500 (since 8500 >= floor 8000)
    assert buyer_rev.amount >= inv.minimum_margin_limit
    buyer_rev.merchant_accepted = True
    buyer_rev.status = models.QuoteStatus.ACCEPTED
    buyer_rev.accepted_at = datetime.utcnow()

    tx.agreed_quote_id = buyer_rev.id
    tx.final_price = 8500.0
    tx.buyer_approved = 1
    tx.merchant_approved = 1
    tx.status = models.TransactionStatus.MUTUALLY_APPROVED
    tx.cryptographic_signature = generate_cart_mandate("TEST-SKU-2", 2, 8500.0, merchant.id, inv.id)
    db.commit()

    # Create payment order
    order = PaymentService.create_order(tx.id, buyer.id, db)
    assert order.agreed_price == 8500.0
    assert order.total_amount == 17000.0  # 8500 * 2


def test_nine_state_lifecycle(db):
    """
    Tests the complete 9-state lifecycle:
    1. NEGOTIATING -> 2. AI_NEGOTIATION_COMPLETED -> 4. AWAITING_MERCHANT_APPROVAL
    -> 5. MANUAL_REVISION_IN_PROGRESS -> 6. MUTUALLY_APPROVED -> 7. PAYMENT_INITIATED -> 8. COMPLETED
    """
    buyer = models.User(username="buyer_9s", hashed_password="pwd", role="buyer")
    merchant = models.User(username="merchant_9s", hashed_password="pwd", role="merchant")
    db.add_all([buyer, merchant])
    db.commit()

    inv = models.Inventory(
        sku="TEST-9S",
        name="Nine State Item",
        current_stock=10,
        reserved_stock=0,
        base_price=1000.0,
        minimum_margin_limit=800.0,
        wholesaler_name="State Merchant",
        merchant_id=merchant.id,
    )
    db.add(inv)
    db.commit()

    # 1. State 1: NEGOTIATING
    tx = models.Transaction(
        sku="TEST-9S",
        quantity=2,
        status=models.TransactionStatus.NEGOTIATING,
        buyer_id=buyer.id,
        merchant_id=merchant.id,
        inventory_id=inv.id,
    )
    db.add(tx)
    db.commit()
    assert tx.status == "negotiating"

    # 2. State 2: AI_NEGOTIATION_COMPLETED
    ai_quote = models.Quote(
        transaction_id=tx.id,
        amount=950.0,
        proposed_by="AI",
        source=models.QuoteSource.AI_NEGOTIATION,
        status=models.QuoteStatus.PENDING,
    )
    db.add(ai_quote)
    tx.status = models.TransactionStatus.AI_NEGOTIATION_COMPLETED
    tx.final_price = 950.0
    tx.agreed_quote_id = ai_quote.id
    tx.buyer_approved = 0
    tx.merchant_approved = 0
    db.commit()
    assert tx.status == "ai_negotiation_completed"
    assert tx.buyer_approved == 0
    assert tx.merchant_approved == 0

    # 3. Buyer approves AI price -> State 4: AWAITING_MERCHANT_APPROVAL
    tx.buyer_approved = 1
    ai_quote.buyer_accepted = True
    tx.status = models.TransactionStatus.AWAITING_MERCHANT_APPROVAL
    db.commit()
    assert tx.status == "awaiting_merchant_approval"

    # 4. Merchant rejects AI price & proposes manual revision -> State 5: MANUAL_REVISION_IN_PROGRESS
    ai_quote.status = models.QuoteStatus.SUPERSEDED
    merch_rev = models.Quote(
        transaction_id=tx.id,
        amount=970.0,
        proposed_by="MERCHANT",
        source=models.QuoteSource.MANUAL_MERCHANT,
        merchant_accepted=True,
        buyer_accepted=None,
        status=models.QuoteStatus.PENDING,
    )
    db.add(merch_rev)
    tx.status = models.TransactionStatus.MANUAL_REVISION_IN_PROGRESS
    tx.final_price = 970.0
    tx.merchant_approved = 1
    tx.buyer_approved = 0
    db.commit()
    assert tx.status == "revision_pending"

    # 5. Buyer accepts merchant quote -> State 6: MUTUALLY_APPROVED
    merch_rev.buyer_accepted = True
    merch_rev.status = models.QuoteStatus.ACCEPTED
    merch_rev.accepted_at = datetime.utcnow()
    tx.agreed_quote_id = merch_rev.id
    tx.buyer_approved = 1
    tx.merchant_approved = 1
    tx.status = models.TransactionStatus.MUTUALLY_APPROVED
    tx.cryptographic_signature = generate_cart_mandate("TEST-9S", 2, 970.0, merchant.id, inv.id)
    db.commit()
    assert tx.status == "mutually_approved"
    assert tx.buyer_approved == 1
    assert tx.merchant_approved == 1

    # 6. Payment initiation -> State 7: PAYMENT_INITIATED
    order = PaymentService.create_order(tx.id, buyer.id, db)
    db.refresh(tx)
    assert tx.status == "payment_initiated"
    assert order.agreed_price == 970.0
    assert order.total_amount == 1940.0

    # 7. Payment checkout & confirmed -> State 8: COMPLETED (paid)
    checkout_res = PaymentService.initiate_checkout(order.id, buyer.id, db)
    mock_rzp = payment_provider.generate_mock_payment(checkout_res.razorpay_order_id)
    PaymentService.verify_payment(
        order_id=order.id,
        razorpay_order_id=checkout_res.razorpay_order_id,
        razorpay_payment_id=mock_rzp["razorpay_payment_id"],
        razorpay_signature=mock_rzp["razorpay_signature"],
        buyer_id=buyer.id,
        db=db,
    )
    db.refresh(tx)
    assert tx.status in (models.TransactionStatus.COMPLETED, "paid")


def test_merchant_submit_revised_quote_via_api_and_buyer_decision(db):
    """
    Full end-to-end API integration test:
    1. Buyer initiates negotiation on inventory with base 4200, min 3600.
    2. Buyer proposes sub-floor revised quote of 3500.
    3. Merchant tries to propose 3500 -> rejected with 422 (below floor).
    4. Merchant proposes valid revised quote of 3800 -> accepted & saved as PENDING.
    5. Buyer accepts merchant's 3800 quote -> becomes MUTUALLY_APPROVED.
    6. Verify final price is 3800 with active cart mandate.
    """
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import get_db

    def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    try:
        # 1. Seed buyer, merchant, and inventory
        from app import auth
        buyer = models.User(username="rev_buyer", hashed_password=auth.get_password_hash("pw"), role="buyer")
        merchant = models.User(username="rev_merch", hashed_password=auth.get_password_hash("pw"), role="merchant")
        db.add_all([buyer, merchant])
        db.commit()

        profile = models.MerchantProfile(user_id=merchant.id, display_name="Pro SSD Wholesaler")
        db.add(profile)
        db.commit()

        inv = models.Inventory(
            sku="PROD-SSD-1TB",
            name="Kingston NVMe 1TB SSD",
            current_stock=100,
            reserved_stock=0,
            base_price=4200.0,
            minimum_margin_limit=3600.0,
            demand_velocity=1.0,
            wholesaler_name="Pro SSD Wholesaler",
            merchant_id=merchant.id,
        )
        db.add(inv)
        db.commit()

        # Login tokens
        buyer_token = client.post("/api/auth/token", data={"username": "rev_buyer", "password": "pw"}).json()["access_token"]
        merch_token = client.post("/api/auth/token", data={"username": "rev_merch", "password": "pw"}).json()["access_token"]
        buyer_headers = {"Authorization": f"Bearer {buyer_token}"}
        merch_headers = {"Authorization": f"Bearer {merch_token}"}

        # Create transaction
        tx = models.Transaction(
            sku=inv.sku,
            quantity=1,
            final_price=3900.0,
            status=models.TransactionStatus.QUOTE_AGREED,
            buyer_id=buyer.id,
            merchant_id=merchant.id,
            inventory_id=inv.id,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)

        # 2. Buyer proposes 3500 (below merchant floor of 3600)
        buyer_quote_res = client.post(
            f"/api/transactions/{tx.id}/quotes",
            headers=buyer_headers,
            json={"amount": 3500.0, "note": "Can you do 3500?"}
        )
        assert buyer_quote_res.status_code == 200
        buyer_quote_id = buyer_quote_res.json()["id"]

        # Verify transaction shows awaiting merchant approval
        tx_detail = client.get(f"/api/transactions/{tx.id}", headers=merch_headers).json()
        assert tx_detail["status"] == "awaiting_merchant_approval"
        assert tx_detail["active_quote"]["id"] == buyer_quote_id
        assert tx_detail["merchant_minimum_price"] == 3600.0

        # 3. Merchant tries to accept 3500 -> blocked by floor check with 422
        merch_accept_fail = client.post(
            f"/api/transactions/{tx.id}/quotes/{buyer_quote_id}/accept",
            headers=merch_headers
        )
        assert merch_accept_fail.status_code == 422

        # 4. Merchant tries to propose 3500 -> blocked by floor check with 422
        merch_propose_fail = client.post(
            f"/api/transactions/{tx.id}/quotes",
            headers=merch_headers,
            json={"amount": 3500.0, "note": "Countering with 3500"}
        )
        assert merch_propose_fail.status_code == 422

        # 5. Merchant proposes valid revised quote of 3750 -> SUCCESS
        merch_quote_res = client.post(
            f"/api/transactions/{tx.id}/quotes",
            headers=merch_headers,
            json={"amount": 3750.0, "note": "Best we can do is 3750"}
        )
        assert merch_quote_res.status_code == 200
        merch_quote_data = merch_quote_res.json()
        assert merch_quote_data["amount"] == 3750.0
        assert merch_quote_data["proposed_by"] == "MERCHANT"
        merch_quote_id = merch_quote_data["id"]

        # Verify transaction now reflects merchant's proposal awaiting buyer approval
        tx_detail = client.get(f"/api/transactions/{tx.id}", headers=buyer_headers).json()
        assert tx_detail["status"] == "awaiting_buyer_approval"
        assert tx_detail["active_quote"]["id"] == merch_quote_id
        assert tx_detail["final_price"] == 3750.0

        # 6. Buyer accepts the 3750 quote -> MUTUALLY_APPROVED
        buyer_accept_res = client.post(
            f"/api/transactions/{tx.id}/quotes/{merch_quote_id}/accept",
            headers=buyer_headers
        )
        assert buyer_accept_res.status_code == 200
        assert buyer_accept_res.json()["status"] == "accepted"

        # 7. Verify final transaction state
        final_tx = client.get(f"/api/transactions/{tx.id}", headers=buyer_headers).json()
        assert final_tx["status"] == "mutually_approved"
        assert final_tx["final_price"] == 3750.0
        assert final_tx["buyer_approved"] == 1
        assert final_tx["merchant_approved"] == 1
        assert final_tx["cryptographic_signature"] is not None
    finally:
        app.dependency_overrides.clear()
