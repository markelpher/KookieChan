"""Exercita sincronização e compensação contra repositórios Git locais."""
import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('mirror_refs_integration', pathlib.Path('.github/scripts/mirror_refs.py'))
mirror = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror)


class MirrorGitIntegrationTest(unittest.TestCase):
    def git(self, *args, cwd=None):
        return subprocess.run(['git', *map(str, args)], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()

    def test_real_git_reverts_first_remote_when_second_push_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            origin, first, second, work = (root / name for name in ('origin.git', 'first.git', 'second.git', 'work'))
            for repo in (origin, first, second):
                self.git('init', '--bare', repo)
            self.git('init', work)
            self.git('config', 'user.email', 'test@example.invalid', cwd=work)
            self.git('config', 'user.name', 'Test', cwd=work)
            self.git('checkout', '-b', 'feature', cwd=work)
            (work / 'file.txt').write_text('old', encoding='utf-8')
            self.git('add', 'file.txt', cwd=work)
            self.git('commit', '-m', 'old', cwd=work)
            old = self.git('rev-parse', 'HEAD', cwd=work)
            self.git('remote', 'add', 'origin', origin, cwd=work)
            for remote in ('origin', first, second):
                self.git('push', remote, 'HEAD:refs/heads/feature', cwd=work)
            (work / 'file.txt').write_text('new', encoding='utf-8')
            self.git('commit', '-am', 'new', cwd=work)
            new = self.git('rev-parse', 'HEAD', cwd=work)
            self.git('push', 'origin', 'HEAD:refs/heads/feature', cwd=work)
            original = mirror.git

            def fail_second_push(*args, **kwargs):
                if args[0] == 'push' and args[-2] == str(second):
                    raise RuntimeError('Falha simulada no segundo mirror')
                return original(*args, **kwargs)

            previous = os.getcwd()
            try:
                os.chdir(work)
                with patch.object(mirror, 'git', side_effect=fail_second_push):
                    with self.assertRaisesRegex(RuntimeError, 'revertidas'):
                        mirror.synchronize('sync', 'refs/heads/feature', new, [str(first), str(second)])
            finally:
                os.chdir(previous)
            self.assertEqual(self.git('--git-dir', first, 'rev-parse', 'refs/heads/feature'), old)
            self.assertEqual(self.git('--git-dir', second, 'rev-parse', 'refs/heads/feature'), old)
