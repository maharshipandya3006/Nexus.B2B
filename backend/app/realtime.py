import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Set, Optional, Any
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("app.realtime")


class EventType:
    QUOTE_UPDATED = "QUOTE_UPDATED"
    NEGOTIATION_UPDATED = "NEGOTIATION_UPDATED"
    PRICE_ACCEPTED = "PRICE_ACCEPTED"
    TRANSACTION_STATUS_CHANGED = "TRANSACTION_STATUS_CHANGED"
    TRANSACTION_TERMINATED = "TRANSACTION_TERMINATED"
    PAYMENT_INITIATED = "PAYMENT_INITIATED"
    PAYMENT_COMPLETED = "PAYMENT_COMPLETED"
    INVENTORY_UPDATED = "INVENTORY_UPDATED"
    INVENTORY_DELETED = "INVENTORY_DELETED"
    HEARTBEAT = "HEARTBEAT"



class ConnectionManager:
    """
    Thread-safe connection manager for transaction-specific rooms
    and user-specific dashboard channels.
    """

    def __init__(self):
        # transaction_id -> set of active WebSockets
        self.active_tx_connections: Dict[int, Set[WebSocket]] = {}
        # user_id -> set of active WebSockets
        self.user_connections: Dict[int, Set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect_transaction(self, websocket: WebSocket, transaction_id: int, user_id: int):
        await websocket.accept()
        async with self._lock:
            if transaction_id not in self.active_tx_connections:
                self.active_tx_connections[transaction_id] = set()
            self.active_tx_connections[transaction_id].add(websocket)
        
        # Send initial connection handshake
        handshake_payload = {
            "event_id": f"evt_handshake_{uuid.uuid4().hex[:8]}",
            "event_type": "CONNECTED",
            "transaction_id": transaction_id,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {"message": f"Subscribed to real-time stream for transaction #{transaction_id}"}
        }
        await websocket.send_text(json.dumps(handshake_payload))
        logger.info(f"User #{user_id} connected to real-time room for transaction #{transaction_id}")

    async def disconnect_transaction(self, websocket: WebSocket, transaction_id: int):
        async with self._lock:
            if transaction_id in self.active_tx_connections:
                self.active_tx_connections[transaction_id].discard(websocket)
                if not self.active_tx_connections[transaction_id]:
                    del self.active_tx_connections[transaction_id]
        logger.info(f"WebSocket disconnected from transaction #{transaction_id}")

    async def connect_dashboard(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        async with self._lock:
            if user_id not in self.user_connections:
                self.user_connections[user_id] = set()
            self.user_connections[user_id].add(websocket)
        
        handshake_payload = {
            "event_id": f"evt_handshake_{uuid.uuid4().hex[:8]}",
            "event_type": "CONNECTED",
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": {"message": "Subscribed to live dashboard feed"}
        }
        await websocket.send_text(json.dumps(handshake_payload))
        logger.info(f"User #{user_id} connected to live dashboard feed")

    async def disconnect_dashboard(self, websocket: WebSocket, user_id: int):
        async with self._lock:
            if user_id in self.user_connections:
                self.user_connections[user_id].discard(websocket)
                if not self.user_connections[user_id]:
                    del self.user_connections[user_id]
        logger.info(f"WebSocket disconnected from user #{user_id} dashboard")

    async def broadcast_to_transaction(
        self,
        transaction_id: int,
        event_type: str,
        data: Dict[str, Any],
        buyer_id: Optional[int] = None,
        merchant_id: Optional[int] = None,
    ):
        """
        Broadcasts an event to all clients in the transaction room,
        and also notifies the respective user dashboard streams.
        """
        envelope = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "event_type": event_type,
            "transaction_id": transaction_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        payload_str = json.dumps(envelope)

        # 1. Broadcast to transaction-specific room
        dead_tx_sockets = set()
        async with self._lock:
            tx_sockets = set(self.active_tx_connections.get(transaction_id, []))

        for ws in tx_sockets:
            try:
                await ws.send_text(payload_str)
            except Exception as e:
                logger.warning(f"Error broadcasting to tx #{transaction_id} client: {e}")
                dead_tx_sockets.add(ws)

        if dead_tx_sockets:
            async with self._lock:
                if transaction_id in self.active_tx_connections:
                    self.active_tx_connections[transaction_id].difference_update(dead_tx_sockets)

        # 2. Also notify the buyer and merchant dashboard channels if connected
        user_ids_to_notify = [uid for uid in [buyer_id, merchant_id] if uid is not None]
        for uid in user_ids_to_notify:
            await self.broadcast_to_user(uid, event_type, {
                "transaction_id": transaction_id,
                **data
            })

    async def broadcast_to_user(self, user_id: int, event_type: str, data: Dict[str, Any]):
        """
        Broadcasts an event directly to a user's dashboard feed.
        """
        envelope = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "event_type": event_type,
            "user_id": user_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        payload_str = json.dumps(envelope)

        dead_user_sockets = set()
        async with self._lock:
            user_sockets = set(self.user_connections.get(user_id, []))

        for ws in user_sockets:
            try:
                await ws.send_text(payload_str)
            except Exception as e:
                logger.warning(f"Error broadcasting to user #{user_id} dashboard: {e}")
                dead_user_sockets.add(ws)

        if dead_user_sockets:
            async with self._lock:
                if user_id in self.user_connections:
                    self.user_connections[user_id].difference_update(dead_user_sockets)

    async def broadcast_all_dashboards(self, event_type: str, data: Dict[str, Any]):
        """
        Broadcasts an event (e.g. inventory updates) to ALL connected user dashboards.
        Ensures instantaneous cross-session synchronization between buyers and merchants.
        """
        envelope = {
            "event_id": f"evt_{uuid.uuid4().hex}",
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        payload_str = json.dumps(envelope)

        dead_sockets = []
        async with self._lock:
            # Collect all active user sockets across all connected dashboard users
            all_sockets = [ws for socket_set in self.user_connections.values() for ws in socket_set]

        for ws in all_sockets:
            try:
                await ws.send_text(payload_str)
            except Exception as e:
                logger.warning(f"Error broadcasting to dashboard feed: {e}")
                dead_sockets.append(ws)

        if dead_sockets:
            async with self._lock:
                for ws in dead_sockets:
                    for uid, socket_set in list(self.user_connections.items()):
                        socket_set.discard(ws)
                        if not socket_set:
                            self.user_connections.pop(uid, None)


# Global singleton instance
manager = ConnectionManager()

