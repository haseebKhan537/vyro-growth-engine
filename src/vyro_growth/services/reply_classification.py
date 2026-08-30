from __future__ import annotations

from dataclasses import dataclass
from typing import Never
from uuid import UUID

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from vyro_growth.domain import (
    FORBIDDEN_REPLY_STAGES,
    ConversationStatus,
    LeadStage,
    MessageDirection,
    ReplyClassificationOutcome,
    ReplyIntent,
    can_transition,
    conversation_status_for,
    desired_reply_stages,
)
from vyro_growth.models import (
    Activity,
    Contact,
    Conversation,
    Lead,
    OutreachMessage,
    ReplyClassification,
    Suppression,
)
from vyro_growth.providers.decision_makers import clip_text
from vyro_growth.providers.reply_classification import (
    SCHEMA_VERSION,
    ReplyClassificationRequest,
    ReplyClassifierError,
    ReplyClassifierProvider,
    ReplyClassifierResult,
    reply_content_hash,
)
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt
from vyro_growth.services.outbound_guard import normalize_email

logger = structlog.get_logger(__name__)

REPLY_ACTOR = "reply_classification"
BATCH_MAX = 200
SUMMARY_MAX_LENGTH = 240
CHANNEL_EMAIL = "email"


class ReplyClassificationError(ValueError):
    """Raised when a reply classification job cannot load the requested row."""


@dataclass(frozen=True)
class InboundReplySpec:
    lead_id: UUID
    body: str
    subject: str | None = None
    sender_email: str | None = None
    provider_message_id: str | None = None
    message_id: UUID | None = None
    contact_id: UUID | None = None


@dataclass(frozen=True)
class ReplyClassificationJobResult:
    classification_id: UUID | None
    lead_id: UUID
    message_id: UUID | None
    conversation_id: UUID | None
    intent: ReplyIntent | None
    outcome: ReplyClassificationOutcome
    provider_name: str
    reused_existing: bool
    suppressed: bool
    lead_stage_before: str
    lead_stage_after: str
    outbound_attempted: bool
    live_call_attempted: bool
    operator_halt_before: str
    operator_halt_after: str


class ReplyClassificationService:
    """Classify stored inbound replies and apply conservative CRM updates.

    Does not send email, place calls, book meetings, or enroll campaigns.
    """

    def __init__(self, provider: ReplyClassifierProvider) -> None:
        self._provider = provider

    def classify_message(
        self,
        db: Session,
        message_id: UUID,
        *,
        commit: bool = True,
    ) -> ReplyClassificationJobResult:
        message = db.get(OutreachMessage, message_id)
        if message is None:
            raise ReplyClassificationError(f"Outreach message not found: {message_id}")
        if message.direction != MessageDirection.INBOUND.value:
            raise ReplyClassificationError(
                f"Outreach message is not inbound: {message_id}"
            )
        lead = db.get(Lead, message.lead_id)
        if lead is None:
            raise ReplyClassificationError(f"Lead not found for message: {message_id}")
        spec = InboundReplySpec(
            lead_id=lead.id,
            body=message.body,
            subject=message.subject,
            sender_email=_sender_email(db, message),
            provider_message_id=message.provider_message_id,
            message_id=message.id,
            contact_id=message.contact_id,
        )
        return self._run(db, lead=lead, spec=spec, message=message, commit=commit)

    def classify_inbound(
        self,
        db: Session,
        spec: InboundReplySpec,
        *,
        commit: bool = True,
    ) -> ReplyClassificationJobResult:
        lead = db.get(Lead, spec.lead_id)
        if lead is None:
            raise ReplyClassificationError(f"Lead not found: {spec.lead_id}")
        sender_email = normalize_email(spec.sender_email)
        content_hash = reply_content_hash(
            subject=spec.subject,
            body=spec.body,
            sender_email=sender_email,
            provider_message_id=spec.provider_message_id,
        )
        existing = self._existing_classification(
            db,
            lead_id=lead.id,
            message_id=spec.message_id,
            provider_message_id=spec.provider_message_id,
            content_hash=content_hash,
        )
        if existing is not None:
            halt_before = _halt_value(read_operator_halt(db))
            return self._reuse(
                db,
                lead=lead,
                existing=existing,
                halt_before=halt_before,
                commit=commit,
            )
        message = self._existing_or_create_message(db, lead, spec)
        return self._run(db, lead=lead, spec=spec, message=message, commit=commit)

    def classify_lead(
        self,
        db: Session,
        lead_id: UUID,
        *,
        commit: bool = True,
    ) -> tuple[ReplyClassificationJobResult, ...]:
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise ReplyClassificationError(f"Lead not found: {lead_id}")
        messages = self._unclassified_inbound(db, lead_id=lead_id, limit=BATCH_MAX)
        return tuple(
            self.classify_message(db, message.id, commit=commit) for message in messages
        )

    def classify_batch(
        self,
        db: Session,
        *,
        limit: int = 50,
    ) -> tuple[ReplyClassificationJobResult, ...]:
        messages = self._unclassified_inbound(db, limit=min(max(limit, 1), BATCH_MAX))
        return tuple(self.classify_message(db, message.id, commit=True) for message in messages)

    def _run(
        self,
        db: Session,
        *,
        lead: Lead,
        spec: InboundReplySpec,
        message: OutreachMessage,
        commit: bool,
    ) -> ReplyClassificationJobResult:
        halt_before = _halt_value(read_operator_halt(db))
        sender_email = normalize_email(spec.sender_email) or _sender_email(db, message)
        content_hash = reply_content_hash(
            subject=spec.subject or message.subject,
            body=spec.body or message.body,
            sender_email=sender_email,
            provider_message_id=spec.provider_message_id or message.provider_message_id,
        )
        existing = self._existing_classification(
            db,
            lead_id=lead.id,
            message_id=message.id,
            provider_message_id=spec.provider_message_id or message.provider_message_id,
            content_hash=content_hash,
        )
        if existing is not None:
            return self._reuse(
                db,
                lead=lead,
                existing=existing,
                halt_before=halt_before,
                commit=commit,
            )

        request = ReplyClassificationRequest(
            lead_id=lead.id,
            subject=spec.subject or message.subject,
            body=spec.body or message.body,
            sender_email=sender_email,
            provider_message_id=spec.provider_message_id or message.provider_message_id,
            message_id=message.id,
        )
        try:
            provider_result = self._provider.classify(request)
        except ReplyClassifierError as exc:
            return self._fail(
                db,
                lead=lead,
                message=message,
                error=exc,
                halt_before=halt_before,
                commit=commit,
            )

        conversation = self._existing_or_create_conversation(db, lead)
        stage_before = _lead_stage(lead.stage)
        stage_after, applied, blocked = apply_conservative_transitions(
            stage_before,
            desired_reply_stages(provider_result.content.intent),
        )
        suppressed = self._apply_suppression(
            db,
            lead=lead,
            sender_email=sender_email,
            intent=provider_result.content.intent,
            explicit=provider_result.content.unsubscribe_explicit,
        )
        if suppressed and can_transition(stage_after, LeadStage.SUPPRESSED):
            applied = (*applied, LeadStage.SUPPRESSED)
            stage_after = LeadStage.SUPPRESSED
            blocked = False
        elif suppressed and stage_after is LeadStage.SUPPRESSED:
            blocked = False

        lead.stage = stage_after.value
        conversation.status = conversation_status_for(provider_result.content.intent).value
        conversation.summary = clip_text(
            f"Inbound reply classified as {provider_result.content.intent.value}.",
            SUMMARY_MAX_LENGTH,
        )
        outcome = _outcome_for(
            intent=provider_result.content.intent,
            applied=applied,
            blocked=blocked,
            suppressed=suppressed,
            empty=not (request.body or "").strip() and not (request.subject or "").strip(),
        )
        halt_after = _halt_value(read_operator_halt(db))
        row = ReplyClassification(
            lead_id=lead.id,
            outreach_message_id=message.id,
            conversation_id=conversation.id,
            provider_message_id=request.provider_message_id,
            sender_email=sender_email,
            intent=provider_result.content.intent.value,
            outcome=outcome.value,
            confidence=provider_result.content.confidence,
            provider_name=provider_result.audit.provider_name,
            schema_version=SCHEMA_VERSION,
            content_hash=content_hash,
            unsubscribe_explicit=provider_result.content.unsubscribe_explicit,
            suppressed=suppressed,
            outbound_attempted=False,
            live_call_attempted=provider_result.audit.live_call_attempted,
            lead_stage_before=stage_before.value,
            lead_stage_after=stage_after.value,
            conversation_status_after=conversation.status,
            matched_signals=list(provider_result.content.matched_signals),
            rationale_json=provider_result.content.to_dict(),
            audit_json=_audit_payload(
                provider_result,
                halt_before=halt_before,
                halt_after=halt_after,
                applied=[stage.value for stage in applied],
                blocked=blocked,
                meetings_created=0,
            ),
        )
        db.add(row)
        db.flush()
        self._record_activity(
            db,
            lead_id=lead.id,
            action=_activity_action(outcome),
            details={
                "classification_id": str(row.id),
                "message_id": str(message.id),
                "conversation_id": str(conversation.id),
                "intent": provider_result.content.intent.value,
                "outcome": outcome.value,
                "provider": provider_result.audit.provider_name,
                "confidence": provider_result.content.confidence,
                "matched_signals": list(provider_result.content.matched_signals),
                "unsubscribe_explicit": provider_result.content.unsubscribe_explicit,
                "suppressed": suppressed,
                "lead_stage_before": stage_before.value,
                "lead_stage_after": stage_after.value,
                "applied_stages": [stage.value for stage in applied],
                "blocked": blocked,
                "reused_existing": False,
                "outbound_attempted": False,
                "live_call_attempted": provider_result.audit.live_call_attempted,
                "operator_halt_before": halt_before,
                "operator_halt_after": halt_after,
                "fabricated_facts": False,
            },
        )
        if commit:
            db.commit()
        logger.info(
            "reply_classified",
            classification_id=str(row.id),
            lead_id=str(lead.id),
            intent=provider_result.content.intent.value,
            outcome=outcome.value,
        )
        return ReplyClassificationJobResult(
            classification_id=row.id,
            lead_id=lead.id,
            message_id=message.id,
            conversation_id=conversation.id,
            intent=provider_result.content.intent,
            outcome=outcome,
            provider_name=provider_result.audit.provider_name,
            reused_existing=False,
            suppressed=suppressed,
            lead_stage_before=stage_before.value,
            lead_stage_after=stage_after.value,
            outbound_attempted=False,
            live_call_attempted=provider_result.audit.live_call_attempted,
            operator_halt_before=halt_before,
            operator_halt_after=halt_after,
        )

    def _reuse(
        self,
        db: Session,
        *,
        lead: Lead,
        existing: ReplyClassification,
        halt_before: str,
        commit: bool,
    ) -> ReplyClassificationJobResult:
        halt_after = _halt_value(read_operator_halt(db))
        self._record_activity(
            db,
            lead_id=lead.id,
            action="reply_skipped",
            details={
                "classification_id": str(existing.id),
                "message_id": str(existing.outreach_message_id)
                if existing.outreach_message_id
                else None,
                "intent": existing.intent,
                "outcome": ReplyClassificationOutcome.SKIPPED.value,
                "reason": "already_classified",
                "reused_existing": True,
                "outbound_attempted": False,
                "live_call_attempted": False,
                "operator_halt_before": halt_before,
                "operator_halt_after": halt_after,
                "fabricated_facts": False,
            },
        )
        if commit:
            db.commit()
        intent: ReplyIntent | None
        try:
            intent = ReplyIntent(existing.intent)
        except ValueError:
            intent = None
        return ReplyClassificationJobResult(
            classification_id=existing.id,
            lead_id=lead.id,
            message_id=existing.outreach_message_id,
            conversation_id=existing.conversation_id,
            intent=intent,
            outcome=ReplyClassificationOutcome.SKIPPED,
            provider_name=existing.provider_name,
            reused_existing=True,
            suppressed=existing.suppressed,
            lead_stage_before=existing.lead_stage_before,
            lead_stage_after=lead.stage,
            outbound_attempted=False,
            live_call_attempted=False,
            operator_halt_before=halt_before,
            operator_halt_after=halt_after,
        )

    def _fail(
        self,
        db: Session,
        *,
        lead: Lead,
        message: OutreachMessage,
        error: ReplyClassifierError,
        halt_before: str,
        commit: bool,
    ) -> ReplyClassificationJobResult:
        halt_after = _halt_value(read_operator_halt(db))
        kind = "retryable" if error.retryable else "non_retryable"
        self._record_activity(
            db,
            lead_id=lead.id,
            action="reply_classification_failed",
            details={
                "message_id": str(message.id),
                "error": str(error),
                "failure_kind": kind,
                "retryable": error.retryable,
                "outbound_attempted": False,
                "live_call_attempted": False,
                "operator_halt_before": halt_before,
                "operator_halt_after": halt_after,
                "fabricated_facts": False,
            },
        )
        if commit:
            db.commit()
        logger.info(
            "reply_classification_failed",
            lead_id=str(lead.id),
            message_id=str(message.id),
            retryable=error.retryable,
        )
        return ReplyClassificationJobResult(
            classification_id=None,
            lead_id=lead.id,
            message_id=message.id,
            conversation_id=None,
            intent=None,
            outcome=ReplyClassificationOutcome.FAILED,
            provider_name="unknown",
            reused_existing=False,
            suppressed=False,
            lead_stage_before=lead.stage,
            lead_stage_after=lead.stage,
            outbound_attempted=False,
            live_call_attempted=False,
            operator_halt_before=halt_before,
            operator_halt_after=halt_after,
        )

    def _existing_classification(
        self,
        db: Session,
        *,
        lead_id: UUID,
        message_id: UUID | None,
        provider_message_id: str | None,
        content_hash: str,
    ) -> ReplyClassification | None:
        if message_id is not None:
            found = db.scalar(
                select(ReplyClassification).where(
                    ReplyClassification.outreach_message_id == message_id
                )
            )
            if found is not None:
                return found
        if provider_message_id:
            found = db.scalar(
                select(ReplyClassification).where(
                    ReplyClassification.provider_message_id == provider_message_id
                )
            )
            if found is not None:
                return found
        return db.scalar(
            select(ReplyClassification).where(
                ReplyClassification.lead_id == lead_id,
                ReplyClassification.content_hash == content_hash,
            )
        )

    def _existing_or_create_message(
        self,
        db: Session,
        lead: Lead,
        spec: InboundReplySpec,
    ) -> OutreachMessage:
        if spec.message_id is not None:
            message = db.get(OutreachMessage, spec.message_id)
            if message is None:
                raise ReplyClassificationError(f"Outreach message not found: {spec.message_id}")
            return message
        if spec.provider_message_id:
            existing = db.scalar(
                select(OutreachMessage).where(
                    OutreachMessage.provider_message_id == spec.provider_message_id
                )
            )
            if existing is not None:
                return existing
        message = OutreachMessage(
            lead_id=lead.id,
            contact_id=spec.contact_id,
            channel=CHANNEL_EMAIL,
            direction=MessageDirection.INBOUND.value,
            subject=spec.subject,
            body=spec.body,
            provider_message_id=spec.provider_message_id,
        )
        db.add(message)
        db.flush()
        return message

    def _existing_or_create_conversation(self, db: Session, lead: Lead) -> Conversation:
        conversation = db.scalar(
            select(Conversation)
            .where(Conversation.lead_id == lead.id)
            .order_by(Conversation.created_at.desc(), Conversation.id.desc())
        )
        if conversation is not None:
            return conversation
        conversation = Conversation(
            lead_id=lead.id,
            status=ConversationStatus.OPEN.value,
        )
        db.add(conversation)
        db.flush()
        return conversation

    def _unclassified_inbound(
        self,
        db: Session,
        *,
        lead_id: UUID | None = None,
        limit: int = 50,
    ) -> tuple[OutreachMessage, ...]:
        classified = select(ReplyClassification.outreach_message_id).where(
            ReplyClassification.outreach_message_id.is_not(None)
        )
        query = (
            select(OutreachMessage)
            .where(
                OutreachMessage.direction == MessageDirection.INBOUND.value,
                OutreachMessage.id.not_in(classified),
            )
            .order_by(OutreachMessage.created_at.asc(), OutreachMessage.id.asc())
        )
        if lead_id is not None:
            query = query.where(OutreachMessage.lead_id == lead_id)
        return tuple(db.scalars(query.limit(limit)).all())

    def _apply_suppression(
        self,
        db: Session,
        *,
        lead: Lead,
        sender_email: str | None,
        intent: ReplyIntent,
        explicit: bool,
    ) -> bool:
        if intent is not ReplyIntent.UNSUBSCRIBE and not explicit:
            return False
        email = normalize_email(sender_email)
        if email is None:
            return True
        existing = db.scalar(select(Suppression).where(Suppression.email == email))
        if existing is None:
            db.add(
                Suppression(
                    email=email,
                    reason="unsubscribe",
                    permanent=True,
                )
            )
            db.flush()
            return True
        existing.reason = existing.reason or "unsubscribe"
        existing.permanent = True
        db.flush()
        return True

    def _record_activity(
        self,
        db: Session,
        *,
        lead_id: UUID,
        action: str,
        details: dict[str, object],
    ) -> None:
        db.add(Activity(lead_id=lead_id, actor=REPLY_ACTOR, action=action, details=details))
        db.flush()


def apply_conservative_transitions(
    current: LeadStage,
    desired: tuple[LeadStage, ...],
) -> tuple[LeadStage, tuple[LeadStage, ...], bool]:
    stage = current
    applied: list[LeadStage] = []
    blocked = False
    for target in desired:
        if target is stage:
            continue
        if target in FORBIDDEN_REPLY_STAGES:
            blocked = True
            break
        if can_transition(stage, target):
            applied.append(target)
            stage = target
            continue
        blocked = True
        break
    return stage, tuple(applied), blocked


def _outcome_for(
    *,
    intent: ReplyIntent,
    applied: tuple[LeadStage, ...],
    blocked: bool,
    suppressed: bool,
    empty: bool,
) -> ReplyClassificationOutcome:
    if suppressed:
        return ReplyClassificationOutcome.SUPPRESSED
    if empty:
        return ReplyClassificationOutcome.SKIPPED
    if intent is ReplyIntent.UNKNOWN:
        return ReplyClassificationOutcome.UNKNOWN
    if intent in {ReplyIntent.OUT_OF_OFFICE, ReplyIntent.SPAM} and not applied:
        return ReplyClassificationOutcome.SKIPPED
    if blocked and not applied:
        return ReplyClassificationOutcome.BLOCKED
    return ReplyClassificationOutcome.CLASSIFIED


def _activity_action(outcome: ReplyClassificationOutcome) -> str:
    match outcome:
        case ReplyClassificationOutcome.CLASSIFIED:
            return "reply_classified"
        case ReplyClassificationOutcome.SKIPPED:
            return "reply_skipped"
        case ReplyClassificationOutcome.SUPPRESSED:
            return "reply_suppressed"
        case ReplyClassificationOutcome.BLOCKED:
            return "reply_blocked"
        case ReplyClassificationOutcome.UNKNOWN:
            return "reply_unknown"
        case ReplyClassificationOutcome.FAILED:
            return "reply_classification_failed"
        case _:
            _unreachable_outcome(outcome)


def _unreachable_outcome(value: ReplyClassificationOutcome) -> Never:
    raise RuntimeError(f"unhandled reply outcome: {value!r}")


def _audit_payload(
    provider_result: ReplyClassifierResult,
    *,
    halt_before: str,
    halt_after: str,
    applied: list[str],
    blocked: bool,
    meetings_created: int,
) -> dict[str, object]:
    return {
        **provider_result.audit.to_dict(),
        "applied_stages": applied,
        "blocked": blocked,
        "operator_halt_before": halt_before,
        "operator_halt_after": halt_after,
        "meetings_created": meetings_created,
        "outbound_attempted": False,
        "fabricated_facts": False,
    }


def _sender_email(db: Session, message: OutreachMessage) -> str | None:
    if message.contact_id is None:
        return None
    contact = db.get(Contact, message.contact_id)
    if contact is None:
        return None
    return normalize_email(contact.email)


def _lead_stage(value: str) -> LeadStage:
    try:
        return LeadStage(value)
    except ValueError:
        return LeadStage.DISCOVERED


def _halt_value(status: HaltStatus) -> str:
    return status.value
