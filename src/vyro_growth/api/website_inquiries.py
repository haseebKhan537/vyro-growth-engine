"""Authenticated server-to-server intake contract for public website forms."""

from __future__ import annotations

import re
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from vyro_growth.services.website_inquiries import (
    WebsiteInquiryInput,
    WebsiteInquiryResult,
    WebsiteInquiryService,
)

ALLOWED_FORM_NAMES = frozenset({"Homepage inquiry", "Free audit request"})
ALLOWED_SOURCE_PAGES = frozenset({"/", "/index.html", "/audit.html"})
CONSENT_TEXT_VERSION = "2026-09-10"
EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
PHI_HINTS = (
    "patient name",
    "date of birth",
    "medical record",
    "member id",
    "claim number",
    "social security",
    "diagnosed with",
    "patient:",
)


class WebsiteInquiryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    submission_id: UUID
    form_name: str = Field(min_length=1, max_length=64)
    source_page: str = Field(min_length=1, max_length=255)
    practice_name: str = Field(min_length=2, max_length=255)
    contact_name: str = Field(min_length=2, max_length=255)
    work_email: str = Field(min_length=5, max_length=320)
    business_phone: str | None = Field(default=None, max_length=50)
    specialty: str | None = Field(default=None, max_length=255)
    state: str | None = Field(default=None, max_length=2)
    provider_count: str | None = Field(default=None, max_length=32)
    primary_concern: str | None = Field(default=None, max_length=120)
    preferred_contact: str | None = Field(default=None, max_length=32)
    business_context: str | None = Field(default=None, max_length=2000)
    contact_consent: bool
    consent_text_version: str = Field(max_length=32)

    @field_validator("form_name")
    @classmethod
    def validate_form_name(cls, value: str) -> str:
        if value not in ALLOWED_FORM_NAMES:
            raise ValueError("Unsupported website form")
        return value

    @field_validator("source_page")
    @classmethod
    def validate_source_page(cls, value: str) -> str:
        if value not in ALLOWED_SOURCE_PAGES:
            raise ValueError("Unsupported source page")
        return value

    @field_validator("work_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.casefold()
        if not EMAIL_RE.fullmatch(normalized):
            raise ValueError("A valid work email is required")
        return normalized

    @field_validator("state")
    @classmethod
    def normalize_state(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if not re.fullmatch(r"[A-Z]{2}", normalized):
            raise ValueError("State must be a two-letter US abbreviation")
        return normalized

    @field_validator("business_context")
    @classmethod
    def reject_likely_phi(cls, value: str | None) -> str | None:
        if value and any(hint in value.casefold() for hint in PHI_HINTS):
            raise ValueError("Do not submit patient or protected health information")
        return value

    @model_validator(mode="after")
    def require_consent(self) -> Self:
        if not self.contact_consent:
            raise ValueError("Contact consent is required")
        if self.consent_text_version != CONSENT_TEXT_VERSION:
            raise ValueError("Unsupported consent text version")
        if self.form_name == "Free audit request":
            if self.source_page != "/audit.html" or not self.specialty or not self.state:
                raise ValueError("Audit requests require the audit page, specialty, and state")
        elif self.source_page not in {"/", "/index.html"}:
            raise ValueError("Homepage inquiries require a homepage source")
        return self


class WebsiteInquiryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accepted: bool = True
    reference_id: UUID
    submission_id: UUID
    duplicate: bool


def capture_website_inquiry(
    db: Session,
    request: WebsiteInquiryRequest,
    *,
    service: WebsiteInquiryService | None = None,
) -> WebsiteInquiryResponse:
    recorder = service or WebsiteInquiryService()
    result: WebsiteInquiryResult = recorder.capture(
        db,
        WebsiteInquiryInput(**request.model_dump()),
    )
    return WebsiteInquiryResponse(
        reference_id=result.inquiry_id,
        submission_id=result.submission_id,
        duplicate=result.duplicate,
    )
