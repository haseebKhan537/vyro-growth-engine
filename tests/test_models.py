from __future__ import annotations

import vyro_growth.models as models
from vyro_growth.database import Base
from vyro_growth.domain import LeadStage
from vyro_growth.models import Lead, OperatorControl, Organization, Suppression

PHASE_ONE_MODELS = (
    Organization,
    models.Contact,
    Lead,
    models.LeadScore,
    models.Campaign,
    models.OutreachMessage,
    models.Conversation,
    models.Meeting,
    models.Activity,
    Suppression,
    models.SourceEvidence,
    models.DiscoveryRun,
    models.EnrichmentRun,
    models.OperatorControl,
    models.PersonalizationDraft,
    models.OutreachPlanRun,
    models.CampaignEnrollment,
    models.ReplyClassification,
    models.BookingPlanRun,
    models.BookingPlan,
    models.VoiceQualificationRun,
    models.VoiceQualificationPlan,
    models.OptimizerRun,
    models.OptimizerRecommendation,
)


def test_models_importable() -> None:
    assert models.Organization is Organization
    assert models.Suppression is Suppression
    assert models.OperatorControl is OperatorControl


def test_metadata_registers_all_phase_one_tables() -> None:
    table_names = set(Base.metadata.tables)
    expected = {model.__tablename__ for model in PHASE_ONE_MODELS}
    assert expected.issubset(table_names)


def test_lead_default_stage() -> None:
    assert Lead.__table__.c.stage.default.arg == LeadStage.DISCOVERED.value
