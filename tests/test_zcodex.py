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
        # Cura's raft layers here are -6..-3 (it skips -2 and -1); the printer needs consecutive numbers.
        layers = [struct.unpack("<i", a[:4])[0] for op, a in C.iter_commands(r.data) if op == C.Op.LAYER]
        self.assertEqual(layers, list(range(layers[0], layers[0] + len(layers))))
        self.assertEqual(r.min_layer, -4)

    def test_full_file_round_trip(self):
        data = writer.build(self.gcode, material="Z-ABS", layer_mm=0.2, raft=True)
        header, _, entries = container.read(data)
        self.assertEqual(set(entries), set(container.ENTRY_ORDER))
        self.assertEqual(header["PrinterModelEnumId"], 24)
        self.assertEqual(header["CommandCount"], sum(1 for _ in C.iter_commands(entries["ZCodeData"])))
        self.assertEqual(header["Materials"][0]["Temperature"], 275)

class PauseTests(unittest.TestCase):
    def test_pause_at_height(self):
        """Cura's PauseAtHeight block becomes one Zortrax Pause after the next Layer; its park moves are dropped."""
        g = ["M83", "G92 E0", ";LAYER_COUNT:3", ";LAYER:0", "G0 X10 Y10 Z0.2", "G1 X20 E1",
             ";TYPE:CUSTOM---------------; Pause at end of Preview Layer 2 (end of Gcode LAYER:1)",
             "G1 F300 Z5", "G1 X190 Y190", "M0 Click to resume", "G1 X20 Y10", "G1 Z0.2",
             ";--------------------------; End of the Pause code", ";TIME_ELAPSED:12.5",
             "G0 Z0.4", ";LAYER:1", "G1 X10 E1"]
        r = translate(g, Options())
        cmds = list(C.iter_commands(r.data))
        ops = [op for op, _ in cmds]
        i = ops.index(C.Op.PAUSE)
        self.assertEqual(ops[i - 1], C.Op.LAYER)
        self.assertEqual(struct.unpack("<ii", cmds[i][1]), (1, 400))
        self.assertEqual(ops.count(C.Op.PAUSE), 1)
        self.assertNotIn(190000, [v for op, a in cmds if op in (C.Op.PRINT_MOVE, C.Op.PRINT_JUMP)
                                  for v in C.decode_axes(a[1:]).values()])
        self.assertEqual(r.pauses, [{"Time": 12, "Material": None, "LayerNumber": 1}])




class ClassicZCodeTests(unittest.TestCase):
    """Original M200 .zcode (Z-Suite 2.32 classic)."""

    def test_compiler_matches_zsuite_232(self):
        # zsuite232-classic-cube20.zcode was written by Z-Suite 2.32's own BinaryZCodeFile from the same text.
        from zcodex import classic
        lines = _read("zsuite232-classic-cube20.gcode", "r").splitlines()
        self.assertEqual(classic.build(lines, classic.Header()), _read("zsuite232-classic-cube20.zcode"))

    def test_cura_slice_translates(self):
        from zcodex import classic, classic_gcode
        lines = _read("cura514-e2e-m200-cube20.gcode", "r").splitlines()
        data = classic_gcode.build(lines, material="Z-PLA Pro", layer_id="19", quality="High")
        fields, cmds = classic.read(data)
        n = fields["command_count"]
        self.assertEqual((fields["printing_profile"], fields["layer_thickness"], fields["quality"]), (11, 19, 1))
        self.assertEqual(fields["min_fw"], (1, 1, 1))
        self.assertEqual(fields["raft_layers"], 6)  # Z-PLA Pro: base + 3 interface + 3 surface, less the base
        self.assertEqual(fields["print_time"], int(lines[1].split(":")[1]))
        self.assertTrue(all(op == C.Op.CUSTOM_DATA for op, _ in cmds[n:]))
        body = cmds[:n]
        self.assertEqual(body[0], (C.Op.REPORT_PROGRESS, b"\x00"))
        self.assertEqual(body[-1], (C.Op.REPORT_PROGRESS, b"\x64"))
        layers = [struct.unpack("<i", a)[0] for op, a in body if op == C.Op.LAYER]
        self.assertEqual(layers, list(range(-7, len(layers) - 7)))
        progress = [a[0] for op, a in body if op == C.Op.REPORT_PROGRESS]
        self.assertEqual(progress, sorted(progress))
        moves = [C.decode_axes(a[1:]) for op, a in body if op == C.Op.PRINT_MOVE]
        self.assertLess(max(abs(m.get("E", 0)) for m in moves), 960 * 1000)  # E is reset every layer
        self.assertTrue(all(("Z" in m) == ("Z2" in m) for m in moves))
        temps = [a for op, a in body if op == C.Op.SET_EXTRUDER_TEMPERATURE]
        self.assertEqual(struct.unpack("<Bi", temps[0]), (0, 207))

    def test_fan_commands_move_15_moves_later(self):
        from zcodex.classic_gcode import move_fan_commands
        fan = C.print_move(255, fan2=255)
        moves = [C.print_move(252, x=i) for i in range(20)]
        out = move_fan_commands([fan] + moves)
        self.assertEqual(out.index(fan), 15)


if __name__ == "__main__":
    unittest.main()
