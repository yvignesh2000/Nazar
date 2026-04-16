# -*- coding: utf-8 -*-
"""
Nazar — Pydantic Request/Response Schemas

All API request bodies are validated through these models before
reaching business logic. This catches bad input at the boundary
and provides clean error messages.

Import pattern in server.py:
  from schemas import CreateContactRequest, SendMessageRequest, ...
"""

from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator, model_validator
import re


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------

class CreateContactRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    phone: str = Field(..., min_length=7, max_length=20)
    company: Optional[str] = Field(None, max_length=200)
    source: Optional[str] = Field(None, max_length=100)
    assigned_to: Optional[str] = Field(None, max_length=100)
    tags: Optional[List[str]] = Field(default_factory=list)
    deal_value: Optional[float] = Field(None, ge=0)

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        cleaned = re.sub(r"[\s\-\(\)\.]", "", v)
        if not re.match(r"^\+?\d{7,15}$", cleaned):
            raise ValueError("Invalid phone number format")
        return v

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, v: Optional[List[str]]) -> List[str]:
        if v is None:
            return []
        return [t.strip()[:50] for t in v if t.strip()]


class UpdateContactRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    company: Optional[str] = Field(None, max_length=200)
    notes: Optional[str] = Field(None, max_length=5000)
    deal_value: Optional[float] = Field(None, ge=0)
    assigned_to: Optional[str] = Field(None, max_length=100)
    pipeline_stage: Optional[str] = None
    lead_score: Optional[int] = Field(None, ge=0, le=100)
    tags: Optional[List[str]] = None
    opt_in: Optional[bool] = None

    class Config:
        extra = "allow"  # Pass unknown fields through to update_contact


class ImportContactsRequest(BaseModel):
    csv: str = Field(..., min_length=10)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

class MovePipelineRequest(BaseModel):
    stage: str = Field(..., min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------

class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)


class HandoverRequest(BaseModel):
    bot_mode: bool = True


# ---------------------------------------------------------------------------
# Reply modes / drafts
# ---------------------------------------------------------------------------

class SetReplyModeRequest(BaseModel):
    mode: str = Field(...)

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, v: str) -> str:
        valid = ("auto_ai", "human_only", "ai_draft")
        if v not in valid:
            raise ValueError(f"Invalid mode. Must be one of: {', '.join(valid)}")
        return v


class ApproveDraftRequest(BaseModel):
    edited_text: Optional[str] = Field(None, max_length=4096)


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

class CreateTemplateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$")
    body: str = Field(..., min_length=1, max_length=1024)
    category: str = "utility"
    variables: Optional[List[str]] = Field(default_factory=list)
    language: str = Field("en", max_length=10)
    description: Optional[str] = Field("", max_length=500)
    header: Optional[dict] = None
    footer: Optional[str] = Field("", max_length=60)
    buttons: Optional[List[dict]] = Field(default_factory=list)

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        valid = ("marketing", "utility", "authentication")
        if v not in valid:
            raise ValueError(f"Invalid category. Must be one of: {', '.join(valid)}")
        return v

    @field_validator("buttons")
    @classmethod
    def validate_buttons(cls, v: Optional[List[dict]]) -> List[dict]:
        if v and len(v) > 3:
            raise ValueError("Maximum 3 buttons allowed per template")
        return v or []

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not re.match(r"^[a-z0-9_]+$", v):
            raise ValueError("Template name must be lowercase letters, numbers, and underscores only")
        return v


class UpdateTemplateRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=100)
    body: Optional[str] = Field(None, max_length=1024)
    category: Optional[str] = None
    variables: Optional[List[str]] = None
    language: Optional[str] = None
    description: Optional[str] = None
    header: Optional[dict] = None
    footer: Optional[str] = None
    buttons: Optional[List[dict]] = None
    approval_status: Optional[str] = None

    class Config:
        extra = "allow"


class RenderTemplateRequest(BaseModel):
    contact_id: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------

class CreateCampaignRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    template_id: str = Field(..., min_length=1)
    filter_stage: Optional[str] = None
    filter_tag: Optional[str] = None
    contact_ids: Optional[List[str]] = Field(default_factory=list)
    group_ids: Optional[List[str]] = Field(default_factory=list)
    scheduled_at: Optional[str] = None
    reply_mode: str = "auto_ai"
    campaign_kb: Optional[str] = Field("", max_length=50000)
    header_image_url: Optional[str] = Field("", max_length=2000)

    @field_validator("reply_mode")
    @classmethod
    def validate_reply_mode(cls, v: str) -> str:
        valid = ("auto_ai", "human_only", "ai_draft")
        if v not in valid:
            raise ValueError(f"Invalid reply_mode. Must be one of: {', '.join(valid)}")
        return v


class RetargetCampaignRequest(BaseModel):
    type: str = "failed"

    @field_validator("type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        if v not in ("failed", "unread"):
            raise ValueError("type must be 'failed' or 'unread'")
        return v


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class UpdateConfigRequest(BaseModel):
    business_name: Optional[str] = Field(None, max_length=200)
    bot_enabled: Optional[bool] = None
    bot_persona: Optional[str] = Field(None, max_length=50)
    welcome_message: Optional[str] = Field(None, max_length=500)
    handoff_message: Optional[str] = Field(None, max_length=500)
    smart_handoff: Optional[bool] = None
    auto_resume_hours: Optional[int] = Field(None, ge=0, le=168)
    notify_phone: Optional[str] = None

    class Config:
        extra = "allow"


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class UploadKBRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=100000)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=6, max_length=200)
    workspace_id: str = "default"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v or "." not in v.split("@")[-1]:
            raise ValueError("Invalid email address")
        return v.lower().strip()


class CreateUserRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    password: str = Field(..., min_length=8, max_length=200)
    name: Optional[str] = Field("", max_length=200)
    role: str = "agent"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email address")
        return v.lower().strip()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid = ("owner", "admin", "agent", "viewer")
        if v not in valid:
            raise ValueError(f"Invalid role. Must be one of: {', '.join(valid)}")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UpdateUserRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=200)
    role: Optional[str] = None
    active: Optional[bool] = None

    class Config:
        extra = "allow"


class ChangePasswordRequest(BaseModel):
    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8)


# ---------------------------------------------------------------------------
# Billing
# ---------------------------------------------------------------------------

class UpgradePlanRequest(BaseModel):
    plan_id: str = Field(..., min_length=1)

    @field_validator("plan_id")
    @classmethod
    def validate_plan(cls, v: str) -> str:
        valid = ("starter", "growth", "pro", "enterprise")
        if v not in valid:
            raise ValueError(f"Invalid plan. Must be one of: {', '.join(valid)}")
        return v


class CancelSubscriptionRequest(BaseModel):
    at_period_end: bool = True


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------

class OnboardingStepRequest(BaseModel):
    notes: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------

class CreateInviteRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=254)
    role: str = "agent"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email address")
        return v.lower().strip()

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        valid = ("admin", "agent", "viewer")
        if v not in valid:
            raise ValueError(f"Cannot invite as '{v}'. Must be one of: {', '.join(valid)}")
        return v


class AcceptInviteRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    password: str = Field(..., min_length=8, max_length=200)


# ---------------------------------------------------------------------------
# API Key management
# ---------------------------------------------------------------------------

class SaveApiKeysRequest(BaseModel):
    keys: dict = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Simulate
# ---------------------------------------------------------------------------

class SimulateMessageRequest(BaseModel):
    contact_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1, max_length=4096)


# ---------------------------------------------------------------------------
# Handoff resume
# ---------------------------------------------------------------------------

class ResumeHandoffRequest(BaseModel):
    reason: Optional[str] = Field("Resumed from dashboard", max_length=500)
