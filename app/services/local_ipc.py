"""Bounded authenticated JSON over loopback. No unpickling, no secret payloads."""
import hashlib
import hmac
import json
import secrets
import socket
import time

MAX_FRAME = 65536
CONNECT_TIMEOUT = 3
AUTH_TIMEOUT = 3
RESPONSE_TIMEOUT = 35


class Connection:
    def __init__(self, sock, timeout=AUTH_TIMEOUT):
        self.sock = sock
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.sock.close()

    def send(self, value):
        data = json.dumps(value, ensure_ascii=True).encode("ascii")
        if len(data) > MAX_FRAME:
            raise ValueError("IPC frame too large")
        self.sock.settimeout(self.timeout)
        self.sock.sendall(len(data).to_bytes(4, "big") + data)

    def recv(self):
        deadline = time.monotonic() + self.timeout

        def exact(size):
            chunks = bytearray()
            while len(chunks) < size:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("IPC response timeout")
                self.sock.settimeout(remaining)
                data = self.sock.recv(size - len(chunks))
                if not data:
                    raise EOFError("IPC connection closed")
                chunks.extend(data)
            return bytes(chunks)

        size = int.from_bytes(exact(4), "big")
        if not 0 < size <= MAX_FRAME:
            raise ValueError("Invalid IPC frame size")
        try:
            return json.loads(exact(size))
        except (ValueError, UnicodeError, RecursionError):
            raise ValueError("Invalid IPC JSON") from None


def _digest(key, challenge):
    if not isinstance(challenge, str) or len(challenge) != 64:
        raise ValueError("Invalid IPC challenge")
    return hmac.new(key, challenge.encode("ascii"), hashlib.sha256).hexdigest()


def Client(address, *, authkey):
    sock = socket.create_connection(address, timeout=CONNECT_TIMEOUT)
    conn = Connection(sock)
    try:
        challenge = conn.recv()
        own_challenge = secrets.token_hex(32)
        conn.send({"proof": _digest(authkey, challenge), "challenge": own_challenge})
        answer = conn.recv()
        if not isinstance(answer, str) or not hmac.compare_digest(answer, _digest(authkey, own_challenge)):
            raise ConnectionError("IPC authentication failed")
        conn.timeout = RESPONSE_TIMEOUT
        return conn
    except BaseException:
        sock.close()
        raise


class Listener:
    def __init__(self, address, *, authkey):
        self.key = authkey
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            # Do not permit another listener to reuse this service address.
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            self.socket.bind(address)
            self.socket.listen(8)
        except BaseException:
            self.socket.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.socket.close()

    def accept(self):
        sock, _ = self.socket.accept()
        conn = Connection(sock)
        try:
            challenge = secrets.token_hex(32)
            conn.send(challenge)
            answer = conn.recv()
            if (not isinstance(answer, dict) or not isinstance(answer.get("proof"), str)
                    or not hmac.compare_digest(answer["proof"], _digest(self.key, challenge))):
                raise ConnectionError("IPC authentication failed")
            conn.send(_digest(self.key, answer.get("challenge")))
            return conn
        except BaseException:
            sock.close()
            raise
