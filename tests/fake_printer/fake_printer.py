"""Fake Zortrax printer for local testing: JSON on TCP 8002, FTP on 8003 (pyftpdlib), UDP 8001 discovery.

Usage: python3 fake_printer.py STORAGE_DIR [--host 127.0.0.1]
Logs every command to STORAGE_DIR/commands.log.
"""
import argparse, base64, json, os, socket, socketserver, struct, threading, time

# 1x1 grey JPEG
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA=")

CAMERA_FILE = os.environ.get("FAKE_CAMERA_JPEG")

STATE = {"printerStatus": "idling", "progress": 0, "filename": "", "lights": "off"}


def log(storage, entry):
    with open(os.path.join(storage, "commands.log"), "a") as f:
        f.write(json.dumps(entry) + "\n")


def handle(storage, cmd):
    t = cmd.get("type")
    log(storage, cmd)
    ok = {"type": t, "status": "1"}
    if t == "status":
        f = {"hotendTemperature": 245 if STATE["printerStatus"] == "printing" else 30, "heatbedTemperature": 80,
             "printerStatus": STATE["printerStatus"], "storageBytesFree": 3843940352, "storageBytesTotal": 4019163136,
             "currentMaterial": "Z-ABS", "serialNumber": "FAKE0001", "currentMaterialId": 0,
             "printingInProgress": 1 if STATE["printerStatus"] == "printing" else 0}
        ok["fields"] = [{"name": k, "value": f.get(k, 0)} for k in cmd.get("fields", [])]
    elif t == "printStatus":
        if STATE["printerStatus"] == "idling":
            return {"type": t, "status": "2"}  # what the real M200 Plus (firmware 2.6.15) answers when idle
        if STATE["printerStatus"] == "printing":
            STATE["progress"] = min(100, STATE["progress"] + 5)
        f = {"progress": STATE["progress"], "filename": STATE["filename"], "metadata": json.dumps({"PrintTime": 1800}), "userSettings": ""}
        ok["fields"] = [{"name": k, "value": f.get(k)} for k in cmd.get("fields", [])]
    elif t == "version":
        f = {"protocol": 1, "firmware": "2.6.15", "software": 23727, "hardware": 24}  # types as the real printer
        ok["fields"] = [{"name": k, "value": f.get(k)} for k in cmd.get("fields", [])]
    elif t == "getCameraPreview":
        ok["cameraPreviewData"] = base64.b64encode(open(CAMERA_FILE, "rb").read() if CAMERA_FILE else JPEG).decode()
    elif t == "printFromStorage":
        path = os.path.join(storage, cmd["path"])
        if cmd["path"].startswith("/") or not os.path.exists(path):  # the real printer wants a bare name
            return {"type": t, "status": "3", "startPrintAdditionalInfo": 1}
        STATE.update(printerStatus="printing", progress=0, filename=os.path.basename(path))
    elif t in ("pause", "resume", "abort"):
        STATE["printerStatus"] = {"pause": "paused", "resume": "printing", "abort": "idling"}[t]
    elif t == "setSetting":
        for s in cmd.get("settings", []):
            STATE[s["name"]] = s["value"]
    elif t == "getSetting":
        ok["fields"] = [{"name": k, "value": STATE.get(k)} for k in cmd.get("fields", [])]
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("storage")
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    os.makedirs(a.storage, exist_ok=True)

    class H(socketserver.BaseRequestHandler):
        def handle(self):
            n = struct.unpack("!H", self.request.recv(2))[0]
            body = b""
            while len(body) < n:
                body += self.request.recv(n - len(body))
            req = json.loads(body)
            resp = {"responses": [handle(a.storage, c) for c in req["commands"]]}
            data = json.dumps(resp).encode()
            for i in range(0, len(data), 1000):  # fragmented, unframed like the firmware
                self.request.sendall(data[i:i + 1000])

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    tcp = socketserver.ThreadingTCPServer((a.host, 8002), H)
    threading.Thread(target=tcp.serve_forever, daemon=True).start()

    def udp():
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", 8001))
        while True:
            data, addr = s.recvfrom(64)
            if data == b"Zortrax":
                s.sendto(bytes([24]) + b"FAKE0001".ljust(32, b"\0"), addr)
    threading.Thread(target=udp, daemon=True).start()

    from pyftpdlib.authorizers import DummyAuthorizer
    from pyftpdlib.handlers import FTPHandler
    from pyftpdlib.servers import FTPServer
    auth = DummyAuthorizer()
    auth.add_user("zortrax", "zortrax", a.storage, perm="elradfmw")
    FTPHandler.authorizer = auth
    FTPHandler.passive_ports = range(60000, 60100)
    FTPServer((a.host, 8003), FTPHandler).serve_forever()


if __name__ == "__main__":
    main()
