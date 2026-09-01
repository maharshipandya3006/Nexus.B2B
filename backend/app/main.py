from fastapi import FastAPI, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session, sessionmaker
from typing import List, Optional
import asyncio
import logging
import json
from datetime import datetime

from .config import settings
from .database import engine, Base, get_db
from . import models, schemas, auth, realtime
from .rate_limit import limiter, lockout_manager
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler
from .agents.orchestrator import NegotiationOrchestrator, verify_cart_mandate
from .agents.upsell import UpsellAgent
from .payment.razorpay_provider import payment_provider
from .payment.service import PaymentService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.PROJECT_NAME)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Enable CORS for frontend routing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this. For hackathon, allow all.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
@app.get("/health")
@app.get("/api/health")
def health_check():
    return {"status": "healthy", "service": "Nexus B2B API", "version": "1.0.0"}



# =========================================================================
# STARTUP: Seed DB with demo data (dynamic, merchant-as-data)
# =========================================================================
@app.on_event("startup")
def startup_db_seed():
    db = next(get_db())
    try:
        # 1. Seed demo buyer
        buyer = db.query(models.User).filter(models.User.username == "retail_purchaser").first()
        if not buyer:
            hashed_pwd_buyer = auth.get_password_hash("retail_purchaser")
            buyer = models.User(username="retail_purchaser", hashed_password=hashed_pwd_buyer, role="buyer")
            db.add(buyer)
            db.commit()
            db.refresh(buyer)
            logger.info("Demo buyer seeded.")

        # 2. Seed Merchant A: Nexus Global Tech
        merchant_a = db.query(models.User).filter(models.User.username == "nexus_wholesaler").first()
        if not merchant_a:
            hashed_pwd = auth.get_password_hash("nexus_wholesaler")
            merchant_a = models.User(username="nexus_wholesaler", hashed_password=hashed_pwd, role="merchant")
            db.add(merchant_a)
            db.commit()
            db.refresh(merchant_a)

            # Create MerchantProfile (dynamic metadata — not hardcoded anywhere else)
            profile_a = models.MerchantProfile(
                user_id=merchant_a.id,
                display_name="Nexus Global Tech",
                description="Premium B2B electronics wholesaler specializing in processors and components",
                contact_email="nexus@example.com",
                business_category="Electronics",
            )
            db.add(profile_a)
            db.commit()
            logger.info("Merchant A (Nexus Global Tech) seeded.")

        # 3. Seed Merchant B: Apex Distributor
        merchant_b = db.query(models.User).filter(models.User.username == "apex_distributor").first()
        if not merchant_b:
            hashed_pwd = auth.get_password_hash("apex_distributor")
            merchant_b = models.User(username="apex_distributor", hashed_password=hashed_pwd, role="merchant")
            db.add(merchant_b)
            db.commit()
            db.refresh(merchant_b)

            profile_b = models.MerchantProfile(
                user_id=merchant_b.id,
                display_name="Apex Distributor",
                description="High-volume component distributor with competitive bulk pricing",
                contact_email="apex@example.com",
                business_category="Components",
            )
            db.add(profile_b)
            db.commit()
            logger.info("Merchant B (Apex Distributor) seeded.")

        # 4. Seed Inventory — overlapping SKUs across merchants to demonstrate multi-merchant
        nexus_items = [
            {"sku": "PROD-M4-CHIP", "name": "Apple M4 Processor Units", "stock": 1500, "base": 24000.0, "min": 19500.0, "velocity": 1.8},
            {"sku": "PROD-MEM-32G", "name": "Samsung LPDDR5 32GB RAM Module", "stock": 800, "base": 6500.0, "min": 5200.0, "velocity": 1.2},
            {"sku": "PROD-SSD-1TB", "name": "Kingston NVMe 1TB SSD", "stock": 120, "base": 4200.0, "min": 3600.0, "velocity": 0.8},
        ]

        apex_items = [
            {"sku": "PROD-M4-CHIP", "name": "Apple M4 Processor Units", "stock": 900, "base": 23500.0, "min": 19000.0, "velocity": 1.5},
            {"sku": "PROD-SSD-1TB", "name": "Kingston NVMe 1TB SSD", "stock": 500, "base": 4000.0, "min": 3400.0, "velocity": 1.0},
        ]

        # Helper to seed inventory for a merchant
        def seed_merchant_inventory(merchant_user, items):
            profile = db.query(models.MerchantProfile).filter(
                models.MerchantProfile.user_id == merchant_user.id
            ).first()
            display_name = profile.display_name if profile else merchant_user.username

            for item_data in items:
                exists = db.query(models.Inventory).filter(
                    models.Inventory.sku == item_data["sku"],
                    models.Inventory.merchant_id == merchant_user.id,
                ).first()
                if not exists:
                    db_item = models.Inventory(
                        sku=item_data["sku"],
                        name=item_data["name"],
                        current_stock=item_data["stock"],
                        base_price=item_data["base"],
                        minimum_margin_limit=item_data["min"],
                        demand_velocity=item_data["velocity"],
                        wholesaler_name=display_name,
                        merchant_id=merchant_user.id,
                    )
                    db.add(db_item)

        seed_merchant_inventory(merchant_a, nexus_items)
        seed_merchant_inventory(merchant_b, apex_items)
        db.commit()
        logger.info("Demo inventory catalog seeded (5 items across 2 merchants).")

        # Backfill transaction_number for any existing transactions where transaction_number is None
        unpopulated_txs = db.query(models.Transaction).filter(models.Transaction.transaction_number.is_(None)).all()
        for tx in unpopulated_txs:
            tx.transaction_number = f"NXS-{tx.id:04d}"
        if unpopulated_txs:
            db.commit()
            logger.info(f"Backfilled transaction_number for {len(unpopulated_txs)} existing transaction(s).")

    except Exception as e:
        logger.error(f"Error seeding DB: {str(e)}")


# =========================================================================
# AUTHENTICATION APIs
# =========================================================================

@app.post("/api/auth/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit(settings.AUTH_RATE_LIMIT_REGISTER)
def register(request: Request, user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    
    hashed_pwd = auth.get_password_hash(user.password)
    db_new_user = models.User(
        username=user.username,
        hashed_password=hashed_pwd,
        role=user.role
    )
    db.add(db_new_user)
    db.commit()
    db.refresh(db_new_user)

    # Auto-create MerchantProfile for merchant users
    if user.role == "merchant":
        profile = models.MerchantProfile(
            user_id=db_new_user.id,
            display_name=user.username.replace("_", " ").title(),  # Default display name
        )
        db.add(profile)
        db.commit()

    return db_new_user

@app.post("/api/auth/token", response_model=schemas.Token)
@limiter.limit(settings.AUTH_RATE_LIMIT_LOGIN)
def login_for_access_token(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
):
    normalized_username = form_data.username.strip().lower()

    # 1. Check account lockout state before touching password hash
    remaining_lockout = lockout_manager.check_lockout(normalized_username)
    if remaining_lockout is not None:
        minutes = max(1, (remaining_lockout + 59) // 60)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Account is temporarily locked due to excessive failed attempts. Please try again in {minutes} minute(s).",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = db.query(models.User).filter(models.User.username == form_data.username.strip()).first()
    if not user or not auth.verify_password(form_data.password, user.hashed_password):
        # Record failed attempt and trigger lockout if limit reached
        _, is_locked, remaining_secs = lockout_manager.record_failure(normalized_username)
        if is_locked and remaining_secs:
            minutes = max(1, (remaining_secs + 59) // 60)
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Account is temporarily locked due to excessive failed attempts. Please try again in {minutes} minute(s).",
                headers={"WWW-Authenticate": "Bearer"},
            )

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Reset any previous failed attempts on successful authentication
    lockout_manager.reset_attempts(normalized_username)

    access_token = auth.create_access_token(data={"sub": user.username})
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "role": user.role,
        "username": user.username
    }

@app.get("/api/auth/me", response_model=schemas.UserResponse)
def get_me(current_user: models.User = Depends(auth.get_current_user)):
    return current_user

@app.post("/api/auth/refresh", response_model=schemas.Token)
async def refresh_access_token(
    request: Request,
    db: Session = Depends(get_db)
):
    """
    Seamless background session refresh.
    Extracts existing token from Bearer header or JSON payload, verifies validity,
    and returns a fresh access token with a renewed expiration date.
    """
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header[7:].strip()

    if not token:
        try:
            body = await request.json()
            token = body.get("token") or body.get("access_token")
        except Exception:
            token = None

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No token provided for session refresh.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    refreshed = auth.refresh_user_token(token, db)
    if not refreshed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session is invalid or account no longer exists. Please sign in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return refreshed


# =========================================================================
# USER MANAGEMENT APIs
# =========================================================================

@app.get("/api/users", response_model=List[schemas.UserResponse])
def get_users(current_user: models.User = Depends(auth.get_current_user), db: Session = Depends(get_db)):
    # Restrict user retrieval to current authenticated user for privacy
    return [current_user]

@app.put("/api/users/{user_id}", response_model=schemas.UserResponse)
def update_user(
    user_id: int,
    user_update: schemas.UserUpdate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    # Authorization: Users can only modify their own profile
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to modify this user account.")

    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if user_update.role:
        db_user.role = user_update.role
    if user_update.password:
        db_user.hashed_password = auth.get_password_hash(user_update.password)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.delete("/api/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db)
):
    # Authorization: Users can only delete their own profile
    if current_user.id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized to delete this user account.")

    db_user = db.query(models.User).filter(models.User.id == user_id).first()
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    db.delete(db_user)
    db.commit()
    return None


# =========================================================================
# REAL-TIME WEBSOCKET APIs & EVENT DISPATCHER
# =========================================================================

async def notify_transaction_event(
    transaction: models.Transaction,
    event_type: str,
    extra_data: Optional[dict] = None
):
    """
    Publishes a real-time event to the transaction room and
    notifies the buyer and merchant dashboard channels.
    """
    try:
        data = {
            "transaction_id": transaction.id,
            "transaction_number": transaction.transaction_number or f"NXS-{transaction.id:04d}",
            "status": transaction.status,
            "final_price": transaction.final_price,
            "buyer_approved": transaction.buyer_approved,
            "merchant_approved": transaction.merchant_approved,
            "buyer_accepted": bool(transaction.buyer_approved == 1),
            "merchant_accepted": bool(transaction.merchant_approved == 1),
            "agreed_quote_id": transaction.agreed_quote_id,
            "sku": transaction.sku,
            "quantity": transaction.quantity,
            "buyer_id": transaction.buyer_id,
            "merchant_id": transaction.merchant_id,
        }
        if extra_data:
            data.update(extra_data)
        await realtime.manager.broadcast_to_transaction(
            transaction_id=transaction.id,
            event_type=event_type,
            data=data,
            buyer_id=transaction.buyer_id,
            merchant_id=transaction.merchant_id,
        )
    except Exception as e:
        logger.error(f"Failed to broadcast real-time event {event_type} for transaction #{transaction.id}: {e}")


@app.websocket("/api/ws/transactions/{transaction_id}")
async def websocket_transaction_channel(
    websocket: WebSocket,
    transaction_id: int,
    token: Optional[str] = Query(None),
):
    """
    WebSocket channel for real-time transaction updates.
    Enforces JWT authentication and authorization (buyer or merchant on this transaction).
    """
    if not token:
        await websocket.close(code=4401)
        return

    from .database import SessionLocal
    db = SessionLocal()
    try:
        user = auth.get_user_from_token(token, db)
        if not user:
            await websocket.close(code=4401)
            return

        transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
        if not transaction:
            await websocket.close(code=4404)
            return

        # Authorization: must be buyer or merchant on this transaction
        if transaction.buyer_id != user.id and transaction.merchant_id != user.id:
            logger.warning(f"Unauthorized WS attempt: User #{user.id} on transaction #{transaction_id}")
            await websocket.close(code=4403)
            return

        user_id = user.id
    finally:
        db.close()

    # Connect to room
    await realtime.manager.connect_transaction(websocket, transaction_id, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_text(json.dumps({
                        "event_type": realtime.EventType.HEARTBEAT,
                        "timestamp": datetime.utcnow().isoformat(),
                    }))
            except Exception:
                pass
    except WebSocketDisconnect:
        await realtime.manager.disconnect_transaction(websocket, transaction_id)
    except Exception as e:
        logger.warning(f"WS error on tx #{transaction_id}: {e}")
        await realtime.manager.disconnect_transaction(websocket, transaction_id)


@app.websocket("/api/ws/dashboard")
async def websocket_dashboard_channel(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
):
    """
    WebSocket channel for user dashboard feeds.
    Pushes transaction status changes live to buyer/merchant dashboard views.
    """
    if not token:
        await websocket.close(code=4401)
        return

    from .database import SessionLocal
    db = SessionLocal()
    try:
        user = auth.get_user_from_token(token, db)
        if not user:
            await websocket.close(code=4401)
            return
        user_id = user.id
    finally:
        db.close()

    await realtime.manager.connect_dashboard(websocket, user_id)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
                if msg.get("action") == "ping":
                    await websocket.send_text(json.dumps({
                        "event_type": realtime.EventType.HEARTBEAT,
                        "timestamp": datetime.utcnow().isoformat(),
                    }))
            except Exception:
                pass
    except WebSocketDisconnect:
        await realtime.manager.disconnect_dashboard(websocket, user_id)
    except Exception as e:
        logger.warning(f"WS error on dashboard for user #{user_id}: {e}")
        await realtime.manager.disconnect_dashboard(websocket, user_id)


# =========================================================================
# MERCHANT PROFILE APIs (Dynamic — supports N merchants)
# =========================================================================

@app.get("/api/merchants", response_model=List[schemas.MerchantProfileResponse])
def list_merchants(db: Session = Depends(get_db)):
    """List all active merchants with their profiles."""
    profiles = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.is_active == True
    ).all()
    result = []
    for p in profiles:
        user = db.query(models.User).filter(models.User.id == p.user_id).first()
        result.append(schemas.MerchantProfileResponse(
            id=p.id,
            user_id=p.user_id,
            display_name=p.display_name,
            description=p.description,
            contact_email=p.contact_email,
            business_category=p.business_category,
            is_active=p.is_active,
            username=user.username if user else None,
            created_at=p.created_at,
            updated_at=p.updated_at,
        ))
    return result

@app.get("/api/merchants/{merchant_id}", response_model=schemas.MerchantProfileResponse)
def get_merchant(merchant_id: int, db: Session = Depends(get_db)):
    """Get a single merchant's profile."""
    profile = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == merchant_id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Merchant profile not found")
    user = db.query(models.User).filter(models.User.id == profile.user_id).first()
    return schemas.MerchantProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        display_name=profile.display_name,
        description=profile.description,
        contact_email=profile.contact_email,
        business_category=profile.business_category,
        is_active=profile.is_active,
        username=user.username if user else None,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )

@app.post("/api/merchants/profile", response_model=schemas.MerchantProfileResponse)
def create_or_update_merchant_profile(
    profile_data: schemas.MerchantProfileCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Create or update the logged-in merchant's profile."""
    if current_user.role != "merchant":
        raise HTTPException(status_code=403, detail="Only merchants can manage their profile.")

    existing = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == current_user.id
    ).first()

    if existing:
        existing.display_name = profile_data.display_name
        if profile_data.description is not None:
            existing.description = profile_data.description
        if profile_data.contact_email is not None:
            existing.contact_email = profile_data.contact_email
        if profile_data.business_category is not None:
            existing.business_category = profile_data.business_category
        db.commit()
        db.refresh(existing)
        profile = existing
    else:
        profile = models.MerchantProfile(
            user_id=current_user.id,
            display_name=profile_data.display_name,
            description=profile_data.description,
            contact_email=profile_data.contact_email,
            business_category=profile_data.business_category,
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)

    return schemas.MerchantProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        display_name=profile.display_name,
        description=profile.description,
        contact_email=profile.contact_email,
        business_category=profile.business_category,
        is_active=profile.is_active,
        username=current_user.username,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


# =========================================================================
# INVENTORY APIs (Merchant-scoped)
# =========================================================================

def _enrich_inventory_response(item: models.Inventory, db: Session) -> schemas.InventoryResponse:
    """Adds dynamic merchant_name and available_stock to inventory response."""
    profile = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == item.merchant_id
    ).first()
    return schemas.InventoryResponse(
        id=item.id,
        sku=item.sku,
        name=item.name,
        current_stock=item.current_stock,
        reserved_stock=item.reserved_stock,
        available_stock=max(0, item.current_stock - item.reserved_stock),
        base_price=item.base_price,
        minimum_margin_limit=item.minimum_margin_limit,
        demand_velocity=item.demand_velocity,
        wholesaler_name=item.wholesaler_name,
        merchant_id=item.merchant_id,
        merchant_name=profile.display_name if profile else item.wholesaler_name,
        created_at=item.created_at,
    )

@app.get("/api/inventory", response_model=List[schemas.InventoryResponse])
def get_inventory(db: Session = Depends(get_db)):
    """Returns all inventory with merchant names. Same SKU from different merchants appears as separate listings."""
    items = db.query(models.Inventory).all()
    return [_enrich_inventory_response(item, db) for item in items]

@app.post("/api/inventory", response_model=schemas.InventoryResponse, status_code=status.HTTP_201_CREATED)
async def add_inventory(
    item: schemas.InventoryCreate,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Adds inventory for the logged-in merchant. wholesaler_name auto-set from MerchantProfile."""
    if current_user.role != "merchant":
        raise HTTPException(status_code=403, detail="Only merchants can add inventory items")

    # Check for duplicate SKU within THIS merchant only (not globally)
    existing = db.query(models.Inventory).filter(
        models.Inventory.sku == item.sku,
        models.Inventory.merchant_id == current_user.id,
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="You already have this SKU in your inventory.")

    # Auto-populate wholesaler_name from MerchantProfile
    profile = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == current_user.id
    ).first()
    display_name = profile.display_name if profile else current_user.username

    db_new_item = models.Inventory(
        sku=item.sku,
        name=item.name,
        current_stock=item.current_stock,
        base_price=item.base_price,
        minimum_margin_limit=item.minimum_margin_limit,
        demand_velocity=item.demand_velocity,
        wholesaler_name=display_name,
        merchant_id=current_user.id,
    )
    db.add(db_new_item)
    db.commit()
    db.refresh(db_new_item)

    # Broadcast new listing to all dashboards in real time
    await realtime.manager.broadcast_all_dashboards(
        realtime.EventType.INVENTORY_UPDATED,
        {
            "inventory_id": db_new_item.id,
            "sku": db_new_item.sku,
            "name": db_new_item.name,
            "merchant_id": db_new_item.merchant_id,
            "merchant_name": display_name,
            "current_stock": db_new_item.current_stock,
            "reserved_stock": 0,
            "available_stock": db_new_item.current_stock,
            "is_out_of_stock": db_new_item.current_stock <= 0,
        }
    )

    return _enrich_inventory_response(db_new_item, db)


@app.post("/api/inventory/{inventory_id}/remove")
async def remove_inventory(
    inventory_id: int,
    req: schemas.InventoryRemoveRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Allows a merchant to remove units from their own listing.
    Validates that units_to_remove does not exceed available_stock.
    Marks Out of Stock if stock reaches 0.
    Optionally deletes listing if stock reaches 0 and delete_if_zero=True.
    Broadcasts real-time update to all dashboards.
    """
    if current_user.role != "merchant":
        raise HTTPException(status_code=403, detail="Only merchants can manage inventory listings.")

    try:
        item = db.query(models.Inventory).filter(
            models.Inventory.id == inventory_id
        ).with_for_update().first()
    except Exception:
        item = db.query(models.Inventory).filter(models.Inventory.id == inventory_id).first()

    if not item:
        raise HTTPException(status_code=404, detail="Inventory listing not found.")

    if item.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this inventory listing.")

    available = max(0, item.current_stock - item.reserved_stock)
    if req.units_to_remove > available:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot remove {req.units_to_remove} units. Only {available} units are currently available ({item.reserved_stock} units are reserved by active buyer orders)."
        )

    item.current_stock = max(0, item.current_stock - req.units_to_remove)
    remaining_available = max(0, item.current_stock - item.reserved_stock)

    profile = db.query(models.MerchantProfile).filter(models.MerchantProfile.user_id == item.merchant_id).first()
    merchant_name = profile.display_name if profile else item.wholesaler_name

    if item.current_stock == 0 and req.delete_if_zero and item.reserved_stock == 0:
        db.delete(item)
        db.commit()

        # Broadcast deletion to all dashboards
        await realtime.manager.broadcast_all_dashboards(
            realtime.EventType.INVENTORY_DELETED,
            {
                "inventory_id": inventory_id,
                "merchant_id": current_user.id,
                "is_deleted": True,
            }
        )
        return {
            "status": "deleted",
            "message": f"All units removed. Listing {inventory_id} has been permanently deleted.",
            "inventory_id": inventory_id,
        }

    db.commit()
    db.refresh(item)

    # Broadcast updated stock to all dashboards
    await realtime.manager.broadcast_all_dashboards(
        realtime.EventType.INVENTORY_UPDATED,
        {
            "inventory_id": item.id,
            "sku": item.sku,
            "name": item.name,
            "merchant_id": item.merchant_id,
            "merchant_name": merchant_name,
            "current_stock": item.current_stock,
            "reserved_stock": item.reserved_stock,
            "available_stock": remaining_available,
            "is_out_of_stock": remaining_available <= 0,
        }
    )

    return _enrich_inventory_response(item, db)


@app.delete("/api/inventory/{inventory_id}")
async def delete_inventory(
    inventory_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Permanently deletes an inventory listing.
    Fails if active buyer reservations exist.
    """
    if current_user.role != "merchant":
        raise HTTPException(status_code=403, detail="Only merchants can delete inventory listings.")

    item = db.query(models.Inventory).filter(models.Inventory.id == inventory_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory listing not found.")

    if item.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="You do not own this inventory listing.")

    if item.reserved_stock > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete listing: {item.reserved_stock} units are currently reserved by active buyer orders. Wait for orders to complete or expire."
        )

    db.delete(item)
    db.commit()

    # Broadcast deletion to all dashboards
    await realtime.manager.broadcast_all_dashboards(
        realtime.EventType.INVENTORY_DELETED,
        {
            "inventory_id": inventory_id,
            "merchant_id": current_user.id,
            "is_deleted": True,
        }
    )

    return {"status": "deleted", "inventory_id": inventory_id}



# =========================================================================
# NEGOTIATION APIs (Single + Multi-Merchant)
# =========================================================================

@app.post("/api/negotiate", response_model=schemas.NegotiationStatusResponse)
async def initiate_negotiation(
    req: schemas.NegotiationRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Single-merchant negotiation. Requires inventory_id to identify the exact merchant listing."""
    if current_user.role != "buyer":
        raise HTTPException(status_code=403, detail="Only buyer users can initiate procurement bids.")

    # Look up the specific inventory listing
    item = db.query(models.Inventory).filter(models.Inventory.id == req.inventory_id).first()
    if not item:
        raise HTTPException(status_code=404, detail="Inventory listing not found.")
    if item.sku != req.sku:
        raise HTTPException(status_code=400, detail="SKU mismatch with inventory listing.")

    # The merchant is determined by the inventory listing — not picked arbitrarily
    merchant = db.query(models.User).filter(models.User.id == item.merchant_id).first()
    if not merchant:
        raise HTTPException(status_code=500, detail="Merchant for this listing not found.")

    # Create transaction
    transaction = models.Transaction(
        sku=req.sku,
        quantity=req.quantity,
        buyer_id=current_user.id,
        merchant_id=merchant.id,
        inventory_id=item.id,
        status=models.TransactionStatus.NEGOTIATING,
    )
    db.add(transaction)
    db.flush()
    if not transaction.transaction_number:
        transaction.transaction_number = f"NXS-{transaction.id:04d}"
    db.commit()
    db.refresh(transaction)

    # Run negotiation in non-blocking thread pool so event loop and WebSockets stay 100% active
    bind_engine = db.get_bind()
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=bind_engine)

    def _run_single_orch(tx_id: int, budget: float):
        local_db = session_factory()
        try:
            orch = NegotiationOrchestrator(local_db)
            return orch.run_negotiation(tx_id, budget)
        finally:
            local_db.close()

    is_sqlite_memory = (":memory:" in str(bind_engine.url))
    if is_sqlite_memory:
        _run_single_orch(transaction.id, req.buyer_max_budget)
    else:
        await asyncio.to_thread(_run_single_orch, transaction.id, req.buyer_max_budget)

    db.refresh(transaction)
    await notify_transaction_event(transaction, realtime.EventType.NEGOTIATION_UPDATED)
    await notify_transaction_event(transaction, realtime.EventType.TRANSACTION_STATUS_CHANGED)

    logs = db.query(models.AuditLog).filter(
        models.AuditLog.transaction_id == transaction.id
    ).order_by(models.AuditLog.timestamp.asc()).all()

    return {
        "transaction_id": transaction.id,
        "transaction_number": transaction.transaction_number or f"NXS-{transaction.id:04d}",
        "status": transaction.status,
        "final_price": transaction.final_price,
        "logs": logs,
    }

@app.post("/api/negotiate/multi", response_model=schemas.MultiNegotiationResponse)
async def initiate_multi_negotiation(
    req: schemas.MultiNegotiationRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Parallel negotiation with ALL merchants offering this SKU.
    Executes all merchant negotiations concurrently for sub-second responses.
    """
    if current_user.role != "buyer":
        raise HTTPException(status_code=403, detail="Only buyer users can initiate procurement bids.")

    # Find all inventory listings for this SKU with available stock
    listings = db.query(models.Inventory).filter(
        models.Inventory.sku == req.sku,
        models.Inventory.current_stock > models.Inventory.reserved_stock,
    ).all()

    if not listings:
        raise HTTPException(status_code=404, detail=f"No merchants found offering SKU '{req.sku}' with available stock.")

    bind_engine = db.get_bind()
    session_factory = sessionmaker(autocommit=False, autoflush=False, bind=bind_engine)

    def _negotiate_single_listing(listing_id: int, buyer_user_id: int, sku: str, quantity: int, buyer_budget: float):
        local_db = session_factory()
        try:
            item = local_db.query(models.Inventory).filter(models.Inventory.id == listing_id).first()
            if not item:
                return None

            tx = models.Transaction(
                sku=sku,
                quantity=quantity,
                buyer_id=buyer_user_id,
                merchant_id=item.merchant_id,
                inventory_id=item.id,
                status=models.TransactionStatus.NEGOTIATING,
            )
            local_db.add(tx)
            local_db.flush()
            if not tx.transaction_number:
                tx.transaction_number = f"NXS-{tx.id:04d}"
            local_db.commit()
            local_db.refresh(tx)

            orch = NegotiationOrchestrator(local_db)
            orch.run_negotiation(tx.id, buyer_budget)
            local_db.refresh(tx)

            profile = local_db.query(models.MerchantProfile).filter(
                models.MerchantProfile.user_id == item.merchant_id
            ).first()

            logs = local_db.query(models.AuditLog).filter(
                models.AuditLog.transaction_id == tx.id
            ).order_by(models.AuditLog.timestamp.asc()).all()

            return schemas.MerchantOfferResponse(
                merchant_id=item.merchant_id,
                merchant_name=profile.display_name if profile else item.wholesaler_name,
                inventory_id=item.id,
                transaction_id=tx.id,
                transaction_number=tx.transaction_number or f"NXS-{tx.id:04d}",
                status=tx.status,
                final_price=tx.final_price,
                available_stock=max(0, item.current_stock - item.reserved_stock),
                logs=logs,
            )
        finally:
            local_db.close()

    # Execute all merchant negotiations concurrently in parallel threads (or safely serialized for in-memory SQLite)
    is_sqlite_memory = (":memory:" in str(bind_engine.url))
    if is_sqlite_memory:
        raw_offers = [_negotiate_single_listing(item.id, current_user.id, req.sku, req.quantity, req.buyer_max_budget) for item in listings]
    else:
        tasks = [
            asyncio.to_thread(
                _negotiate_single_listing,
                item.id,
                current_user.id,
                req.sku,
                req.quantity,
                req.buyer_max_budget,
            )
            for item in listings
        ]
        raw_offers = await asyncio.gather(*tasks)
    offers = [o for o in raw_offers if o is not None]

    # Notify events for all generated transactions
    for offer in offers:
        tx = db.query(models.Transaction).filter(models.Transaction.id == offer.transaction_id).first()
        if tx:
            await notify_transaction_event(tx, realtime.EventType.NEGOTIATION_UPDATED)
            await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED)

    # Find best offer (lowest agreed price)
    valid_agreed_states = (
        models.TransactionStatus.AI_NEGOTIATION_COMPLETED,
        models.TransactionStatus.MUTUALLY_APPROVED,
        "ai_negotiation_completed",
        "mutually_approved",
        "agreed",
        "quote_agreed",
    )
    agreed_offers = [o for o in offers if o.status in valid_agreed_states and o.final_price]
    best_id = None
    if agreed_offers:
        best = min(agreed_offers, key=lambda o: o.final_price)
        best_id = best.transaction_id

    return schemas.MultiNegotiationResponse(
        sku=req.sku,
        offers=offers,
        best_offer_transaction_id=best_id,
    )


# =========================================================================
# DUAL-HUMAN APPROVAL
# =========================================================================

# =========================================================================
# DUAL-HUMAN APPROVAL & QUOTE LIFECYCLE (Human-in-the-Loop)
# =========================================================================

@app.post("/api/transactions/{transaction_id}/approve")
async def approve_transaction(
    transaction_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Independent human approval of the negotiated / agreed price.
    Transitions:
      - First approver -> AWAITING_BUYER_APPROVAL or AWAITING_MERCHANT_APPROVAL
      - Both approvers -> MUTUALLY_APPROVED (unlocks Razorpay payment)
    """
    transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    
    valid_approval_statuses = (
        models.TransactionStatus.AI_NEGOTIATION_COMPLETED,
        models.TransactionStatus.AWAITING_BUYER_APPROVAL,
        models.TransactionStatus.AWAITING_MERCHANT_APPROVAL,
        models.TransactionStatus.MUTUALLY_APPROVED,
        "ai_negotiation_completed",
        "awaiting_buyer_approval",
        "awaiting_merchant_approval",
        "agreed",
        "quote_agreed",
        "approved",
    )
    if transaction.status not in valid_approval_statuses:
        raise HTTPException(status_code=400, detail=f"Transaction is not awaiting approval. Current status: '{transaction.status}'.")

    # Block approval if a manual revised quote is pending (must accept or reject that proposal instead)
    pending_manual_quote = db.query(models.Quote).filter(
        models.Quote.transaction_id == transaction.id,
        models.Quote.source != models.QuoteSource.AI_NEGOTIATION,
        models.Quote.status == models.QuoteStatus.PENDING,
    ).first()
    if pending_manual_quote:
        raise HTTPException(status_code=400, detail="A revised quote is currently pending. Please accept or reject that proposal.")

    # Target quote: active agreed quote or latest quote
    target_quote = None
    if transaction.agreed_quote_id:
        target_quote = db.query(models.Quote).filter(models.Quote.id == transaction.agreed_quote_id).first()
    if not target_quote:
        target_quote = db.query(models.Quote).filter(models.Quote.transaction_id == transaction.id).order_by(models.Quote.id.desc()).first()

    if current_user.role == "buyer" and transaction.buyer_id == current_user.id:
        transaction.buyer_approved = 1
        if target_quote:
            target_quote.buyer_accepted = True
        actor_label = "Human Buyer"
        log_msg = f"Buyer accepted and approved the price of ₹{transaction.final_price:,.2f}."
    elif current_user.role == "merchant" and transaction.merchant_id == current_user.id:
        transaction.merchant_approved = 1
        if target_quote:
            target_quote.merchant_accepted = True
        actor_label = "Human Merchant"
        log_msg = f"Merchant accepted and approved the price of ₹{transaction.final_price:,.2f}."
    else:
        raise HTTPException(status_code=403, detail="Unauthorized to approve this transaction.")

    db.add(models.AuditLog(transaction_id=transaction.id, actor=actor_label, message=log_msg))

    # Evaluate mutual consensus: ONLY when BOTH buyer and merchant have explicitly accepted
    if transaction.buyer_approved == 1 and transaction.merchant_approved == 1:
        transaction.status = models.TransactionStatus.MUTUALLY_APPROVED
        if target_quote:
            target_quote.status = models.QuoteStatus.ACCEPTED
            target_quote.accepted_at = datetime.utcnow()
            transaction.agreed_quote_id = target_quote.id
        from .agents.orchestrator import generate_cart_mandate
        transaction.cryptographic_signature = generate_cart_mandate(
            transaction.sku, transaction.quantity, transaction.final_price,
            merchant_id=transaction.merchant_id,
            inventory_id=transaction.inventory_id
        )
        db.add(models.AuditLog(
            transaction_id=transaction.id,
            actor="System Orchestrator",
            message=(
                f"Dual-human mutual agreement completed! Both Buyer and Merchant approved ₹{transaction.final_price:,.2f}. "
                f"Mutually agreed price locked. Razorpay payment enabled."
            )
        ))
    elif transaction.buyer_approved == 1:
        transaction.status = models.TransactionStatus.AWAITING_MERCHANT_APPROVAL
        if target_quote:
            target_quote.status = models.QuoteStatus.PENDING
    elif transaction.merchant_approved == 1:
        transaction.status = models.TransactionStatus.AWAITING_BUYER_APPROVAL
        if target_quote:
            target_quote.status = models.QuoteStatus.PENDING

    db.commit()
    db.refresh(transaction)
    if target_quote:
        db.refresh(target_quote)

    quote_dict = None
    if target_quote:
        quote_dict = {
            "id": target_quote.id,
            "amount": target_quote.amount,
            "proposed_by": target_quote.proposed_by,
            "source": target_quote.source,
            "status": target_quote.status,
            "merchant_accepted": target_quote.merchant_accepted,
            "buyer_accepted": target_quote.buyer_accepted,
            "note": target_quote.note,
        }
    extra = {"quote": quote_dict} if quote_dict else {}

    await notify_transaction_event(transaction, realtime.EventType.PRICE_ACCEPTED, extra)
    await notify_transaction_event(transaction, realtime.EventType.TRANSACTION_STATUS_CHANGED, extra)

    return {
        "transaction_id": transaction.id,
        "status": transaction.status,
        "buyer_approved": transaction.buyer_approved,
        "merchant_approved": transaction.merchant_approved,
        "buyer_accepted": bool(transaction.buyer_approved == 1),
        "merchant_accepted": bool(transaction.merchant_approved == 1),
    }


@app.post("/api/transactions/{transaction_id}/quotes", response_model=schemas.QuoteResponse)
async def propose_revised_quote(
    transaction_id: int,
    req: schemas.QuoteCreateRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Propose a manual revised quote (Human Override).
    AI plays NO role in this stage.
    Proposer is auto-approved; counter-party approval is reset to pending.
    Payment is locked while revision is in progress.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    is_buyer = (tx.buyer_id == current_user.id)
    is_merchant = (tx.merchant_id == current_user.id)
    if not (is_buyer or is_merchant):
        raise HTTPException(status_code=403, detail="Unauthorized to propose quotes on this transaction.")

    # Block proposing quotes if payment initiated, paid, or terminated
    blocked_statuses = (
        models.TransactionStatus.PAYMENT_INITIATED,
        models.TransactionStatus.COMPLETED,
        models.TransactionStatus.TERMINATED,
        "paid",
        "completed",
        "failed",
        "terminated",
        "payment_initiated",
    )
    if tx.status in blocked_statuses:
        raise HTTPException(status_code=400, detail=f"Cannot propose revised quote when transaction is in '{tx.status}' state.")

    if req.amount <= 0:
        raise HTTPException(status_code=400, detail="Quote amount must be greater than zero.")

    inventory = db.query(models.Inventory).filter(models.Inventory.id == tx.inventory_id).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory listing not found.")

    # Guardrail: Merchant CANNOT propose below their confidential floor price
    if is_merchant and req.amount < inventory.minimum_margin_limit:
        raise HTTPException(
            status_code=422,
            detail=f"Cannot propose quote below merchant minimum price (₹{inventory.minimum_margin_limit:,.2f})."
        )

    if is_buyer:
        proposed_by = "BUYER"
        source = models.QuoteSource.MANUAL_BUYER
        buyer_accepted = True
        merchant_accepted = None
        actor_label = "Human Buyer"
    else:
        proposed_by = "MERCHANT"
        source = models.QuoteSource.MANUAL_MERCHANT
        merchant_accepted = True
        buyer_accepted = None
        actor_label = "Human Merchant"

    # Supersede any previous pending or accepted quotes on this transaction
    existing_pendings = db.query(models.Quote).filter(
        models.Quote.transaction_id == tx.id,
        models.Quote.status == models.QuoteStatus.PENDING
    ).all()
    for ep in existing_pendings:
        ep.status = models.QuoteStatus.SUPERSEDED

    prior_accepted = db.query(models.Quote).filter(
        models.Quote.transaction_id == tx.id,
        models.Quote.status == models.QuoteStatus.ACCEPTED
    ).all()
    for pa in prior_accepted:
        pa.status = models.QuoteStatus.SUPERSEDED

    # Create new Quote record with independent acceptance
    new_quote = models.Quote(
        transaction_id=tx.id,
        amount=round(req.amount, 2),
        proposed_by=proposed_by,
        source=source,
        merchant_accepted=merchant_accepted,
        buyer_accepted=buyer_accepted,
        status=models.QuoteStatus.PENDING,
        note=req.note,
        created_at=datetime.utcnow()
    )
    db.add(new_quote)
    db.flush()

    # Move transaction to AWAITING counter-party approval
    # Resets counter-party acceptance to 0
    tx.final_price = round(req.amount, 2)
    tx.agreed_quote_id = new_quote.id
    if is_buyer:
        tx.buyer_approved = 1
        tx.merchant_approved = 0
        tx.status = models.TransactionStatus.AWAITING_MERCHANT_APPROVAL
    else:
        tx.merchant_approved = 1
        tx.buyer_approved = 0
        tx.status = models.TransactionStatus.AWAITING_BUYER_APPROVAL
    
    note_text = f" Note: '{req.note}'" if req.note else ""
    log = models.AuditLog(
        transaction_id=tx.id,
        actor=actor_label,
        message=f"{actor_label} proposed revised quote #{new_quote.id} at ₹{req.amount:,.2f}.{note_text} Awaiting counter-party decision."
    )
    db.add(log)
    db.commit()
    db.refresh(new_quote)
    db.refresh(tx)

    quote_dict = {
        "id": new_quote.id,
        "amount": new_quote.amount,
        "proposed_by": new_quote.proposed_by,
        "source": new_quote.source,
        "status": new_quote.status,
        "merchant_accepted": new_quote.merchant_accepted,
        "buyer_accepted": new_quote.buyer_accepted,
        "note": new_quote.note,
    }
    await notify_transaction_event(tx, realtime.EventType.QUOTE_UPDATED, {"quote": quote_dict, "active_quote_id": new_quote.id})
    await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED, {"quote": quote_dict, "active_quote_id": new_quote.id})

    return schemas.QuoteResponse.from_orm(new_quote)


@app.post("/api/transactions/{transaction_id}/quotes/{quote_id}/accept", response_model=schemas.QuoteResponse)
async def accept_revised_quote(
    transaction_id: int,
    quote_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Accept an active revised quote.
    Only counter-party can accept.
    Once accepted by both sides, transaction updates to MUTUALLY_APPROVED and payment unlocks.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    quote = db.query(models.Quote).filter(
        models.Quote.id == quote_id,
        models.Quote.transaction_id == transaction_id
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if quote.status != models.QuoteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Quote cannot be accepted because status is '{quote.status}'.")

    is_buyer = (tx.buyer_id == current_user.id)
    is_merchant = (tx.merchant_id == current_user.id)
    if not (is_buyer or is_merchant):
        raise HTTPException(status_code=403, detail="Unauthorized.")

    # Proposer CANNOT accept their own quote
    if (quote.proposed_by == "BUYER" and is_buyer) or (quote.proposed_by == "MERCHANT" and is_merchant):
        raise HTTPException(status_code=400, detail="Cannot accept your own proposal. Awaiting counter-party response.")

    inventory = db.query(models.Inventory).filter(models.Inventory.id == tx.inventory_id).first()
    if not inventory:
        raise HTTPException(status_code=404, detail="Inventory listing not found.")

    # Guardrail: Merchant CANNOT accept an offer below confidential floor
    if is_merchant and quote.amount < inventory.minimum_margin_limit:
        raise HTTPException(
            status_code=422,
            detail="Below minimum acceptable price. Reject or counter with another quote."
        )

    # Set independent acceptor flag
    if is_buyer:
        quote.buyer_accepted = True
        tx.buyer_approved = 1
        actor_label = "Human Buyer"
    else:
        quote.merchant_accepted = True
        tx.merchant_approved = 1
        actor_label = "Human Merchant"

    # Both parties must explicitly accept this exact quote before MUTUALLY_APPROVED
    both_accepted = (quote.buyer_accepted is True and quote.merchant_accepted is True)

    if both_accepted:
        quote.status = models.QuoteStatus.ACCEPTED
        quote.accepted_at = datetime.utcnow()
        tx.agreed_quote_id = quote.id
        tx.final_price = quote.amount
        tx.buyer_approved = 1
        tx.merchant_approved = 1
        tx.status = models.TransactionStatus.MUTUALLY_APPROVED

        # Regenerate cryptographic cart mandate for newly agreed price
        from .agents.orchestrator import generate_cart_mandate
        tx.cryptographic_signature = generate_cart_mandate(
            tx.sku, tx.quantity, quote.amount,
            merchant_id=tx.merchant_id,
            inventory_id=tx.inventory_id
        )

        log = models.AuditLog(
            transaction_id=tx.id,
            actor=actor_label,
            message=f"{actor_label} accepted quote #{quote.id} at ₹{quote.amount:,.2f}. Both Buyer and Merchant have accepted! Mutually agreed price locked."
        )
    elif is_buyer:
        quote.status = models.QuoteStatus.PENDING
        tx.agreed_quote_id = quote.id
        tx.final_price = quote.amount
        tx.buyer_approved = 1
        tx.merchant_approved = 0
        tx.status = models.TransactionStatus.AWAITING_MERCHANT_APPROVAL
        log = models.AuditLog(
            transaction_id=tx.id,
            actor=actor_label,
            message=f"Buyer accepted quote #{quote.id} at ₹{quote.amount:,.2f}. Accepted by Buyer only — awaiting independent Merchant acceptance."
        )
    else:  # is_merchant
        quote.status = models.QuoteStatus.PENDING
        tx.agreed_quote_id = quote.id
        tx.final_price = quote.amount
        tx.merchant_approved = 1
        tx.buyer_approved = 0
        tx.status = models.TransactionStatus.AWAITING_BUYER_APPROVAL
        log = models.AuditLog(
            transaction_id=tx.id,
            actor=actor_label,
            message=f"Merchant accepted quote #{quote.id} at ₹{quote.amount:,.2f}. Accepted by Merchant only — awaiting independent Buyer acceptance."
        )

    db.add(log)
    db.commit()
    db.refresh(quote)
    db.refresh(tx)

    quote_dict = {
        "id": quote.id,
        "amount": quote.amount,
        "proposed_by": quote.proposed_by,
        "source": quote.source,
        "status": quote.status,
        "merchant_accepted": quote.merchant_accepted,
        "buyer_accepted": quote.buyer_accepted,
        "note": quote.note,
    }
    await notify_transaction_event(tx, realtime.EventType.PRICE_ACCEPTED, {"quote": quote_dict, "agreed_quote_id": quote.id})
    await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED, {"quote": quote_dict, "agreed_quote_id": quote.id})

    return schemas.QuoteResponse.from_orm(quote)


@app.post("/api/transactions/{transaction_id}/quotes/{quote_id}/reject", response_model=schemas.QuoteActionResponse)
async def reject_revised_quote(
    transaction_id: int,
    quote_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Reject an active revised quote.
    Reverts to the prior mutually ACCEPTED quote so payment remains available on the earlier agreed price,
    or keeps transaction in revision state if no prior accepted quote exists.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    quote = db.query(models.Quote).filter(
        models.Quote.id == quote_id,
        models.Quote.transaction_id == transaction_id
    ).first()
    if not quote:
        raise HTTPException(status_code=404, detail="Quote not found")

    if quote.status != models.QuoteStatus.PENDING:
        raise HTTPException(status_code=400, detail=f"Quote cannot be rejected because status is '{quote.status}'.")

    is_buyer = (tx.buyer_id == current_user.id)
    is_merchant = (tx.merchant_id == current_user.id)
    if not (is_buyer or is_merchant):
        raise HTTPException(status_code=403, detail="Unauthorized.")

    # Proposer cannot reject their own quote
    if (quote.proposed_by == "BUYER" and is_buyer) or (quote.proposed_by == "MERCHANT" and is_merchant):
        raise HTTPException(status_code=400, detail="Cannot reject your own proposal.")

    actor_label = "Human Buyer" if is_buyer else "Human Merchant"

    # Mark quote rejected
    quote.status = models.QuoteStatus.REJECTED
    if is_buyer:
        quote.buyer_accepted = False
    else:
        quote.merchant_accepted = False

    # Find previous ACCEPTED quote for this transaction (excluding this one)
    prev_accepted = db.query(models.Quote).filter(
        models.Quote.transaction_id == tx.id,
        models.Quote.status == models.QuoteStatus.ACCEPTED,
        models.Quote.id != quote.id
    ).order_by(models.Quote.id.desc()).first()

    from .agents.orchestrator import generate_cart_mandate
    if prev_accepted:
        tx.agreed_quote_id = prev_accepted.id
        tx.final_price = prev_accepted.amount
        tx.buyer_approved = 1 if prev_accepted.buyer_accepted else 0
        tx.merchant_approved = 1 if prev_accepted.merchant_accepted else 0
        tx.status = models.TransactionStatus.MUTUALLY_APPROVED if (tx.buyer_approved == 1 and tx.merchant_approved == 1) else models.TransactionStatus.AI_NEGOTIATION_COMPLETED
        tx.cryptographic_signature = generate_cart_mandate(
            tx.sku, tx.quantity, prev_accepted.amount,
            merchant_id=tx.merchant_id,
            inventory_id=tx.inventory_id
        )
        restore_msg = f"Reverted settlement price to prior agreed quote #{prev_accepted.id} (₹{prev_accepted.amount:,.2f})."
    else:
        tx.buyer_approved = 0
        tx.merchant_approved = 0
        tx.status = models.TransactionStatus.MANUAL_REVISION_IN_PROGRESS
        restore_msg = "Quote rejected. You may submit a counter quote or terminate the transaction."

    log = models.AuditLog(
        transaction_id=tx.id,
        actor=actor_label,
        message=f"{actor_label} rejected revised quote #{quote.id} (₹{quote.amount:,.2f}). {restore_msg}"
    )
    db.add(log)
    db.commit()

    quote_dict = {
        "id": quote.id,
        "amount": quote.amount,
        "proposed_by": quote.proposed_by,
        "source": quote.source,
        "status": quote.status,
        "note": quote.note,
    }
    await notify_transaction_event(tx, realtime.EventType.QUOTE_UPDATED, {"quote": quote_dict, "rejected_quote_id": quote.id})
    await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED)

    return schemas.QuoteActionResponse(
        status="rejected",
        quote=schemas.QuoteResponse.from_orm(quote),
        message=f"Quote rejected. {restore_msg}"
    )


@app.post("/api/transactions/{transaction_id}/terminate")
async def terminate_transaction(
    transaction_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Explicitly terminate a negotiation session (State 9).
    Permanently locks price editing and payment.
    """
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")

    is_buyer = (tx.buyer_id == current_user.id)
    is_merchant = (tx.merchant_id == current_user.id)
    if not (is_buyer or is_merchant):
        raise HTTPException(status_code=403, detail="Unauthorized.")

    if tx.status in (models.TransactionStatus.COMPLETED, "paid"):
        raise HTTPException(status_code=400, detail="Cannot terminate an already completed transaction.")

    tx.status = models.TransactionStatus.TERMINATED

    # Mark pending quotes as expired
    pending_quotes = db.query(models.Quote).filter(
        models.Quote.transaction_id == tx.id,
        models.Quote.status == models.QuoteStatus.PENDING
    ).all()
    for pq in pending_quotes:
        pq.status = models.QuoteStatus.EXPIRED

    actor_label = "Human Buyer" if is_buyer else "Human Merchant"
    log = models.AuditLog(
        transaction_id=tx.id,
        actor=actor_label,
        message=f"{actor_label} terminated the negotiation. Transaction permanently closed (TERMINATED)."
    )
    db.add(log)
    db.commit()
    db.refresh(tx)

    await notify_transaction_event(tx, realtime.EventType.TRANSACTION_TERMINATED)
    await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED)

    return {"status": "terminated", "transaction_id": tx.id}


@app.get("/api/transactions/{transaction_id}/quotes", response_model=List[schemas.QuoteResponse])
def get_transaction_quotes(
    transaction_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns the full chronological quote negotiation history for a transaction."""
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.buyer_id != current_user.id and tx.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized")

    quotes = db.query(models.Quote).filter(
        models.Quote.transaction_id == transaction_id
    ).order_by(models.Quote.created_at.asc()).all()
    return [schemas.QuoteResponse.from_orm(q) for q in quotes]



# =========================================================================
# ORDER APIs (Payment lifecycle)
# =========================================================================

@app.post("/api/orders", response_model=schemas.OrderResponse)
async def create_order(
    req: schemas.OrderCreateRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Buyer accepts negotiation → creates Order + reserves inventory."""
    if current_user.role != "buyer":
        raise HTTPException(status_code=403, detail="Only buyers can create orders.")
    try:
        order = PaymentService.create_order(req.negotiation_id, current_user.id, db)
        tx = db.query(models.Transaction).filter(models.Transaction.id == req.negotiation_id).first()
        if tx:
            await notify_transaction_event(tx, realtime.EventType.PAYMENT_INITIATED, {
                "order_id": order.id,
                "total_amount": order.total_amount,
            })
            await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED)
        return _enrich_order_response(order, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/orders", response_model=List[schemas.OrderResponse])
def list_orders(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """List orders for the current user (role-scoped)."""
    if current_user.role == "buyer":
        orders = db.query(models.Order).filter(
            models.Order.buyer_id == current_user.id
        ).order_by(models.Order.created_at.desc()).all()
    elif current_user.role == "merchant":
        orders = db.query(models.Order).filter(
            models.Order.merchant_id == current_user.id
        ).order_by(models.Order.created_at.desc()).all()
    else:
        orders = db.query(models.Order).order_by(models.Order.created_at.desc()).all()
    return [_enrich_order_response(o, db) for o in orders]

@app.get("/api/orders/{order_id}", response_model=schemas.OrderResponse)
def get_order(
    order_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    if current_user.role == "buyer" and order.buyer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this order.")
    if current_user.role == "merchant" and order.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized to view this order.")
    return _enrich_order_response(order, db)


def _enrich_order_response(order: models.Order, db: Session) -> schemas.OrderResponse:
    """Adds dynamic merchant_name and item details to order response."""
    profile = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == order.merchant_id
    ).first()
    inventory = db.query(models.Inventory).filter(
        models.Inventory.id == order.inventory_id
    ).first()
    return schemas.OrderResponse(
        id=order.id,
        buyer_id=order.buyer_id,
        merchant_id=order.merchant_id,
        inventory_id=order.inventory_id,
        negotiation_id=order.negotiation_id,
        agreed_price=order.agreed_price,
        quantity=order.quantity,
        total_amount=order.total_amount,
        currency=order.currency,
        order_status=order.order_status,
        payment_status=order.payment_status,
        razorpay_order_id=order.razorpay_order_id,
        razorpay_payment_id=order.razorpay_payment_id,
        idempotency_key=order.idempotency_key,
        merchant_name=profile.display_name if profile else f"Merchant#{order.merchant_id}",
        item_name=inventory.name if inventory else "Unknown",
        item_sku=inventory.sku if inventory else "Unknown",
        created_at=order.created_at,
        updated_at=order.updated_at,
    )


# =========================================================================
# PAYMENT APIs (Razorpay Checkout + Verification + Webhook)
# =========================================================================

@app.post("/api/payment/checkout", response_model=schemas.CheckoutInitResponse)
def initiate_checkout(
    order_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Creates Razorpay order and returns checkout config for frontend. Key comes from backend."""
    if current_user.role != "buyer":
        raise HTTPException(status_code=403, detail="Only buyers can initiate checkout.")
    try:
        return PaymentService.initiate_checkout(order_id, current_user.id, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/payment/verify")
async def verify_payment(
    req: schemas.PaymentVerifyRequest,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Server-side Razorpay signature verification. Never trust the frontend."""
    if current_user.role != "buyer":
        raise HTTPException(status_code=403, detail="Only buyers can verify payments.")
    try:
        order = PaymentService.verify_payment(
            order_id=req.order_id,
            razorpay_order_id=req.razorpay_order_id,
            razorpay_payment_id=req.razorpay_payment_id,
            razorpay_signature=req.razorpay_signature,
            buyer_id=current_user.id,
            db=db,
        )
        if order.negotiation_id:
            tx = db.query(models.Transaction).filter(models.Transaction.id == order.negotiation_id).first()
            if tx:
                await notify_transaction_event(tx, realtime.EventType.PAYMENT_COMPLETED, {
                    "order_id": order.id,
                    "payment_id": order.razorpay_payment_id,
                    "payment_status": order.payment_status,
                })
                await notify_transaction_event(tx, realtime.EventType.TRANSACTION_STATUS_CHANGED)

        # Broadcast updated inventory to all buyer & merchant dashboards
        if order.payment_status == models.OrderStatus.CONFIRMED and order.inventory_id:
            inv = db.query(models.Inventory).filter(models.Inventory.id == order.inventory_id).first()
            if inv:
                prof = db.query(models.MerchantProfile).filter(models.MerchantProfile.user_id == inv.merchant_id).first()
                avail_units = max(0, inv.current_stock - inv.reserved_stock)
                await realtime.manager.broadcast_all_dashboards(
                    realtime.EventType.INVENTORY_UPDATED,
                    {
                        "inventory_id": inv.id,
                        "sku": inv.sku,
                        "name": inv.name,
                        "merchant_id": inv.merchant_id,
                        "merchant_name": prof.display_name if prof else inv.wholesaler_name,
                        "current_stock": inv.current_stock,
                        "reserved_stock": inv.reserved_stock,
                        "available_stock": avail_units,
                        "is_out_of_stock": avail_units <= 0,
                    }
                )

        return {
            "status": "success" if order.payment_status == models.OrderStatus.CONFIRMED else "failed",
            "order_id": order.id,
            "payment_status": order.payment_status,
            "order_status": order.order_status,
            "razorpay_payment_id": order.razorpay_payment_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/payment/webhook")
async def razorpay_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Razorpay webhook receiver. Verifies signature. Idempotent processing.
    No auth required — Razorpay calls this directly.
    """
    body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature", "")

    # Verify webhook signature
    if not payment_provider.verify_webhook_signature(body, signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        payload = json.loads(body)
        event_type = payload.get("event", "")
        PaymentService.handle_webhook(event_type, payload, db)

        # If payment succeeded, broadcast updated stock to all dashboards
        rzp_order_id = payload.get("payload", {}).get("payment", {}).get("entity", {}).get("order_id")
        if rzp_order_id:
            wh_order = db.query(models.Order).filter(models.Order.razorpay_order_id == rzp_order_id).first()
            if wh_order and wh_order.payment_status == models.OrderStatus.CONFIRMED and wh_order.inventory_id:
                inv = db.query(models.Inventory).filter(models.Inventory.id == wh_order.inventory_id).first()
                if inv:
                    prof = db.query(models.MerchantProfile).filter(models.MerchantProfile.user_id == inv.merchant_id).first()
                    avail_units = max(0, inv.current_stock - inv.reserved_stock)
                    await realtime.manager.broadcast_all_dashboards(
                        realtime.EventType.INVENTORY_UPDATED,
                        {
                            "inventory_id": inv.id,
                            "sku": inv.sku,
                            "name": inv.name,
                            "merchant_id": inv.merchant_id,
                            "merchant_name": prof.display_name if prof else inv.wholesaler_name,
                            "current_stock": inv.current_stock,
                            "reserved_stock": inv.reserved_stock,
                            "available_stock": avail_units,
                            "is_out_of_stock": avail_units <= 0,
                        }
                    )

        return {"status": "ok"}

    except Exception as e:
        logger.error(f"Webhook error: {str(e)}")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

# Legacy mock checkout endpoint (sandbox fallback)
@app.post("/api/payment/mock-checkout")
def mock_payment_checkout(
    order_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Frontend utility to simulate a successful checkout in sandbox mode."""
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order or not order.razorpay_order_id:
        raise HTTPException(status_code=400, detail="No active Razorpay order found.")
    if not payment_provider.is_mock:
        raise HTTPException(status_code=400, detail="Mock checkout is only available in Sandbox mode.")
    return payment_provider.generate_mock_payment(order.razorpay_order_id)


# =========================================================================
# TRANSACTION HISTORY & LOGS
# =========================================================================

def format_transaction_response(tx: models.Transaction, db: Session) -> schemas.TransactionResponse:
    profile = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == tx.merchant_id
    ).first()
    inventory = db.query(models.Inventory).filter(
        models.Inventory.id == tx.inventory_id
    ).first() if tx.inventory_id else None

    # Fetch quotes for this transaction
    quote_objs = db.query(models.Quote).filter(
        models.Quote.transaction_id == tx.id
    ).order_by(models.Quote.created_at.asc()).all()
    quote_responses = [schemas.QuoteResponse.from_orm(q) for q in quote_objs]

    # Active pending quote if any
    active_quote_obj = next((q for q in quote_objs if q.status == models.QuoteStatus.PENDING), None)
    active_quote = schemas.QuoteResponse.from_orm(active_quote_obj) if active_quote_obj else None

    return schemas.TransactionResponse(
        id=tx.id,
        transaction_number=tx.transaction_number or f"NXS-{tx.id:04d}",
        sku=tx.sku,
        quantity=tx.quantity,
        final_price=tx.final_price,
        status=tx.status,
        cryptographic_signature=tx.cryptographic_signature,
        razorpay_order_id=tx.razorpay_order_id,
        buyer_id=tx.buyer_id,
        merchant_id=tx.merchant_id,
        inventory_id=tx.inventory_id,
        buyer_approved=tx.buyer_approved,
        merchant_approved=tx.merchant_approved,
        buyer_accepted=bool(tx.buyer_approved == 1),
        merchant_accepted=bool(tx.merchant_approved == 1),
        agreed_quote_id=tx.agreed_quote_id,
        quotes=quote_responses,
        active_quote=active_quote,
        merchant_name=profile.display_name if profile else None,
        item_name=inventory.name if inventory else None,
        merchant_minimum_price=inventory.minimum_margin_limit if inventory else None,
        catalog_price=inventory.base_price if inventory else None,
        created_at=tx.created_at,
        updated_at=tx.updated_at,
    )


@app.get("/api/transactions")
def get_transactions(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns transaction history with merchant/inventory and quote details."""
    if current_user.role == "merchant":
        txs = db.query(models.Transaction).filter(
            models.Transaction.merchant_id == current_user.id
        ).order_by(models.Transaction.created_at.desc()).all()
    else:
        txs = db.query(models.Transaction).filter(
            models.Transaction.buyer_id == current_user.id
        ).order_by(models.Transaction.created_at.desc()).all()

    return [format_transaction_response(tx, db) for tx in txs]


@app.get("/api/transactions/{transaction_id}", response_model=schemas.TransactionResponse)
def get_transaction_by_id(
    transaction_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """Returns a specific transaction with quotes and active proposals."""
    tx = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not tx:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if tx.buyer_id != current_user.id and tx.merchant_id != current_user.id:
        raise HTTPException(status_code=403, detail="Unauthorized to view this transaction.")
    return format_transaction_response(tx, db)


@app.get("/api/transactions/{transaction_id}/logs", response_model=List[schemas.AuditLogResponse])
def get_transaction_logs(
    transaction_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    return db.query(models.AuditLog).filter(
        models.AuditLog.transaction_id == transaction_id
    ).order_by(models.AuditLog.timestamp.asc()).all()

@app.get("/api/transactions/{transaction_id}/upsell", response_model=schemas.UpsellOfferResponse)
def get_transaction_upsell(
    transaction_id: int,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    if transaction.buyer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    item = db.query(models.Inventory).filter(models.Inventory.id == transaction.inventory_id).first()
    if not item:
        # Fallback to SKU-based lookup
        item = db.query(models.Inventory).filter(models.Inventory.sku == transaction.sku).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    # Get inventory scoped to the same merchant
    merchant_inventory = db.query(models.Inventory).filter(
        models.Inventory.merchant_id == transaction.merchant_id
    ).all()
    inv_dicts = [
        {"sku": i.sku, "name": i.name, "current_stock": i.current_stock, "base_price": i.base_price, "merchant_id": i.merchant_id}
        for i in merchant_inventory
    ]

    agent = UpsellAgent()
    offer = agent.generate_upsell_offer(
        purchased_sku=item.sku,
        purchased_name=item.name,
        available_inventory=inv_dicts,
        merchant_id=transaction.merchant_id,
    )

    if not offer:
        raise HTTPException(status_code=404, detail="No upsell offers available")

    return offer


# =========================================================================
# ADMIN APIs
# =========================================================================

@app.get("/api/admin/payments")
def admin_payment_list(
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
    merchant_id: Optional[int] = None,
):
    """Admin view of all orders with Razorpay IDs. Filterable by merchant_id."""
    query = db.query(models.Order).order_by(models.Order.created_at.desc())
    if merchant_id:
        query = query.filter(models.Order.merchant_id == merchant_id)
    orders = query.all()
    return [_enrich_order_response(o, db) for o in orders]


# =========================================================================
# LEGACY COMPATIBILITY: Old payment/create-order endpoint
# (Kept for backward compat — new flow uses /api/orders + /api/payment/checkout)
# =========================================================================

@app.post("/api/payment/create-order")
def create_payment_order_legacy(
    transaction_id: int,
    mandate_token: str,
    current_user: models.User = Depends(auth.get_current_user),
    db: Session = Depends(get_db),
):
    """
    Legacy endpoint. New flow: POST /api/orders → POST /api/payment/checkout.
    Kept for backward compatibility with existing frontend code during migration.
    """
    transaction = db.query(models.Transaction).filter(models.Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(status_code=404, detail="Transaction not found")
    valid_approved_statuses = (
        models.TransactionStatus.MUTUALLY_APPROVED,
        models.TransactionStatus.APPROVED,
        models.TransactionStatus.QUOTE_AGREED,
        "mutually_approved",
        "approved",
        "quote_agreed",
    )
    if transaction.status not in valid_approved_statuses:
        raise HTTPException(status_code=400, detail="Transaction must be mutually approved first.")

    # Cryptographic validation
    if not verify_cart_mandate(mandate_token):
        transaction.status = models.TransactionStatus.VERIFICATION_FAILED
        log = models.AuditLog(
            transaction_id=transaction.id,
            actor="Security Verification System",
            message="CRITICAL ALERT: Tampering attempt blocked! Cryptographic mandate verification failed."
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=400, detail="Signature Verification Mismatch (Tampering Detected).")

    # Extract and verify payload
    payload_str = mandate_token.rsplit(".", 1)[0]
    payload = json.loads(payload_str)

    if (payload["sku"] != transaction.sku or
        payload["quantity"] != transaction.quantity or
        abs(payload["price"] - transaction.final_price) > 0.01):
        transaction.status = models.TransactionStatus.VERIFICATION_FAILED
        log = models.AuditLog(
            transaction_id=transaction.id,
            actor="Security Verification System",
            message="CRITICAL ALERT: Mandate values mismatch database state."
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=400, detail="Transaction details do not match negotiated agreement.")

    # Resolve merchant for dynamic notes
    profile = db.query(models.MerchantProfile).filter(
        models.MerchantProfile.user_id == transaction.merchant_id
    ).first()
    merchant_name = profile.display_name if profile else f"Merchant#{transaction.merchant_id}"

    total_amount = transaction.quantity * transaction.final_price
    try:
        notes = {
            "merchant_id": str(transaction.merchant_id),
            "merchant_name": merchant_name,
            "transaction_id": str(transaction.id),
            "platform": "Project Nexus",
        }
        order = payment_provider.create_order(
            amount=total_amount,
            currency="INR",
            receipt=f"txn_{transaction.id}",
            notes=notes,
        )

        transaction.razorpay_order_id = order["id"]
        log = models.AuditLog(
            transaction_id=transaction.id,
            actor="System Payment Gateway",
            message=f"Razorpay order {order['id']} created for merchant '{merchant_name}'. Amount: {total_amount} INR."
        )
        db.add(log)
        db.commit()

        return {
            "order_id": order["id"],
            "amount": order["amount"],
            "currency": order["currency"],
            "is_mock": payment_provider.is_mock,
            "key_id": settings.RAZORPAY_KEY_ID or "rzp_mock_key",
        }
    except Exception as e:
        logger.error(f"Error in creating settlement: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Payment settlement setup failed: {str(e)}")
