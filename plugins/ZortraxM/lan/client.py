"""Zortrax LAN client, ported from the zsuite-mcp printer client (Z-Suite 3.7.0 protocol).

Requests have a uint16 big-endian byte count. Replies are unframed JSON.
No operation is retried: a lost reply must never duplicate a physical action.
"""
from __future__ import annotations

import base64
import binascii
import ftplib
import ipaddress
import json
import math
from pathlib import Path, PurePosixPath
import io
import socket
import struct
import time

STATUS_FIELDS = ('hotendTemperature', 'heatbedTemperature', 'printerStatus',
    'storageBytesFree', 'storageBytesTotal', 'currentMaterial', 'serialNumber',
    'failsafeReason', 'currentPrinterSystemTime', 'currentMaterialId', 'materialLeft',
    'currentSecondMaterialId', 'printingInProgress', 'failsafeAlertSource', 'failsafeAlertReason')
PRINT_STATUS_FIELDS = ('progress', 'metadata', 'userSettings', 'filename')
SETTINGS = ('lights', 'buzzer', 'sleep', 'nozzleDiameter')
CONTROL_ACTIONS = ('pause', 'resume', 'abort', 'restart', 'wakeUp')
COMMANDS = CONTROL_ACTIONS + ('status', 'printStatus', 'version', 'getCameraPreview',
    'pauseStatus', 'smoothingStatus', 'isStreaming', 'printFromStorage',
    'updateFromStorage', 'setSetting', 'getSetting')
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class PrinterError(RuntimeError):
    """Transport, malformed response, or explicit printer rejection."""


def remote_path(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError('Remote path must be a nonempty string without control characters')
    if '\\' in value or '..' in PurePosixPath(value).parts:
        raise ValueError('Remote paths must use forward slashes and cannot contain ..')
    return '/' + value.lstrip('/')


def _status_code(response):
    try:
        return int(response.get('status'))
    except (TypeError, ValueError):
        raise PrinterError('Printer response has no valid status code') from None


class PrinterClient:
    def __init__(self, host: str, port: int = 8002, ftp_port: int = 8003,
                 timeout: float = 10, ftp_username: str = 'zortrax',
                 ftp_password: str = 'zortrax', max_response_bytes: int = MAX_RESPONSE_BYTES):
        # Explicit literal IPs avoid DNS changing a selected physical target.
        self.host = str(ipaddress.ip_address(host))
        if not 1 <= port <= 65535 or not 1 <= ftp_port <= 65535:
            raise ValueError('Invalid port')
        if not math.isfinite(timeout) or timeout <= 0 or max_response_bytes <= 0:
            raise ValueError('Timeout and response bound must be positive')
        if any(c in ftp_username + ftp_password for c in '\r\n\0'):
            raise ValueError('FTP credentials cannot contain control characters')
        self.port, self.ftp_port, self.timeout = port, ftp_port, timeout
        self.ftp_username, self.ftp_password = ftp_username, ftp_password
        self.max_response_bytes = max_response_bytes

    def request(self, commands: list[dict], optional: tuple = ()) -> list[dict]:
        """Send a batch. Replies for command types in `optional` may carry status 2 (nothing to report)."""
        if not isinstance(commands, list) or not commands:
            raise ValueError('At least one command is required')
        if any(not isinstance(c, dict) or c.get('type') not in COMMANDS for c in commands):
            raise ValueError('Unknown printer command')
        body = json.dumps({'commands': commands}, separators=(',', ':'), allow_nan=False).encode('utf-8')
        if len(body) > 65535:
            raise ValueError('Command batch exceeds uint16 protocol length')
        deadline = time.monotonic() + self.timeout
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as connection:
                connection.sendall(struct.pack('!H', len(body)) + body)
                data = bytearray()
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise PrinterError('Printer response deadline exceeded; outcome may be unknown')
                    connection.settimeout(remaining)
                    chunk = connection.recv(min(65536, self.max_response_bytes - len(data) + 1))
                    if not chunk:
                        raise PrinterError('Printer closed connection before a complete JSON reply')
                    data.extend(chunk)
                    if len(data) > self.max_response_bytes:
                        raise PrinterError('Printer response exceeds configured byte bound')
                    try:
                        response = json.loads(data.decode('utf-8'))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    break
        except OSError as exc:
            raise PrinterError(f'Printer transport failed ({exc}); outcome may be unknown for commands that change state') from exc
        if not isinstance(response, dict) or not isinstance(response.get('responses'), list):
            raise PrinterError('Printer returned an invalid response envelope')
        responses = response['responses']
        if len(responses) != len(commands):
            raise PrinterError('Printer response count does not match command count')
        for command, item in zip(commands, responses):
            if not isinstance(item, dict) or item.get('type') != command['type']:
                raise PrinterError('Printer response command does not match request')
            if _status_code(item) != 1 and not (command['type'] in optional and _status_code(item) == 2):
                raise PrinterError(f"Printer rejected {command['type']}: {json.dumps(item)}")
        return responses

    def status(self):
        """[status, printStatus]. Like Z-Suite, ask for printStatus in its own request and only while a
        print is running; otherwise the second entry is an empty status-2 reply."""
        status = self.request([{'type': 'status', 'fields': list(STATUS_FIELDS)}])[0]
        info = fields(status)
        running = str(info.get('printerStatus', '')) in ('printing', 'printing_paused') or \
            str(info.get('printingInProgress', '0')) == '1'
        job = {'type': 'printStatus', 'status': '2'}
        if running:
            try:
                job = self.request([{'type': 'printStatus', 'fields': list(PRINT_STATUS_FIELDS)}],
                                   optional=('printStatus',))[0]
            except PrinterError:
                pass
        return [status, job]

    def full_info(self):
        return self.request([{'type': 'status', 'fields': list(STATUS_FIELDS)},
            {'type': 'version', 'fields': ['protocol', 'firmware', 'software', 'hardware']},
            {'type': 'getSetting', 'fields': list(SETTINGS)},
            {'type': 'printStatus', 'fields': ['progress', 'metadata', 'userSettings', 'filename']}],
            optional=('printStatus',))

    def camera(self, quality=50):
        if type(quality) is not int or not 1 <= quality <= 100:
            raise ValueError('Camera quality must be an integer from 1 to 100')
        response = self.request([{'type': 'getCameraPreview', 'quality': quality}])[0]
        encoded = response.get('cameraPreviewData')
        if not isinstance(encoded, str) or not encoded:
            raise PrinterError('Printer did not return a camera snapshot; it may require RTSP streaming')
        if encoded.startswith('data:'):
            encoded = encoded.partition(',')[2]
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PrinterError('Printer returned invalid camera base64') from exc
        if data.startswith(b'\xff\xd8\xff'):
            mime = 'image/jpeg'
        elif data.startswith(b'\x89PNG\r\n\x1a\n'):
            mime = 'image/png'
        else:
            raise PrinterError('Camera preview is not a recognized JPEG or PNG')
        return {'mimeType': mime, 'data': base64.b64encode(data).decode('ascii')}

    def control(self, action):
        if action not in CONTROL_ACTIONS:
            raise ValueError(f'Control must be one of {CONTROL_ACTIONS}')
        return self.request([{'type': action}])[0]

    def get_settings(self, fields=None):
        fields = list(SETTINGS if fields is None else fields)
        if not fields or any(f not in SETTINGS for f in fields):
            raise ValueError('Unknown printer setting')
        return self.request([{'type': 'getSetting', 'fields': fields}])[0]

    def set_setting(self, name, value):
        if name not in SETTINGS:
            raise ValueError('Unknown printer setting')
        if name == 'lights' and value not in ('off', 'white', 'dynamic'):
            raise ValueError('lights must be off, white, or dynamic (the Z-Suite UI values)')
        # Firmware defines allowed values. Preserve the GUI's JSON scalar behavior.
        if type(value) not in (str, bool, int, float) or (type(value) is float and not math.isfinite(value)):
            raise ValueError('Setting values must be finite JSON scalars')
        result = self.request([{'type': 'setSetting', 'settings': [{'name': name, 'value': value}]}])[0]
        if name == 'lights':
            # An outer status=1 can accompany an unapplied individual setting.
            # Read back the actual state; never retry the mutation blindly.
            actual = None
            for attempt in range(3):
                if attempt:
                    time.sleep(0.3)
                response = self.get_settings(['lights'])
                fields = response.get('fields', response.get('settings', []))
                actual = next((item.get('value') for item in fields if item.get('name') == 'lights'), None)
                if actual == value:
                    result['verified_value'] = actual
                    return result
            raise PrinterError(f'Printer did not confirm lights change: requested {value!r}, reported {actual!r}')
        return result

    def print_file(self, path, forced=False):
        if type(forced) is not bool:
            raise ValueError('forced must be boolean')
        # Z-Suite sends the bare file name (Path.GetFileName); with a leading '/' the firmware answers
        # startPrintAdditionalInfo 1 ("corrupted file") even for its own files.
        return self.request([{'type': 'printFromStorage', 'path': remote_path(path).lstrip('/'), 'forced': forced}])[0]

    def update_firmware(self, path):
        return self.request([{'type': 'updateFromStorage', 'path': remote_path(path)}])[0]

    def _ftp(self):
        ftp = ftplib.FTP(timeout=self.timeout)
        try:
            ftp.connect(self.host, self.ftp_port)
            ftp.login(self.ftp_username, self.ftp_password)
            return ftp
        except BaseException:
            ftp.close()
            raise

    def list_files(self, path='/'):
        path = remote_path(path)
        with self._ftp() as ftp:
            try:
                return [{'name': name, **facts} for name, facts in ftp.mlsd(path)]
            except ftplib.error_perm as exc:
                if not str(exc).startswith(('500', '502', '504')):
                    raise
                lines = []
                ftp.retrlines('LIST ' + path, lines.append)
                return [{'listing': line} for line in lines]

    def upload(self, local_path, path, overwrite=False):
        path = remote_path(path)
        source = Path(local_path).expanduser().resolve(strict=True)
        if not source.is_file():
            raise ValueError('Upload source must be a regular file')
        with self._ftp() as ftp:
            if not overwrite:
                parent, name = path.rsplit('/', 1)
                # Listing failure aborts rather than interpreting denial as absence.
                existing = ftp.nlst(parent or '/')
                if any(PurePosixPath(item.rstrip('/')).name == name for item in existing):
                    raise FileExistsError(path)
            with source.open('rb') as stream:
                result = ftp.storbinary('STOR ' + path, stream)
        return {'path': path, 'bytes': source.stat().st_size, 'response': result}

    def download(self, path, local_path, overwrite=False):
        path = remote_path(path)
        destination = Path(local_path).expanduser().absolute()
        # x mode atomically prevents accidental overwrite and follows no existing symlink.
        with destination.open('wb' if overwrite else 'xb') as stream:
            try:
                with self._ftp() as ftp:
                    response = ftp.retrbinary('RETR ' + path, stream.write)
            except BaseException:
                if not overwrite:
                    destination.unlink(missing_ok=True)
                raise
        return {'path': str(destination), 'bytes': destination.stat().st_size, 'response': response}

    def delete(self, path, directory=False):
        path = remote_path(path)
        if path == '/':
            raise ValueError('Cannot delete root')
        with self._ftp() as ftp:
            return ftp.rmd(path) if directory else ftp.delete(path)

    def mkdir(self, path):
        path = remote_path(path)
        with self._ftp() as ftp:
            return ftp.mkd(path)


def discover_printers(timeout: float = 3, broadcast: str = '255.255.255.255') -> list[dict]:
    """Read-only Zortrax UDP discovery; replies are hardware byte + serial bytes."""
    address = ipaddress.ip_address(broadcast)
    if address.version != 4 or not math.isfinite(timeout) or not 0 < timeout <= 30:
        raise ValueError('Discovery requires an IPv4 broadcast and timeout in (0, 30] seconds')
    results = {}
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as connection:
        connection.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        connection.sendto(b'Zortrax', (str(address), 8001))
        # Bound incoming datagrams even on a noisy/malicious local network.
        for _ in range(1024):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            connection.settimeout(remaining)
            try:
                data, sender = connection.recvfrom(2048)
            except socket.timeout:
                break
            if len(data) != 33:
                continue
            serial = data[1:].split(b'\0', 1)[0].decode('ascii', errors='replace')
            results[(sender[0], serial)] = {'host': sender[0], 'hardware': data[0], 'serialNumber': serial}
    return list(results.values())


def fields(response: dict) -> dict:
    """Flatten a response's [{name, value}] list into a dict."""
    items = response.get("fields", response.get("settings", [])) or []
    return {i.get("name"): i.get("value") for i in items if isinstance(i, dict)}


def upload_bytes(client: "PrinterClient", data: bytes, path: str, callback=None) -> dict:
    """Upload in-memory bytes (refuses to overwrite), calling callback(sent, total)."""
    path = remote_path(path)
    total, sent = len(data), [0]
    def progress(block):
        sent[0] += len(block)
        if callback:
            callback(sent[0], total)
    with client._ftp() as ftp:
        parent, name = path.rsplit("/", 1)
        existing = ftp.nlst(parent or "/")
        if any(PurePosixPath(item.rstrip("/")).name == name for item in existing):
            raise FileExistsError(path)
        result = ftp.storbinary("STOR " + path, io.BytesIO(data), blocksize=32768, callback=progress)
    return {"path": path, "bytes": total, "response": result}


START_PRINT_INFO = {1: "corrupted file", 2: "wrong device", 4: "firmware too old", 8: "Z endstop not calibrated",
                    256: "nozzle mismatch", 512: "material mismatch", 1024: "support material mismatch",
                    8192: "not enough model material", 16384: "not enough support material"}


def describe_start_info(mask) -> str:
    try:
        mask = int(mask)
    except (TypeError, ValueError):
        return ""
    return ", ".join(text for bit, text in START_PRINT_INFO.items() if mask & bit)
