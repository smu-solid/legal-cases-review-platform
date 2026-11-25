"""Composition of application services and portable storage."""

from typing import cast

from pydantic import SecretStr

from review_platform.auth.service import AuthService
from review_platform.dataset.catalog import DatasetCatalog
from review_platform.dataset.fixture_reader import FixtureDatasetReader
from review_platform.db.session import Database
from review_platform.email import EmailSender, build_email_sender
from review_platform.review.allocation.service import AllocationService
from review_platform.review.artifact_store import ArtifactStore, build_artifact_store
from review_platform.review.service import ReviewService
from review_platform.settings import Settings


class AppContext:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = Database(settings.database_url, pool=settings.review_pool)
        self.auth = AuthService(settings)
        self.email: EmailSender = build_email_sender(settings)
        self.catalog = DatasetCatalog(settings.dataset_path)
        audit_key = cast(SecretStr, settings.audit_hmac_key).get_secret_value()
        self.review = ReviewService(
            FixtureDatasetReader(settings.synthetic_fixture_root),
            audit_key,
            synthetic_enabled=settings.synthetic_import_enabled,
            campaign_filter_database=self.catalog,
        )
        self.artifact_store: ArtifactStore | None = build_artifact_store(settings)
        self.allocation = AllocationService(audit_key)
