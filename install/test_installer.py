import argparse
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from install import installer


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.package.mkdir()
        for name in ("bootloader.bin", "partitions.bin", "receiver.bin"):
            (self.package / name).write_bytes(b"image")

    def tearDown(self):
        self.temp.cleanup()

    def run_installer(self, board, existing=False, flash_size=None):
        header = bytearray(0x8100)
        partitions = (self.package / "partitions.bin").read_bytes()
        header[:len(partitions)] = partitions
        if existing:
            start = 0x8000
            header[start] = 0xE9
            header[start + 32:start + 36] = bytes.fromhex("3254cdab")
            app_name = b"lilygo_adsb"
            header[start + 80:start + 80 + len(app_name)] = app_name
        calls = []

        def fake_run(command, **kwargs):
            command = [str(word) for word in command]
            calls.append(command)
            operation = command.index("flash_id") if "flash_id" in command else None
            if operation is not None:
                return type("Result", (), {"stdout": "Detected flash size: " +
                                           (flash_size or "8MB") + "\n", "stderr": ""})()
            if "read_flash" in command:
                Path(command[-1]).write_bytes(header if command[-2] == "0x8100" else b"backup")
            return type("Result", (), {"stdout": "", "stderr": ""})()

        with patch.object(installer, "HERE", self.package), \
                patch.object(installer.subprocess, "run", side_effect=fake_run), \
                patch.object(Path, "cwd", return_value=self.root):
            installer.run(argparse.Namespace(port="test-port"), board)
        return calls

    def test_tbeam_first_install_backs_up_full_flash_then_erases_captures(self):
        calls = self.run_installer("tbeam-supreme")
        rendered = [" ".join(call) for call in calls]
        self.assertIn("read_flash 0 0x800000", "\n".join(rendered))
        self.assertIn("verify_flash 0", "\n".join(rendered))
        self.assertIn("erase_region 0x100000 0xf0000", "\n".join(rendered))
        self.assertTrue(any("write_flash" in call for call in rendered))
        self.assertFalse(any("--erase-all" in call for call in rendered))

    def test_tbeam_rejects_wrong_flash_size_before_read_or_write(self):
        with self.assertRaisesRegex(SystemExit, "requires 8MB flash"):
            self.run_installer("tbeam-supreme", flash_size="4MB")

    def test_t3s3_first_install_keeps_four_megabyte_behavior(self):
        calls = self.run_installer("t3s3")
        rendered = [" ".join(call) for call in calls]
        self.assertIn("read_flash 0 0x400000", "\n".join(rendered))
        self.assertIn("erase_region 0x100000 0xf0000", "\n".join(rendered))
        self.assertFalse(any("flash_id" in call for call in rendered))
        self.assertTrue(any("--flash_size 4MB" in call for call in rendered))

    def test_existing_receiver_update_does_not_back_up_or_erase_captures(self):
        calls = self.run_installer("tbeam-supreme", existing=True)
        rendered = [" ".join(call) for call in calls]
        self.assertFalse(any("read_flash 0 0x800000" in call for call in rendered))
        self.assertFalse(any("verify_flash" in call for call in rendered))
        self.assertFalse(any("erase_region" in call for call in rendered))
        self.assertTrue(any("write_flash" in call for call in rendered))


if __name__ == "__main__":
    unittest.main()
