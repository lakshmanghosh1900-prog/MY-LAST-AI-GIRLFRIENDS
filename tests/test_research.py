from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer
from my_last_ai_girlfriends.research import ResearchError, validate_research_url
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.tools import FetchResult

from test_budget_service import make_config


class ResearchTests(unittest.TestCase):
    def test_research_url_rejects_secret_like_query_parameters(self):
        with self.assertRaisesRegex(ResearchError, "secret-like"):
            validate_research_url("https://example.com/article?api_key=hidden")
        self.assertEqual(validate_research_url("https://example.com/article?topic=local"), "https://example.com/article?topic=local")

    def test_research_run_persists_sources_citations_and_partial_failures(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            service.web_tool.fetch = Mock(side_effect=[
                FetchResult("https://example.com/a", "text/html", "First sourced fact", 20),
                ResearchError("PRIVATE_DESTINATION", "blocked"),
            ])
            result = service.run_research(["https://example.com/a", "https://example.com/b"])
            self.assertEqual(result["status"], "PARTIAL")
            self.assertEqual(len(result["citations"]), 1)
            self.assertEqual(result["citations"][0]["label"], "S1")
            self.assertTrue(result["citations"][0]["content_sha256"])
            self.assertEqual(service.research_run(result["id"])["status"], "PARTIAL")
            service.close()

    def test_research_evidence_is_heuristic_and_cites_sources(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            service.web_tool.fetch = Mock(return_value=FetchResult("https://example.com/a", "text/plain", "Bengali support is available.", 32))
            run = service.run_research(["https://example.com/a"])
            evidence = service.analyze_research_evidence(run["id"], ["Bengali support is available"])
            self.assertEqual(evidence["results"][0]["classification"], "SUPPORTED_EVIDENCE")
            self.assertTrue(evidence["results"][0]["citations"][0]["content_sha256"])
            self.assertTrue(evidence["heuristic"])
            insufficient = service.analyze_research_evidence(run["id"], ["Android hardware is available"])
            self.assertEqual(insufficient["results"][0]["classification"], "INSUFFICIENT_EVIDENCE")
            service.close()

    def test_research_preserves_source_ordinals_and_reports_conflicting_stances(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            service.web_tool.fetch = Mock(side_effect=[
                FetchResult("https://example.com/a", "text/plain", "Bengali support is available.", 32),
                FetchResult("https://example.com/b", "text/plain", "Bengali support is not available.", 36),
            ])
            run = service.run_research(["https://example.com/a", "https://example.com/b"])
            self.assertEqual([citation["label"] for citation in run["citations"]], ["S1", "S2"])
            evidence = service.analyze_research_evidence(run["id"], ["Bengali support is available"])
            result = evidence["results"][0]
            self.assertEqual(result["classification"], "CONFLICTING_EVIDENCE")
            self.assertEqual([citation["stance"] for citation in result["citations"]], ["supporting", "conflicting"])
            self.assertEqual([citation["label"] for citation in result["citations"]], ["S1", "S2"])
            service.close()

    def test_authenticated_research_api_rejects_invalid_shape_and_returns_sources(self):
        with tempfile.TemporaryDirectory() as raw:
            service = MyLastAIGirlfriendsService(make_config(Path(raw)))
            service.web_tool.fetch = Mock(return_value=FetchResult("https://example.com/a", "text/plain", "public evidence", 15))
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            headers = {"Authorization": "Bearer " + "T" * 48, "Content-Type": "application/json"}
            try:
                connection.request("POST", "/v1/research", body=json.dumps({"urls": "not-a-list"}), headers=headers)
                self.assertEqual(connection.getresponse().status, 400)
                connection.request("POST", "/v1/research", body=json.dumps({"urls": ["https://example.com/a"]}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                payload = json.loads(response.read())
                self.assertEqual(payload["citations"][0]["label"], "S1")
                connection.request("POST", f"/v1/research/{payload['id']}/evidence", body=json.dumps({"claims": ["public evidence"]}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["results"][0]["classification"], "SUPPORTED_EVIDENCE")
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
