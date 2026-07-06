"""Testes do diagnóstico do Mercado Livre."""

from unittest.mock import MagicMock, patch

from src.connectors.mercado_livre import diagnose_search


class TestDiagnoseSearch:
    @patch("src.connectors.mercado_livre.MercadoLivreConnector")
    def test_success_json(self, mock_connector_cls):
        mock_session = MagicMock()
        mock_connector_cls.return_value.session = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"results": [{"id": "MLB1", "title": "Charizard"}], "paging": {}}'
        mock_response.json.return_value = {
            "results": [{"id": "MLB1", "title": "Charizard"}],
            "paging": {},
        }
        mock_session.prepare_request.return_value = MagicMock(url="https://api.test/search?q=charizard")
        mock_session.send.return_value = mock_response

        result = diagnose_search("charizard")

        assert result.status_code == 200
        assert result.is_valid_json is True
        assert result.results_count == 1
        assert "results" in (result.json_top_level_keys or [])
        assert any("JSON válido" in s for s in result.suggestions)

    @patch("src.connectors.mercado_livre.MercadoLivreConnector")
    def test_forbidden_suggestions(self, mock_connector_cls):
        mock_session = MagicMock()
        mock_connector_cls.return_value.session = mock_session

        mock_response = MagicMock()
        mock_response.status_code = 403
        mock_response.text = "<html>Forbidden</html>"
        mock_response.json.side_effect = ValueError("not json")
        mock_session.prepare_request.return_value = MagicMock(url="https://api.test/search")
        mock_session.send.return_value = mock_response

        result = diagnose_search("charizard")

        assert result.status_code == 403
        assert result.is_valid_json is False
        assert any("403" in s for s in result.suggestions)

    @patch("src.connectors.mercado_livre.MercadoLivreConnector")
    def test_network_error(self, mock_connector_cls):
        import requests

        mock_session = MagicMock()
        mock_connector_cls.return_value.session = mock_session
        mock_session.prepare_request.return_value = MagicMock(url="https://api.test/search")
        mock_session.send.side_effect = requests.ConnectionError("connection failed")

        result = diagnose_search("charizard")

        assert result.status_code is None
        assert result.error_message is not None
        assert any("conexão" in s.lower() or "connection" in s.lower() for s in result.suggestions)
