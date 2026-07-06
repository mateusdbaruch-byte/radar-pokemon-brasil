"""Testes do diagnóstico do Reddit."""

from unittest.mock import MagicMock, patch

from src.connectors.reddit import DEFAULT_USER_AGENT, diagnose_search


class TestRedditDiagnoseSearch:
    @patch("src.connectors.reddit.requests.Session")
    def test_success_no_oauth(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"data": {"children": [{"data": {"title": "WTB Charizard"}}]}}'
        mock_response.json.return_value = {
            "data": {"children": [{"data": {"title": "WTB Charizard"}}]},
        }
        mock_session.prepare_request.return_value = MagicMock(
            url="https://www.reddit.com/search.json?q=test",
            method="GET",
        )
        mock_session.send.return_value = mock_response

        result = diagnose_search("pokemon tcg brasil charizard")

        assert result.method == "GET"
        assert result.status_code == 200
        assert result.is_valid_json is True
        assert result.posts_count == 1
        assert result.needs_oauth is False
        assert "sem OAuth" in result.oauth_message

    @patch("src.connectors.reddit.requests.Session")
    def test_forbidden_no_oauth(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "<html><body>Blocked</body></html>"
        mock_response.json.side_effect = ValueError("not json")
        mock_session.prepare_request.return_value = MagicMock(
            url="https://www.reddit.com/search.json",
            method="GET",
        )
        mock_session.send.return_value = mock_response

        result = diagnose_search("charizard", user_agent=DEFAULT_USER_AGENT)

        assert result.status_code == 403
        assert result.needs_oauth is False
        assert "403" in result.oauth_message
        assert any("403" in s for s in result.suggestions)

    @patch("src.connectors.reddit.requests.Session")
    def test_unauthorized_needs_oauth(self, mock_session_cls):
        mock_session = MagicMock()
        mock_session_cls.return_value = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = '{"error": "unauthorized"}'
        mock_response.json.return_value = {"error": "unauthorized"}
        mock_session.prepare_request.return_value = MagicMock(
            url="https://www.reddit.com/search.json",
            method="GET",
        )
        mock_session.send.return_value = mock_response

        result = diagnose_search("charizard")

        assert result.needs_oauth is True
        assert "OAuth" in result.oauth_message
