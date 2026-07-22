from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


class AccountDto(BaseModel):
    id: UUID
    username: str
    created_at: datetime


class LoginResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    account: AccountDto


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
