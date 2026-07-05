"""Testes de autenticação Reddit."""

from unittest.mock import MagicMock, patch

from src.reddit_auth import (
    RedditAuthResult,
    RedditAuthStatus,
    authenticate_reddit,
    credential_requirements_met,
    inspect_reddit_env,
)


class TestRedditAuth:
  @patch.dict("os.environ", {}, clear=True)
  def test_missing_credentials(self):
      ok, msg = credential_requirements_met()
      assert ok is False
      assert "REDDIT_CLIENT_ID" in msg

  @patch.dict(
      "os.environ",
      {
          "REDDIT_CLIENT_ID": "id",
          "REDDIT_CLIENT_SECRET": "secret",
          "REDDIT_USER_AGENT": "python:test:1.0 (by /u/test)",
      },
  )
  def test_credentials_met(self):
      ok, _ = credential_requirements_met()
      assert ok is True

  @patch.dict("os.environ", {}, clear=True)
  def test_public_mode_without_oauth(self):
      with patch.dict("os.environ", {"REDDIT_USER_AGENT": "python:test:1.0"}):
          result = authenticate_reddit()
      assert result.status == RedditAuthStatus.PUBLIC

  @patch.dict(
      "os.environ",
      {
          "REDDIT_CLIENT_ID": "id",
          "REDDIT_CLIENT_SECRET": "secret",
          "REDDIT_USER_AGENT": "python:test:1.0 (by /u/test)",
      },
  )
  @patch("src.reddit_auth.requests.Session")
  def test_oauth_success(self, mock_session_cls):
      mock_session = MagicMock()
      mock_session_cls.return_value = mock_session
      mock_resp = MagicMock()
      mock_resp.status_code = 200
      mock_resp.json.return_value = {"access_token": "tok123"}
      mock_session.post.return_value = mock_resp

      result = authenticate_reddit(mock_session)
      assert result.status == RedditAuthStatus.LIVE
      assert result.token_obtained is True

  @patch.dict(
      "os.environ",
      {
          "REDDIT_CLIENT_ID": "id",
          "REDDIT_CLIENT_SECRET": "bad",
          "REDDIT_USER_AGENT": "python:test:1.0 (by /u/test)",
      },
  )
  @patch("src.reddit_auth.requests.Session")
  def test_oauth_failure(self, mock_session_cls):
      mock_session = MagicMock()
      mock_session_cls.return_value = mock_session
      mock_resp = MagicMock()
      mock_resp.status_code = 401
      mock_session.post.return_value = mock_resp

      result = authenticate_reddit(mock_session)
      assert result.status == RedditAuthStatus.AUTH_FAILED
