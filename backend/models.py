"""Pydantic models for request/response validation."""
from pydantic import BaseModel
from typing import List, Optional, Dict


# Auth
class UserRegister(BaseModel):
    name: str
    email: str
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class UserApproval(BaseModel):
    user_id: str
    approved: bool

class UserCreate(BaseModel):
    username: str
    email: Optional[str] = None
    password: str
    role: str = "user"

class UserUpdate(BaseModel):
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None
    role: Optional[str] = None

class PasswordReset(BaseModel):
    new_password: str


# Suppliers
class SupplierCreate(BaseModel):
    supplier_name: str
    api_base_url: str = ""
    account_number: str = ""
    password: str = ""
    media_password: str = ""
    use_uat: bool = False
    services: Dict[str, str] = {}
    endpoint_style: str = ""
    bulk_data_url: str = ""

class SupplierUpdate(BaseModel):
    supplier_name: Optional[str] = None
    api_base_url: Optional[str] = None
    account_number: Optional[str] = None
    password: Optional[str] = None
    media_password: Optional[str] = None
    use_uat: Optional[bool] = None
    services: Optional[Dict[str, str]] = None
    endpoint_style: Optional[str] = None
    status: Optional[str] = None
    bulk_data_url: Optional[str] = None


# Products
class ProductSelectRequest(BaseModel):
    product_id: str
    selected: bool

class BulkSelectRequest(BaseModel):
    product_ids: List[str]
    selected: bool

class BulkDeleteRequest(BaseModel):
    product_ids: list


# Settings
class SettingsUpdate(BaseModel):
    sync_products_interval_hours: Optional[int] = None
    sync_inventory_interval_minutes: Optional[int] = None
    sync_pricing_interval_hours: Optional[int] = None
    auto_sync_enabled: Optional[bool] = None
    odoo_url: Optional[str] = None
    odoo_db: Optional[str] = None
    odoo_username: Optional[str] = None
    odoo_api_key: Optional[str] = None
    preferred_warehouse: Optional[str] = None
    markup_percentage: Optional[float] = None
    auto_push_to_odoo: Optional[bool] = None
    lightspeed_store_id: Optional[str] = None
    lightspeed_secret_token: Optional[str] = None
    lightspeed_client_id: Optional[str] = None
    lightspeed_client_secret: Optional[str] = None
