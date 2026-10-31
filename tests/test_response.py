"""ECHONET Lite response matching regression tests (no hardware needed)."""
import ast
import logging
import time
import unittest
from pathlib import Path

# Load only the production method: importing the script opens UART and LEDs.
tree = ast.parse((Path(__file__).resolve().parents[1] / "GetSmartMeterData.py").read_text())
cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "CommEchoNet")
method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "SendEchonetCommand")
stub = ast.ClassDef(name="Target", bases=[], keywords=[], body=[method], decorator_list=[])
module = ast.fix_missing_locations(ast.Module(body=[stub], type_ignores=[]))
namespace = {"time": time, "logging": logging, "COMMAND_TIMEOUT": 0.02}
exec(compile(module, "<production-method>", "exec"), namespace)
Target = namespace["Target"]


class Serial:
    def __init__(self, responses):
        self.responses = responses

    def readline(self):
        return (self.responses.pop(0) if self.responses else "").encode()


class ResponseTests(unittest.TestCase):
    def run_case(self, responses, epc=b"\xe7", success=True):
        obj = Target()
        obj.LocalIPAddr = "fe80::1"
        obj._Target__ser = Serial(responses)
        sent = []
        obj.SendCommand = lambda cmd, raw: sent.append(raw) or success
        return obj.SendEchonetCommand(epc), sent

    def packet(self, epc="E7", tid=1, pdc=4, data="00000123",
               seoj="028801", deoj="05FF01", esv="72", opc="01", ehd="1081"):
        frame = f"{ehd}{tid:04X}{seoj}{deoj}{esv}{opc}{epc}{pdc:02X}{data}"
        return "ERXUDP " + " ".join(["x"] * 8) + " " + frame + "\r\n"

    def test_good(self):
        val, sent = self.run_case([self.packet()])
        self.assertEqual(val, 291)
        self.assertEqual(sent[0][2:4], b"\x00\x01")

    def test_wrong_epc_then_good(self):
        self.assertEqual(self.run_case([self.packet(epc="E0"), self.packet()])[0], 291)

    def test_old_tid(self):
        self.assertEqual(self.run_case([self.packet(tid=0)])[0], -1)

    def test_bad_sender(self):
        self.assertEqual(self.run_case([self.packet(seoj="000001")])[0], -1)

    def test_bad_receiver(self):
        self.assertEqual(self.run_case([self.packet(deoj="000001")])[0], -1)

    def test_bad_esv(self):
        self.assertEqual(self.run_case([self.packet(esv="52")])[0], -1)

    def test_bad_opc(self):
        self.assertEqual(self.run_case([self.packet(opc="02")])[0], -1)

    def test_bad_pdc(self):
        self.assertEqual(self.run_case([self.packet(pdc=5)])[0], -1)

    def test_zero_pdc(self):
        self.assertEqual(self.run_case([self.packet(pdc=0, data="")])[0], -1)

    def test_invalid_hex(self):
        self.assertEqual(self.run_case(["ERXUDP " + " ".join(["x"] * 8) + " zz"])[0], -1)

    def test_short(self):
        self.assertEqual(self.run_case([self.packet()[:25]])[0], -1)

    def test_trailing_bytes(self):
        self.assertEqual(self.run_case([self.packet().strip() + "00"])[0], -1)

    def test_wrong_ehd(self):
        self.assertEqual(self.run_case([self.packet(ehd="1082")])[0], -1)

    def test_send_failure(self):
        self.assertEqual(self.run_case([], success=False)[0], -1)

    def test_empty(self):
        self.assertEqual(self.run_case([])[0], -1)

    def test_tid_wrap(self):
        obj = Target()
        obj._echonet_tid = 65535
        obj.LocalIPAddr = "fe80::1"
        obj._Target__ser = Serial([])
        sent = []
        obj.SendCommand = lambda cmd, raw: sent.append(raw) or False
        self.assertEqual(obj.SendEchonetCommand(b"\xe7"), -1)
        self.assertEqual(sent[0][2:4], b"\x00\x00")

    def test_delayed_old_response(self):
        self.assertEqual(self.run_case([self.packet(epc="E0", tid=0), self.packet()])[0], 291)

    def test_wrong_length_header(self):
        self.assertEqual(self.run_case(["ERXUDP x"])[0], -1)

    def test_e1(self):
        self.assertEqual(self.run_case([self.packet(epc="E1", pdc=1, data="01")], epc=b"\xe1")[0], 1)


if __name__ == "__main__":
    unittest.main()
