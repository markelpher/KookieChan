import importlib.util
import pathlib
import subprocess
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location('mirror_refs', pathlib.Path('.github/scripts/mirror_refs.py'))
mirror_refs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mirror_refs)


class MirrorRefsTest(unittest.TestCase):
    def setUp(self):
        self.refs = {'origin': 'new', 'one': 'old', 'two': 'old'}
        self.backups = {}
        self.fail_remote = 'two'

    def fake_git(self, *args, check=True):
        if args[0] == 'check-ref-format':
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'rev-parse':
            ref = args[-1]
            return subprocess.CompletedProcess(args, 0, self.backups.get(ref, 'new') + '\n', '')
        if args[0] == 'ls-remote':
            remote = args[-2]
            oid = self.refs[remote]
            return subprocess.CompletedProcess(args, 0 if oid else 2, f'{oid}\tref\n' if oid else '', '')
        if args[0] == 'fetch':
            remote, mapping = args[-2:]
            self.backups[mapping.split(':', 1)[1]] = self.refs[remote]
            return subprocess.CompletedProcess(args, 0, '', '')
        if args[0] == 'push':
            remote, mapping = args[-2:]
            source = mapping.split(':', 1)[0]
            if remote == self.fail_remote:
                raise RuntimeError('rede indisponível')
            self.refs[remote] = None if not source else ('new' if source == 'source' else source)
            return subprocess.CompletedProcess(args, 0, '', '')
        raise AssertionError(args)

    def test_reverts_first_mirror_if_second_fails(self):
        with patch.object(mirror_refs, 'git', side_effect=self.fake_git):
            with self.assertRaisesRegex(RuntimeError, 'Alterações anteriores revertidas'):
                mirror_refs.synchronize('sync', 'refs/heads/test', 'source', ['one', 'two'])
        self.assertEqual(self.refs['one'], 'old')
        self.assertEqual(self.refs['two'], 'old')

    def test_restores_deleted_ref_on_failure(self):
        self.refs['origin'] = None
        with patch.object(mirror_refs, 'git', side_effect=self.fake_git):
            with self.assertRaisesRegex(RuntimeError, 'Alterações anteriores revertidas'):
                mirror_refs.synchronize('delete', 'refs/heads/test', '', ['one', 'two'])
        self.assertEqual(self.refs['one'], 'old')

    def test_protects_main_deletion(self):
        with patch.object(mirror_refs, 'git', side_effect=self.fake_git):
            with self.assertRaises(ValueError):
                mirror_refs.synchronize('delete', 'refs/heads/main', '', ['one', 'two'])
