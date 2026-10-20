from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, EmailStr, Field

class Role(StrEnum):
    student = "student"
    teacher = "teacher"
    administrator = "administrator"

class PublicUserAccount(BaseModel):
    id: int
    username: str = Field(min_length=4, max_length=32)
    email: EmailStr
    role: Role
    created_at: datetime

class FullUserAccount(PublicUserAccount):
    password_hash: str = Field(repr=False)

class UserCreate(BaseModel):
    username: str = Field(min_length=4, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)