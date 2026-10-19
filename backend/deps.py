"""Shared dependencies: DB pool, helpers, auth, sync log utilities."""
import os
import json
import uuid
import logging
import asyncpg
import jwt
from datetime import datetime, timezone, timedelta
from passlib.context import CryptContext
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

logger = logging.getLogger(__name__)

# PostgreSQL pool (assigned during startup)
pool: asyncpg.Pool = None

# JWT config
JWT_SECRET = os.environ.get('JWT_SECRET', 'supplierhub-secret-key-change-in-production')
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

# In-memory tracker for running sync jobs
running_syncs: dict = {}


# ==================== HELPERS ====================
def utc_now():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def utc_now_str():
    return datetime.now(timezone.utc).isoformat()

def new_id():
    return str(uuid.uuid4())

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS)
    payload = {"sub": user_id, "role": role, "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.isoformat()
        elif k in ('services', 'warehouse_inventory'):
            if isinstance(v, str):
                try:
                    d[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    d[k] = {} if k == 'services' else []
            elif v is None:
                d[k] = {} if k == 'services' else []
    return d

def calculate_sale_price(cost_price: float, markup_percentage: float) -> float:
    if not cost_price or cost_price <= 0:
        return 0
    sale_price = cost_price + (cost_price * markup_percentage / 100)
    return round(sale_price)


# ==================== AUTH DEPS ====================
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(401, "Not authenticated")
    try:
        payload = jwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(401, "Invalid token")
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT id, username, full_name, email, role, approved FROM users WHERE id = $1", user_id)
            if not row:
                raise HTTPException(401, "User not found")
            user = row_to_dict(row)
            if not user.get("approved"):
                raise HTTPException(403, "Account not approved")
            return user
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(401, "Invalid token")

async def get_admin_user(user: dict = Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(403, "Admin access required")
    return user


# ==================== SYNC LOG HELPERS ====================
async def create_sync_log(supplier_id, supplier_name, sync_type, message):
    log_id = new_id()
    async with pool.acquire() as conn:
        await conn.execute('''
            INSERT INTO sync_logs (id, supplier_id, supplier_name, sync_type, status, message, start_time, created_at)
            VALUES ($1, $2, $3, $4, 'running', $5, $6, $6)
        ''', log_id, supplier_id, supplier_name, sync_type, message, utc_now())
    return log_id

async def update_sync_log(log_id, status, message, progress=0, total=0, processed=0):
    async with pool.acquire() as conn:
        end_time = utc_now() if status in ['completed', 'failed', 'stopped'] else None
        await conn.execute('''
            UPDATE sync_logs SET status = $1, message = $2, progress = $3, total_items = $4, processed_items = $5, end_time = $6
            WHERE id = $7
        ''', status, message, progress, total, processed, end_time, log_id)
