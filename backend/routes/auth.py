"""Auth routes: login, register, user CRUD."""
from fastapi import APIRouter, Depends, HTTPException
import deps
from deps import row_to_dict, new_id, utc_now, hash_password, verify_password, create_access_token, get_current_user, get_admin_user
from models import UserLogin, UserRegister, UserApproval, UserCreate, UserUpdate, PasswordReset

router = APIRouter(prefix="/api")


@router.post("/auth/login")
async def login(data: UserLogin):
    async with deps.pool.acquire() as conn:
        row = await conn.fetchrow("SELECT id, username, full_name, email, hashed_password, role, approved FROM users WHERE username = $1", data.username)
        if not row:
            raise HTTPException(401, "Invalid credentials")
        user = row_to_dict(row)
        if not verify_password(data.password, user['hashed_password']):
            raise HTTPException(401, "Invalid credentials")
        if not user.get('approved'):
            raise HTTPException(403, "Account not approved")
        token = create_access_token(user['id'], user['role'])
        return {"token": token, "user": {"id": user['id'], "username": user['username'], "full_name": user['full_name'], "email": user['email'], "role": user['role']}}


@router.post("/users/register")
async def register(data: UserRegister):
    async with deps.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT id FROM users WHERE username = $1 OR email = $2", data.username, data.email)
        if existing:
            raise HTTPException(400, "Username or email already exists")
        user_id = new_id()
        await conn.execute('''
            INSERT INTO users (id, username, full_name, email, hashed_password, role, approved, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, 'user', FALSE, $6, $6)
        ''', user_id, data.username, data.name, data.email, hash_password(data.password), utc_now())
        return {"message": "Registration successful. Awaiting admin approval.", "user_id": user_id}


@router.get("/users")
async def get_users(user: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        rows = await conn.fetch("SELECT id, username, full_name, email, role, approved, created_at FROM users ORDER BY created_at DESC")
        return {"users": [row_to_dict(r) for r in rows]}


@router.post("/users")
async def create_user(data: UserCreate, admin: dict = Depends(get_admin_user)):
    if not data.username or not data.password:
        raise HTTPException(400, "Username and password are required")
    if len(data.password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    async with deps.pool.acquire() as conn:
        existing = await conn.fetchval("SELECT id FROM users WHERE username = $1", data.username)
        if existing:
            raise HTTPException(400, "Username already exists")
        user_id = new_id()
        await conn.execute("""
            INSERT INTO users (id, username, email, hashed_password, role, approved, created_at)
            VALUES ($1, $2, $3, $4, $5, TRUE, $6)
        """, user_id, data.username, data.email, hash_password(data.password), data.role, utc_now())
        return {"status": "created", "id": user_id}


@router.put("/users/{user_id}")
async def update_user(user_id: str, data: UserUpdate, admin: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        existing = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        if not existing:
            raise HTTPException(404, "User not found")
        update_fields = []
        values = []
        param_idx = 1
        if data.username:
            update_fields.append(f"username = ${param_idx}"); values.append(data.username); param_idx += 1
        if data.email is not None:
            update_fields.append(f"email = ${param_idx}"); values.append(data.email); param_idx += 1
        if data.role:
            update_fields.append(f"role = ${param_idx}"); values.append(data.role); param_idx += 1
        if data.password:
            if len(data.password) < 6:
                raise HTTPException(400, "Password must be at least 6 characters")
            update_fields.append(f"hashed_password = ${param_idx}"); values.append(hash_password(data.password)); param_idx += 1
        if update_fields:
            update_fields.append(f"updated_at = ${param_idx}"); values.append(utc_now()); param_idx += 1
            values.append(user_id)
            query = f"UPDATE users SET {', '.join(update_fields)} WHERE id = ${param_idx}"
            await conn.execute(query, *values)
        return {"status": "updated"}


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(user_id: str, data: PasswordReset, admin: dict = Depends(get_admin_user)):
    if len(data.new_password) < 6:
        raise HTTPException(400, "Password must be at least 6 characters")
    async with deps.pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET hashed_password = $1, updated_at = $2 WHERE id = $3",
            hash_password(data.new_password), utc_now(), user_id)
        if result == "UPDATE 0":
            raise HTTPException(404, "User not found")
        return {"status": "password_reset"}


@router.put("/users/{user_id}/approve")
async def approve_user(user_id: str, data: UserApproval, admin: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        result = await conn.execute("UPDATE users SET approved = $1, updated_at = $2 WHERE id = $3", data.approved, utc_now(), user_id)
        if result == "UPDATE 0":
            raise HTTPException(404, "User not found")
        return {"status": "updated", "approved": data.approved}


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, admin: dict = Depends(get_admin_user)):
    async with deps.pool.acquire() as conn:
        result = await conn.execute("DELETE FROM users WHERE id = $1 AND role != 'admin'", user_id)
        if result == "DELETE 0":
            raise HTTPException(404, "User not found or cannot delete admin")
        return {"status": "deleted"}


@router.get("/users/me")
async def get_me(user: dict = Depends(get_current_user)):
    return user
