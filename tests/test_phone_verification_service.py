from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tests.fixtures.decision_makers import candidate
from vyro_growth.config import Settings
from vyro_growth.domain import (
    ContactDiscoveryCallStatus,
    ContactFactType,
    ReviewArtifactType,
    ReviewDecisionStatus,
)
from vyro_growth.models import (
    Activity,
    Contact,
    ContactDiscoveryCall,
    Meeting,
    OutreachMessage,
    SourceEvidence,
    Suppression,
)
from vyro_growth.providers.decision_makers import StaticDecisionMakerEnrichmentProvider
from vyro_growth.services.contact_enrichment import ContactEnrichmentService
from vyro_growth.services.operator_halt import HaltStatus, read_operator_halt, set_operator_halt
from vyro_growth.services.outbound_guard import OutboundAction, OutboundGuard, normalize_phone
from vyro_growth.services.phone_verification import (
    PHONE_VERIFICATION_SOURCE,
    PhoneVerificationError,
    PhoneVerificationOutcomeInput,
    PhoneVerificationService,
    format_phone_verification_queue,
)
from vyro_growth.services.review_queue import ReviewQueueService

PROSPECT_PHONE = "5125550199"
PROSPECT_EMAIL = "jordan.blake@austinfamily.example"
PROSPECT_NAME = "Jordan Blake"


def _org(db: Session, **overrides: object):
    from vyro_growth.models import Organization

    values: dict[str, object] = {
        "name": "AUSTIN FAMILY MEDICINE PLLC",
        "npi": "1487448189",
        "city": "AUSTIN",
        "state": "TX",
        "specialty": "Family Medicine",
        "website": "https://austinfamily.example",
        "website_match_status": "verified",
    }
    values.update(overrides)
    organization = Organization(**values)
    db.add(organization)
    db.flush()
    return organization


def _settings(**overrides: object) -> Settings:
    return Settings(**overrides)


def _dump(value: object) -> str:
    return json.dumps(value, default=str)


def test_no_contact_found_queues_human_task(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    result = ContactEnrichmentService(
        StaticDecisionMakerEnrichmentProvider(())
    ).enrich_organization(db_session, organization.id)

    assert result.contacts_upserted == 0
    assert result.phone_verification_queued is True
    assert result.phone_verification_task_id is not None
    task = db_session.get(ContactDiscoveryCall, result.phone_verification_task_id)
    assert task is not None
    assert task.status == ContactDiscoveryCallStatus.QUEUED.value
    assert task.queued_reason == "no_contact_found"
    assert task.live_call_attempted is False
    assert task.voice_provider_used is False
    assert task.autodial_attempted is False
    assert task.executed is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    queue = ReviewQueueService().list_queue(db_session, _settings())
    match = next(
        item
        for item in queue.items
        if item.artifact_type == ReviewArtifactType.CONTACT_DISCOVERY_CALL.value
    )
    assert match.artifact_id == task.id
    assert match.executable_later is False
    assert match.executed is False
    assert "no_call_placed" in match.risk_labels
    assert "no_ai_voice" in match.risk_labels
    assert PROSPECT_PHONE not in match.title
    assert PROSPECT_PHONE not in match.summary


def test_found_contact_does_not_queue_task(db_session: Session) -> None:
    organization = _org(db_session)
    ContactEnrichmentService(
        StaticDecisionMakerEnrichmentProvider((candidate(),))
    ).enrich_organization(db_session, organization.id)
    assert db_session.scalar(select(func.count()).select_from(ContactDiscoveryCall)) == 0
    assert db_session.scalar(select(Contact)) is not None


def test_queue_is_idempotent_for_the_same_organization(db_session: Session) -> None:
    organization = _org(db_session)
    service = PhoneVerificationService()
    first = service.queue_for_organization(db_session, organization.id)
    second = service.queue_for_organization(db_session, organization.id)
    assert first.task_id == second.task_id
    assert second.reused is True
    assert db_session.scalar(select(func.count()).select_from(ContactDiscoveryCall)) == 1


def test_record_decision_maker_identified_stores_phone_verification_fact(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    result = PhoneVerificationService().record_outcome(
        db_session,
        queued.task_id,
        PhoneVerificationOutcomeInput(
            outcome=ContactDiscoveryCallStatus.DECISION_MAKER_IDENTIFIED.value,
            operator="ops",
            full_name=PROSPECT_NAME,
            title="Practice Manager",
            phone=PROSPECT_PHONE,
            email=PROSPECT_EMAIL,
            notes="Reached front desk then manager",
        ),
    )

    assert result.status == ContactDiscoveryCallStatus.DECISION_MAKER_IDENTIFIED.value
    assert result.contact_fact_created is True
    assert result.live_call_attempted is False
    assert result.voice_provider_used is False
    assert result.has_phone is True
    assert result.has_email is True
    assert PROSPECT_PHONE not in _dump(result)
    contact = db_session.scalar(select(Contact))
    assert contact is not None
    assert contact.source_provider == PHONE_VERIFICATION_SOURCE
    assert contact.full_name == PROSPECT_NAME
    assert contact.phone == PROSPECT_PHONE
    evidence = db_session.scalar(
        select(SourceEvidence).where(
            SourceEvidence.claim_type == ContactFactType.PHONE_VERIFICATION.value
        )
    )
    assert evidence is not None
    assert evidence.extracted_value == ContactDiscoveryCallStatus.DECISION_MAKER_IDENTIFIED.value
    assert evidence.metadata_json["source_provider"] == PHONE_VERIFICATION_SOURCE
    assert PROSPECT_PHONE not in _dump(evidence.metadata_json)
    activity = db_session.scalar(
        select(Activity).where(Activity.action == "phone_verification_outcome_recorded")
    )
    assert activity is not None
    assert PROSPECT_PHONE not in _dump(activity.details)
    assert PROSPECT_EMAIL not in _dump(activity.details)
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0
    assert db_session.scalar(select(func.count()).select_from(Meeting)) == 0
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    assert Settings().outbound_enabled is False


def test_do_not_contact_creates_suppression_and_blocks_dial(
    db_session: Session,
) -> None:
    set_operator_halt(db_session, halted=True, reason="incident")
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    result = PhoneVerificationService().record_outcome(
        db_session,
        queued.task_id,
        PhoneVerificationOutcomeInput(
            outcome=ContactDiscoveryCallStatus.DO_NOT_CONTACT.value,
            phone=PROSPECT_PHONE,
            email=PROSPECT_EMAIL,
        ),
    )

    assert result.status == ContactDiscoveryCallStatus.DO_NOT_CONTACT.value
    assert result.suppression_created is True
    suppression = db_session.scalar(select(Suppression))
    assert suppression is not None
    assert suppression.reason == "do_not_contact"
    assert suppression.phone == normalize_phone(PROSPECT_PHONE)
    assert suppression.permanent is True
    guard = OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False))
    set_operator_halt(db_session, halted=False, reason="test_clear")
    decision = guard.evaluate(
        db_session,
        action=OutboundAction.PHONE_DIAL,
        phone=PROSPECT_PHONE,
        consent_to_call=True,
    )
    assert decision.allowed is False
    assert decision.reason == "suppressed"
    listed = PhoneVerificationService().list_tasks(
        db_session,
        _settings(),
        include_completed=True,
    )
    payload = format_phone_verification_queue(listed, as_json=True)
    assert PROSPECT_PHONE not in payload
    assert PROSPECT_EMAIL not in payload
    assert "do_not_contact" in payload


def test_no_answer_does_not_create_contact_or_call(db_session: Session) -> None:
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    result = PhoneVerificationService().record_outcome(
        db_session,
        queued.task_id,
        PhoneVerificationOutcomeInput(outcome=ContactDiscoveryCallStatus.NO_ANSWER.value),
    )
    assert result.status == ContactDiscoveryCallStatus.NO_ANSWER.value
    assert result.contact_fact_created is False
    assert result.suppression_created is False
    assert db_session.scalar(select(Contact)) is None
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0


def test_review_decision_does_not_place_a_call(db_session: Session) -> None:
    set_operator_halt(db_session, halted=True, reason="keep-halted")
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    recorded = ReviewQueueService().record_decision(
        db_session,
        artifact_type=ReviewArtifactType.CONTACT_DISCOVERY_CALL.value,
        artifact_id=queued.task_id,
        decision=ReviewDecisionStatus.APPROVED.value,
        reviewer="ops",
    )
    assert recorded.executed is False
    assert recorded.live_call_attempted is False
    assert recorded.outbound_attempted is False
    item = ReviewQueueService().get_item(
        db_session,
        _settings(),
        artifact_type=ReviewArtifactType.CONTACT_DISCOVERY_CALL.value,
        artifact_id=queued.task_id,
    )
    assert item is not None
    assert item.executable_later is False
    assert item.executed is False
    assert read_operator_halt(db_session) is HaltStatus.HALTED
    task = db_session.get(ContactDiscoveryCall, queued.task_id)
    assert task is not None
    assert task.status == ContactDiscoveryCallStatus.QUEUED.value
    assert task.live_call_attempted is False


def test_missing_name_rejects_decision_maker_identified(db_session: Session) -> None:
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    try:
        PhoneVerificationService().record_outcome(
            db_session,
            queued.task_id,
            PhoneVerificationOutcomeInput(
                outcome=ContactDiscoveryCallStatus.DECISION_MAKER_IDENTIFIED.value
            ),
        )
    except PhoneVerificationError as exc:
        assert exc.code == "missing_name"
    else:
        raise AssertionError("expected missing_name")
    assert db_session.scalar(select(Contact)) is None


def test_sanitized_list_omits_unsafe_fields(db_session: Session) -> None:
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    PhoneVerificationService().record_outcome(
        db_session,
        queued.task_id,
        PhoneVerificationOutcomeInput(
            outcome=ContactDiscoveryCallStatus.WRONG_NUMBER.value,
            notes=f"Number {PROSPECT_PHONE} was a fax",
        ),
    )
    listed = PhoneVerificationService().list_tasks(
        db_session, _settings(), include_completed=True
    )
    payload = format_phone_verification_queue(listed, as_json=True)
    assert PROSPECT_PHONE not in payload
    assert organization.name not in payload
    assert listed.items[0].status == ContactDiscoveryCallStatus.WRONG_NUMBER.value
    assert listed.live_call_attempted is False
    assert listed.voice_provider_used is False
    assert listed.outbound_attempted is False
    assert listed.outbound_enabled is False


def test_refused_and_completed_are_terminal_without_side_effects(db_session: Session) -> None:
    first = _org(db_session, npi="1487448189")
    second = _org(db_session, npi="1487448190", name="ROUND ROCK FAMILY MEDICINE PLLC")
    queued_first = PhoneVerificationService().queue_for_organization(db_session, first.id)
    queued_second = PhoneVerificationService().queue_for_organization(db_session, second.id)
    refused = PhoneVerificationService().record_outcome(
        db_session,
        queued_first.task_id,
        PhoneVerificationOutcomeInput(outcome=ContactDiscoveryCallStatus.REFUSED.value),
    )
    completed = PhoneVerificationService().record_outcome(
        db_session,
        queued_second.task_id,
        PhoneVerificationOutcomeInput(outcome=ContactDiscoveryCallStatus.COMPLETED.value),
    )
    assert refused.status == ContactDiscoveryCallStatus.REFUSED.value
    assert completed.status == ContactDiscoveryCallStatus.COMPLETED.value
    assert db_session.scalar(select(Contact)) is None
    assert db_session.scalar(select(Suppression)) is None
    assert db_session.scalar(select(func.count()).select_from(OutreachMessage)) == 0


def test_do_not_contact_without_phone_suppresses_organization(db_session: Session) -> None:
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    result = PhoneVerificationService().record_outcome(
        db_session,
        queued.task_id,
        PhoneVerificationOutcomeInput(outcome=ContactDiscoveryCallStatus.DO_NOT_CONTACT.value),
    )
    assert result.suppression_created is True
    suppression = db_session.scalar(select(Suppression))
    assert suppression is not None
    assert suppression.organization_id == organization.id
    assert suppression.reason == "do_not_contact"
    assert suppression.phone is None
    assert suppression.email is None
    guard = OutboundGuard(Settings(outbound_enabled=True, outbound_halted=False))
    set_operator_halt(db_session, halted=False, reason="test_clear")
    decision = guard.evaluate(
        db_session,
        action=OutboundAction.PHONE_DIAL,
        phone=PROSPECT_PHONE,
        organization_id=organization.id,
        consent_to_call=True,
    )
    assert decision.allowed is False
    assert decision.reason == "suppressed"


def test_outbound_enabled_cannot_record_a_live_call(db_session: Session) -> None:
    organization = _org(db_session)
    queued = PhoneVerificationService().queue_for_organization(db_session, organization.id)
    try:
        PhoneVerificationService(_settings(outbound_enabled=True)).record_outcome(
            db_session,
            queued.task_id,
            PhoneVerificationOutcomeInput(outcome=ContactDiscoveryCallStatus.NO_ANSWER.value),
        )
    except RuntimeError as exc:
        assert "OUTBOUND_ENABLED=false" in str(exc)
    else:
        raise AssertionError("expected outbound-enabled record to fail closed")
    task = db_session.get(ContactDiscoveryCall, queued.task_id)
    assert task is not None
    assert task.status == ContactDiscoveryCallStatus.QUEUED.value
    assert task.live_call_attempted is False
