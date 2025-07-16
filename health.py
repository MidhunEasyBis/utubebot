from http.server import SimpleHTTPRequestHandler, HTTPServer

PORT = 8000  # Same as Koyeb's health check port

class HealthCheckHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"OK")
        else:
            self.send_response(404)
            self.end_headers()

def run_health_server():
    server_address = ("0.0.0.0", PORT)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    httpd.serve_forever()

if __name__ == "__main__":
    run_health_server()
