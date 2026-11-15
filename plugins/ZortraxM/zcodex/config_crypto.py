"""Encrypt the Z-Suite slicer Configuration JSON into a ConfigurationData entry.

Layout (all lengths int32 LE):
  total | len(keyCt) keyCt | len(ivCt) ivCt | len(dataCt) dataCt
keyCt / ivCt: RSA-OAEP (SHA-1) of a random AES-256 key / 128-bit IV using the
public key embedded in Z-Suite. dataCt: AES-256-CBC, PKCS7, of the UTF-8 JSON.

Pure Python on purpose: Cura's frozen builds only ship part of `cryptography`.
"""
import base64
import hashlib
import os
import struct

_MODULUS_B64 = (
    "qCwJL1EZ/XO+tfzIu1cPniwuq5SzejwxZrztAlAFqA587GiMqHKHZoijiNCnXsGsZQadVYIPrgqF125f4Rao74ib"
    "mO9b0mh68123HAnWS6R/WAPo+VYcakdswZ8tL8ks3JSC4OJ14egWretGhMREc+hhY3jPAqK7Hed60ExvNN/HGACg"
    "BJM9ItFIp2BwJSwpBDvqz05JMbCDOpi/gj7B/cPuhCKS92tl/2oDdn7AQ2aTDoWya9Az01P/2ZKjRDWU+usmv7T2"
    "NeqoHmogfBfuoL7rVerSD4QXokmKXYlb1m2/JNN3G4FRm1arRkRwiYrh/J/ugzMIXEifaTaUY0B34Q=="
)
_EXPONENT = 65537


def public_key():
    """(n, e) of the Z-Suite configuration key."""
    return int.from_bytes(base64.b64decode(_MODULUS_B64), "big"), _EXPONENT


# ---------------------------------------------------------------- RSA-OAEP (SHA-1)
def _mgf1(seed: bytes, length: int) -> bytes:
    out, counter = b"", 0
    while len(out) < length:
        out += hashlib.sha1(seed + struct.pack(">I", counter)).digest()
        counter += 1
    return out[:length]


def rsa_oaep_encrypt(message: bytes, key=None) -> bytes:
    n, e = key or public_key()
    k = (n.bit_length() + 7) // 8
    h_len = 20
    if len(message) > k - 2 * h_len - 2:
        raise ValueError("message too long for RSA-OAEP")
    l_hash = hashlib.sha1(b"").digest()
    db = l_hash + b"\x00" * (k - len(message) - 2 * h_len - 2) + b"\x01" + message
    seed = os.urandom(h_len)
    masked_db = bytes(a ^ b for a, b in zip(db, _mgf1(seed, k - h_len - 1)))
    masked_seed = bytes(a ^ b for a, b in zip(seed, _mgf1(masked_db, h_len)))
    em = b"\x00" + masked_seed + masked_db
    return pow(int.from_bytes(em, "big"), e, n).to_bytes(k, "big")


# ---------------------------------------------------------------- AES-256-CBC
def _xtime(a: int) -> int:
    return ((a << 1) ^ 0x1B) & 0xFF if a & 0x80 else a << 1


def _gmul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


def _build_sbox():
    sbox = [0] * 256
    for x in range(256):
        inv = 0
        if x:
            for y in range(1, 256):
                if _gmul(x, y) == 1:
                    inv = y
                    break
        s = inv
        for i in range(1, 5):
            s ^= ((inv << i) | (inv >> (8 - i))) & 0xFF
        sbox[x] = s ^ 0x63
    return sbox


_SBOX = _build_sbox()


def _expand_key(key: bytes):
    nk, nr = len(key) // 4, len(key) // 4 + 6
    w = [list(key[4 * i:4 * i + 4]) for i in range(nk)]
    rcon = 1
    for i in range(nk, 4 * (nr + 1)):
        t = list(w[i - 1])
        if i % nk == 0:
            t = t[1:] + t[:1]
            t = [_SBOX[b] for b in t]
            t[0] ^= rcon
            rcon = _xtime(rcon)
        elif nk > 6 and i % nk == 4:
            t = [_SBOX[b] for b in t]
        w.append([a ^ b for a, b in zip(w[i - nk], t)])
    return [sum(w[4 * r:4 * r + 4], []) for r in range(nr + 1)]


def _encrypt_block(block, round_keys):
    s = [b ^ k for b, k in zip(block, round_keys[0])]
    nr = len(round_keys) - 1
    for rnd in range(1, nr + 1):
        s = [_SBOX[b] for b in s]
        # ShiftRows; state is column-major (index = 4*col + row)
        s = [s[4 * ((i // 4 + i % 4) % 4) + i % 4] for i in range(16)]
        if rnd != nr:
            out = []
            for c in range(4):
                a = s[4 * c:4 * c + 4]
                t = a[0] ^ a[1] ^ a[2] ^ a[3]
                out += [a[i] ^ t ^ _xtime(a[i] ^ a[(i + 1) % 4]) for i in range(4)]
            s = out
        s = [b ^ k for b, k in zip(s, round_keys[rnd])]
    return s


def aes_cbc_encrypt(key: bytes, iv: bytes, plaintext: bytes) -> bytes:
    pad = 16 - len(plaintext) % 16
    data = plaintext + bytes([pad]) * pad
    rk = _expand_key(key)
    prev, out = list(iv), bytearray()
    for i in range(0, len(data), 16):
        prev = _encrypt_block([a ^ b for a, b in zip(data[i:i + 16], prev)], rk)
        out += bytes(prev)
    return bytes(out)


# ---------------------------------------------------------------- entry point
def encrypt_configuration(config_json: str, key=None) -> bytes:
    aes_key, iv = os.urandom(32), os.urandom(16)
    data_ct = aes_cbc_encrypt(aes_key, iv, config_json.encode("utf-8"))
    key_ct, iv_ct = rsa_oaep_encrypt(aes_key, key), rsa_oaep_encrypt(iv, key)
    inner = b"".join(struct.pack("<i", len(x)) + x for x in (key_ct, iv_ct, data_ct))
    return struct.pack("<i", len(inner)) + inner
