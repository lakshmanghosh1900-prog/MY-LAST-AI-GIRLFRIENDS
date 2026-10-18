from __future__ import annotations

import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path

from my_last_ai_girlfriends.documents import DocumentError, chunk_text
from my_last_ai_girlfriends.http_api import MyLastAIGirlfriendsHTTPServer
from my_last_ai_girlfriends.service import MyLastAIGirlfriendsService
from my_last_ai_girlfriends.storage import Database

from test_budget_service import make_config


class DocumentTests(unittest.TestCase):
    def test_docx_and_bounded_pdf_text_are_extractable(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            workspace = root / "workspace"
            workspace.mkdir()
            with zipfile.ZipFile(workspace / "note.docx", "w") as archive:
                archive.writestr("word/document.xml", "<w:document xmlns:w='urn'><w:body><w:p><w:r><w:t>DOCX hello</w:t></w:r></w:p></w:body></w:document>")
            (workspace / "note.pdf").write_bytes(b"%PDF-1.4\nBT\n( PDF hello ) Tj\nET\n%%EOF")
            service = MyLastAIGirlfriendsService(make_config(root))
            docx = service.index_document("note.docx")
            pdf = service.index_document("note.pdf")
            self.assertEqual(docx["path"], "note.docx")
            self.assertEqual(pdf["path"], "note.pdf")
            self.assertIn("DOCX hello", service.answer_documents("DOCX hello")["answer"])
            self.assertIn("PDF hello", service.answer_documents("PDF hello")["answer"])
            service.close()

    def test_chunking_is_bounded_and_deterministic(self):
        text = "first paragraph\n" + ("x" * 300) + "\nlast paragraph"
        chunks = chunk_text(text, 128)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 128 for chunk in chunks))
        self.assertEqual(chunks, chunk_text(text, 128))

    def test_index_search_persists_and_delete_is_tombstoned(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir()
            (root / "workspace" / "notes.txt").write_text("Bengali books and local research", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            document = service.index_document("notes.txt")
            self.assertEqual(document["path"], "notes.txt")
            self.assertEqual(service.search_documents("research")[0]["path"], "notes.txt")
            self.assertEqual(service.db.connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0], 11)
            self.assertTrue(service.delete_document(document["id"]))
            self.assertEqual(service.search_documents("research"), [])
            service.close()

    def test_document_answer_is_local_bounded_and_cited(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir()
            (root / "workspace" / "notes.txt").write_text("Bengali books are useful for local research.", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            document = service.index_document("notes.txt")
            answer = service.answer_documents("Bengali research")
            self.assertFalse(answer["ai_generated"])
            self.assertEqual(answer["evidence_status"], "SUPPORTED_EVIDENCE")
            self.assertIn("Local evidence", answer["answer"])
            self.assertEqual(answer["citations"][0]["path"], "notes.txt")
            self.assertEqual(answer["citations"][0]["content_sha256"], document["content_sha256"])
            insufficient = service.answer_documents("unknown phrase")
            self.assertEqual(insufficient["citations"], [])
            self.assertEqual(insufficient["evidence_status"], "INSUFFICIENT_EVIDENCE")
            self.assertIn("no answer was generated", insufficient["answer"])
            service.delete_document(document["id"])
            self.assertEqual(service.answer_documents("Bengali research")["citations"], [])
            service.close()

    def test_file_boundary_and_empty_query_are_enforced(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir()
            service = MyLastAIGirlfriendsService(make_config(root))
            with self.assertRaises(DocumentError):
                service.index_document("../outside.txt")
            with self.assertRaisesRegex(DocumentError, "query"):
                service.search_documents(" ")
            service.close()

    def test_authenticated_document_api(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "workspace").mkdir()
            (root / "workspace" / "guide.md").write_text("safe local guide", encoding="utf-8")
            service = MyLastAIGirlfriendsService(make_config(root))
            server = MyLastAIGirlfriendsHTTPServer(("127.0.0.1", 0), service)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=3)
            headers = {"Authorization": "Bearer " + "T" * 48, "Content-Type": "application/json"}
            try:
                connection.request("POST", "/v1/documents", body=json.dumps({"path": "guide.md"}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 201)
                document = json.loads(response.read())
                connection.request("GET", "/v1/documents/search?q=guide", headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(json.loads(response.read())["results"][0]["id"], document["id"])
                connection.request("POST", "/v1/documents/answer", body=json.dumps({"query": "safe guide"}), headers=headers)
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                answer = json.loads(response.read())
                self.assertFalse(answer["ai_generated"])
                self.assertEqual(answer["evidence_status"], "SUPPORTED_EVIDENCE")
            finally:
                connection.close()
                server.shutdown()
                server.server_close()
                service.close()


if __name__ == "__main__":
    unittest.main()
