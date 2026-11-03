import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'deploy' / 'rootless-deploy.sh'
REVISION = 'a' * 40


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.root = self.home / 'server' / 'ipchan'
        for suffix in ['shared/data', 'releases/' + REVISION + '/app', 'incoming']:
            (self.root / suffix).mkdir(parents=True)
        (self.root / 'shared/.env').write_text('DISCORD_TOKEN=test\n')
        (self.root / 'shared/data/state.json').write_text('{"preserved":true}')
        self.unit = self.home / '.config/containers/systemd/pcugame-ipchan.container'
        self.unit.parent.mkdir(parents=True)
        self.old_unit = '[Container]\nImage=localhost/pcugame-ipchan:previous\n'
        self.unit.write_text(self.old_unit)
        self.bin = self.home / 'bin'
        self.bin.mkdir()
        self.stub('id', 'case "$1" in -un) echo gh-deploy;; -u|-g) echo 1001;; esac')
        self.stub('nproc', 'echo 22')
        self.stub('git', 'printf "%s\\trefs/heads/master\\n" "${TEST_LATEST:-' + REVISION + '}"')
        self.stub('systemd-run', 'printf "%s\\n" "$*" >> "$HOME/build-command"')
        self.stub('systemctl', 'printf "%s\\n" "$*" >> "$HOME/systemctl-commands"')
        self.stub('podman', 'exit 0')
        self.stub('journalctl', 'if [ "${TEST_UNHEALTHY:-}" != 1 ]; then echo "봇 준비 완료"; fi')
        self.stub('sleep', 'exit 0')

    def stub(self, name, body):
        p = self.bin / name
        p.write_text('#!/usr/bin/env bash\nset -eu\n' + body + '\n')
        p.chmod(0o755)

    def run_deploy(self, **extra):
        env = dict(os.environ, HOME=str(self.home), PATH=str(self.bin) + ':' + os.environ['PATH'], **extra)
        return subprocess.run(['bash', str(SCRIPT), REVISION], env=env, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)

    def test_deploy_binds_exact_commit_and_caps_build(self):
        result = self.run_deploy()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Image=localhost/pcugame-ipchan:' + REVISION, self.unit.read_text())
        self.assertEqual((self.root / 'deployed-revision').read_text().strip(), REVISION)
        command = (self.home / 'build-command').read_text()
        for required in ['CPUQuota=1980%', 'CPUWeight=10', 'IOWeight=10', '--jobs 19', '--cpu-quota 1980000']:
            self.assertIn(required, command)
        self.assertEqual((self.root / 'shared/data/state.json').read_text(), '{"preserved":true}')

    def test_failed_health_check_restores_previous_unit(self):
        result = self.run_deploy(TEST_UNHEALTHY='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.unit.read_text(), self.old_unit)
        self.assertFalse((self.root / 'deployed-revision').exists())
        self.assertIn('start pcugame-ipchan.service', (self.home / 'systemctl-commands').read_text())

    def test_superseded_commit_is_not_activated(self):
        result = self.run_deploy(TEST_LATEST='b' * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.unit.read_text(), self.old_unit)
        self.assertFalse((self.home / 'build-command').exists())
