from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from vyro_growth.domain import VoiceConsentChannel, VoiceConsentSource
from vyro_growth.providers.voice_qualification import (
    VoiceQualificationProvider,
    build_voice_qualification_provider,
    parse_consent_timestamp,
)
from vyro_growth.services.voice_qualification import (
    VoiceConsentInput,
    VoiceQualificationService,
    VoiceQualificationServiceError,
)
from vyro_growth.workers.base import Job

PLAN_VOICE_QUALIFICATIONS_JOB = "plan_voice_qualifications"


class PlanVoiceQualificationsHandler:
    db: Session
    provider: VoiceQualificationProvider | None = None

    def __init__(
        self,
        db: Session,
        provider: VoiceQualificationProvider | None = None,
    ) -> None:
        self.db = db
        self.provider = provider

    def handle(self, job: Job) -> None:
        lead_id = _optional_uuid(job.payload.get("lead_id"))
        message_id = _optional_uuid(job.payload.get("message_id"))
        meeting_id = _optional_uuid(job.payload.get("meeting_id"))
        booking_plan_id = _optional_uuid(job.payload.get("booking_plan_id"))
        operator_request = job.payload.get("operator_request") is True
        request_key = _optional_str(job.payload.get("request_key"))
        limit = _optional_int(job.payload.get("limit"))
        state = _optional_str(job.payload.get("state"))
        city = _optional_str(job.payload.get("city"))
        consent = _consent_input(job.payload)

        service = VoiceQualificationService(self.provider or build_voice_qualification_provider())
        if message_id is not None and lead_id is None:
            service.plan_message(self.db, message_id)
            return
        if meeting_id is not None and lead_id is None:
            service.plan_meeting(self.db, meeting_id, consent=consent)
            return
        if lead_id is not None:
            service.plan_lead(
                self.db,
                lead_id,
                message_id=message_id,
                meeting_id=meeting_id,
                booking_plan_id=booking_plan_id,
                operator_request=operator_request,
                request_key=request_key,
                consent=consent,
            )
            return
        if operator_request:
            raise VoiceQualificationServiceError("operator_request requires lead_id")
        service.plan_batch(
            self.db,
            limit=limit or 50,
            state=state,
            city=city,
        )


def _optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _optional_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return UUID(str(value))
    if isinstance(value, str) and value.strip():
        return UUID(value)
    return None


def _consent_input(payload: dict[str, object]) -> VoiceConsentInput | None:
    source = _consent_source(payload.get("consent_source"))
    channel = _consent_channel(payload.get("consent_channel"))
    consented_at = _optional_datetime(payload.get("consent_timestamp"))
    permitted_phone = _optional_str(payload.get("permitted_phone"))
    evidence_reference_id = _optional_str(payload.get("consent_evidence_id"))
    if (
        source is None
        and channel is None
        and consented_at is None
        and permitted_phone is None
        and evidence_reference_id is None
    ):
        return None
    return VoiceConsentInput(
        source=source,
        channel=channel,
        consented_at=consented_at,
        permitted_phone=permitted_phone,
        evidence_reference_id=evidence_reference_id,
    )


def _optional_datetime(value: object) -> datetime | None:
    return parse_consent_timestamp(value)


def _consent_source(value: object) -> VoiceConsentSource | None:
    if isinstance(value, VoiceConsentSource):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return VoiceConsentSource(value.strip())
        except ValueError:
            return None
    return None


def _consent_channel(value: object) -> VoiceConsentChannel | None:
    if isinstance(value, VoiceConsentChannel):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return VoiceConsentChannel(value.strip())
        except ValueError:
            return None
    return None
