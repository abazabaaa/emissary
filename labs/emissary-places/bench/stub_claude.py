#!/usr/bin/env python3
"""Local stand-in for the Messages API, for demos without an API key. Returns a canned transcription."""
import http.server, json, sys

REPLY = {"id": "msg_stub", "type": "message", "role": "assistant", "model": "claude-opus-5 (LOCAL STUB)",
         "content": [{"type": "text", "text": "[STUB TRANSCRIPTION - not a real Claude response]\n# SETTLEMENT AGREEMENT\n"
                      "Party A: Acme Corporation\nParty B: Globex LLC\nAmount: $250,000\nSigned: March 3, 2026"}],
         "stop_reason": "end_turn", "stop_sequence": None, "usage": {"input_tokens": 1650, "output_tokens": 48}}

class H(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        req = json.loads(body)
        kinds = [b["type"] for b in req["messages"][0]["content"]]
        sys.stderr.write(f"stub: model={req['model']} max_tokens={req['max_tokens']} blocks={kinds} "
                         f"effort={req.get('output_config', {}).get('effort')} fallbacks={req.get('fallbacks')}\n")
        out = json.dumps(REPLY).encode()
        self.send_response(200); self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(out))); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass

http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8099), H).serve_forever()
