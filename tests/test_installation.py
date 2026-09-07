import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('systemd-analyze'),
                     'Requires the actual Linux service parser')
class LinuxInstallationTests(unittest.TestCase):
    def test_generated_unit_accepts_a_private_home_with_spaces(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory) / 'private home'
            installed = subprocess.run([sys.executable, str(root / 'scripts/install-sdlc.py'),
                                        '--home', str(home), '--project', 'example/app',
                                        '--source', str(root), '--approver', 'human'],
                                       capture_output=True, text=True)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            unit = json.loads(installed.stdout)['service_definition']
            parsed = subprocess.run(['systemd-analyze', 'verify', unit], capture_output=True, text=True)
            self.assertEqual(parsed.returncode, 0, parsed.stderr)


if __name__ == '__main__':
    unittest.main()
