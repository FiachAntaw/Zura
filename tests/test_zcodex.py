import json, os, struct, sys, unittest

def _read(name, mode="rb"):
    with open(os.path.join(os.path.dirname(__file__), "fixtures", name), mode) as f:
        return f.read()

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, "..", "plugins", "ZortraxM"))
from zcodex import commands as C, container, config_crypto, writer
from zcodex.gcode import translate, Options

FIX = os.path.join(HERE, "fixtures")

class CommandTests(unittest.TestCase):
    def test_reencode_zsuite_commands_identically(self):
        _, _, entries = container.read(_read("zsuite-cube20.zcodex2"))
        zc = entries["ZCodeData"]
        rebuilt = b"".join(C.frame(op, args) for op, args in C.iter_commands(zc))
        self.assertEqual(rebuilt, zc)

    def test_known_encodings_match_zsuite(self):
        self.assertEqual(C.set_bed_temperature(80).hex(), "060e5000000016")
        self.assertEqual(C.print_move(C.MoveType.UNKNOWN, z=15000)[:-1].hex(), "0801ff04983a0000")

class CryptoTests(unittest.TestCase):
    def test_aes_matches_fips197_vector(self):
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        key, iv, msg = bytes(range(32)), bytes(16), bytes(range(100))
        ref = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        pad = 16 - len(msg) % 16
        self.assertEqual(config_crypto.aes_cbc_encrypt(key, iv, msg), ref.update(msg + bytes([pad]) * pad) + ref.finalize())

    def test_layout_and_decrypt_with_test_key(self):
        from cryptography.hazmat.primitives.asymmetric import rsa, padding as ap
        from cryptography.hazmat.primitives import hashes, padding
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pn = priv.public_key().public_numbers()
        blob = config_crypto.encrypt_configuration('{"TempBed":80}' * 50, key=(pn.n, pn.e))
        total, = struct.unpack_from("<i", blob, 0)
        self.assertEqual(total, len(blob) - 4)
        pos, parts = 4, []
        for _ in range(3):
            n, = struct.unpack_from("<i", blob, pos); parts.append(blob[pos + 4:pos + 4 + n]); pos += 4 + n
        oaep = ap.OAEP(mgf=ap.MGF1(hashes.SHA1()), algorithm=hashes.SHA1(), label=None)
        key, iv = priv.decrypt(parts[0], oaep), priv.decrypt(parts[1], oaep)
        d = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        u = padding.PKCS7(128).unpadder()
        plain = u.update(d.update(parts[2]) + d.finalize()) + u.finalize()
        self.assertEqual(plain.decode(), '{"TempBed":80}' * 50)

    def test_zsuite_sample_has_same_layout(self):
        _, _, entries = container.read(_read("zsuite-cube20.zcodex2"))
        blob = entries["ConfigurationData"]
        self.assertEqual(struct.unpack_from("<ii", blob, 0), (len(blob) - 4, 256))

class TranslatorTests(unittest.TestCase):
    def setUp(self):
        self.gcode = _read("cube20-cura514.gcode", "r").splitlines()

    def test_translate_cura_cube(self):
        r = translate(self.gcode, Options(raft=True))
        ops = [op for op, _ in C.iter_commands(r.data)]
        self.assertEqual(len(ops), r.command_count)
        self.assertEqual(ops[-1], C.Op.PRINT_END)
        self.assertIn(C.Op.LAYER, ops)
        self.assertEqual((r.nozzle_temperature, r.bed_temperature), (275, 80))
        self.assertAlmostEqual(r.filament_mm, 1997.07, delta=0.5)  # sum of extruding E moves
        self.assertEqual(r.min_layer, -6)

    def test_full_file_round_trip(self):
        data = writer.build(self.gcode, material="Z-ABS", layer_mm=0.2, raft=True)
        header, _, entries = container.read(data)
        self.assertEqual(set(entries), set(container.ENTRY_ORDER))
        self.assertEqual(header["PrinterModelEnumId"], 24)
        self.assertEqual(header["CommandCount"], sum(1 for _ in C.iter_commands(entries["ZCodeData"])))
        self.assertEqual(header["Materials"][0]["Temperature"], 275)

if __name__ == "__main__":
    unittest.main()
