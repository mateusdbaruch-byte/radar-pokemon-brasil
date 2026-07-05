"""Testes de política/aprovação Reddit."""

from src.connector_health import HealthStatus
from src.reddit_policy import (
    REDDIT_PENDING_MESSAGE,
    get_reddit_policy_status,
    is_reddit_policy_block,
    map_reddit_diagnostic_to_health,
)


class TestRedditPolicy:
    def test_detect_403(self):
        assert is_reddit_policy_block(403, "") is True

    def test_detect_policy_keyword(self):
        assert is_reddit_policy_block(200, "Responsible Builder Policy required") is True

    def test_map_403_to_pending_approval(self):
        health = map_reddit_diagnostic_to_health(
            status_code=403,
            response_preview="<html>forbidden</html>",
            auth_mode="oauth_app",
            auth_status="pending_approval",
            is_valid_json=False,
            posts_count=None,
            error_message=None,
            suggestions=[],
        )
        assert health.status == HealthStatus.PENDING_APPROVAL
        assert REDDIT_PENDING_MESSAGE in health.message

    def test_map_missing_credentials_requires_auth(self):
        health = map_reddit_diagnostic_to_health(
            status_code=None,
            response_preview="",
            auth_mode="none",
            auth_status="missing_credentials",
            is_valid_json=False,
            posts_count=None,
            error_message=None,
            suggestions=[],
        )
        assert health.status == HealthStatus.REQUIRES_AUTH

    def test_policy_status_defaults(self):
        status = get_reddit_policy_status()
        assert isinstance(status.env_exists, bool)
        assert isinstance(status.next_action, str)
