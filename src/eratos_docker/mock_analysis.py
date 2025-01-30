import requests
import json
import posixpath
from http.server import HTTPServer, BaseHTTPRequestHandler


class DocumentUploadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        response = json.dumps(
            {
                "documentid": self.document_id,
                "value": self.server.documents.get(self.document_id, ""),
                "valuetruncated": False,
                "organisationid": "csiro",
                "groupids": [],
            }
        ).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(response))
        self.end_headers()
        self.wfile.write(response)

    def do_PUT(self):
        length = int(self.headers.get("content-length"))
        upload = json.loads(self.rfile.read(length).decode())

        self.server.documents[self.document_id] = upload["value"]

        self.do_GET()

    def log_message(self, format_, *log_args):
        pass  # Inhibit log messages.

    @property
    def document_id(self):
        path_parts = self.path.strip(posixpath.sep).split(posixpath.sep)
        return path_parts[3]  # api/analysis/documentnodes/<document_id>


class MockAnalysisService(HTTPServer):
    def __init__(self):
        super(MockAnalysisService, self).__init__(
            ("localhost", 18080), DocumentUploadHandler
        )

    def handle_timeout(self):
        pass
