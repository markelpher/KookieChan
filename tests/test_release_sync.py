import importlib.util
import pathlib
import io
import sys
import unittest
from unittest.mock import patch
from urllib.error import HTTPError


spec = importlib.util.spec_from_file_location('sync_releases', pathlib.Path('.github/scripts/sync_releases.py'))
sync = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sync
spec.loader.exec_module(sync)


class FakeMirror:
    def __init__(self, kind, release):
        self.kind = kind
        self.item = {'version': 'before'}
        self.rolled_back = False
        self.assets = False

    def snapshot(self):
        return self.item.copy() if self.item else None

    def signature(self, item):
        return item

    def has_assets(self, item):
        return self.assets

    def rollback(self, before, after):
        if self.snapshot() != after:
            raise RuntimeError('alteração concorrente')
        self.item = before
        self.rolled_back = True


class ReleaseTransactionTest(unittest.TestCase):
    def setUp(self):
        self.release = sync.Release('v1', 'v1', 'notes', False, False, 'https://example.org/v1')
        self.gitlab = FakeMirror('gitlab', self.release)
        self.codeberg = FakeMirror('codeberg', self.release)

    def mirrors(self, kind, release):
        return self.gitlab if kind == 'gitlab' else self.codeberg

    def test_rolls_back_first_mirror_after_second_fails(self):
        def update(*args):
            self.gitlab.item = {'version': 'after'}
        with patch.object(sync, 'ReleaseMirror', side_effect=self.mirrors), \
             patch.object(sync, 'sync_gitlab', side_effect=update), \
             patch.object(sync, 'sync_codeberg', side_effect=RuntimeError('falha')):
            with self.assertRaisesRegex(RuntimeError, 'alterações anteriores revertidas'):
                sync.sync_transaction('published', self.release)
        self.assertTrue(self.gitlab.rolled_back)
        self.assertEqual(self.gitlab.item, {'version': 'before'})

    def test_reports_unknown_if_failing_step_changed(self):
        def update(*args):
            self.gitlab.item = {'version': 'after'}
        def fail_after_change(*args):
            self.codeberg.item = {'version': 'unknown'}
            raise RuntimeError('timeout')
        with patch.object(sync, 'ReleaseMirror', side_effect=self.mirrors), \
             patch.object(sync, 'sync_gitlab', side_effect=update), \
             patch.object(sync, 'sync_codeberg', side_effect=fail_after_change):
            with self.assertRaisesRegex(RuntimeError, 'REVERSÃO INCOMPLETA'):
                sync.sync_transaction('published', self.release)
        self.assertTrue(self.gitlab.rolled_back)

    def test_delete_with_assets_is_blocked_before_any_changes(self):
        self.codeberg.assets = True
        with patch.object(sync, 'ReleaseMirror', side_effect=self.mirrors), \
             patch.object(sync, 'sync_gitlab') as gitlab:
            with self.assertRaisesRegex(RuntimeError, 'anexos'):
                sync.sync_transaction('deleted', self.release)
            gitlab.assert_not_called()

    def test_does_not_overwrite_concurrent_modification(self):
        def update(*args):
            self.gitlab.item = {'version': 'after'}
        def fail_and_modify(*args):
            self.gitlab.item = {'version': 'other-user'}
            raise RuntimeError('falha')
        with patch.object(sync, 'ReleaseMirror', side_effect=self.mirrors), \
             patch.object(sync, 'sync_gitlab', side_effect=update), \
             patch.object(sync, 'sync_codeberg', side_effect=fail_and_modify):
            with self.assertRaisesRegex(RuntimeError, 'REVERSÃO INCOMPLETA'):
                sync.sync_transaction('published', self.release)
        self.assertEqual(self.gitlab.item, {'version': 'other-user'})

    def test_api_failure_does_not_expose_response_or_url(self):
        error = HTTPError('https://example.org/?token=secret', 403, 'forbidden', {},
                          io.BytesIO(b'{"token":"secret"}'))
        with patch.object(sync, 'urlopen', side_effect=error):
            with self.assertRaises(RuntimeError) as raised:
                sync.request_json('GET', 'https://example.org/?token=secret', {})
        self.assertIn('403', str(raised.exception))
        self.assertNotIn('secret', str(raised.exception))


class ReleaseMirrorRollbackTest(unittest.TestCase):
    def setUp(self):
        self.release = sync.Release('v1', 'v1', 'notes', False, False, 'https://example.org/v1')

    @patch.dict('os.environ', {'GITLAB_PROJECT_ID': '1', 'GITLAB_ACCESS_TOKEN': 'test'})
    def test_gitlab_restores_previous_metadata(self):
        mirror = sync.ReleaseMirror('gitlab', self.release)
        before = {'name': 'old', 'description': 'old body', 'assets': {'links': []}}
        after = {'name': 'new', 'description': 'new body', 'assets': {'links': []}}
        with patch.object(mirror, 'snapshot', return_value=after), patch.object(sync, 'request_json') as request:
            mirror.rollback(before, after)
        self.assertEqual(request.call_args.args[0], 'PUT')
        self.assertEqual(request.call_args.args[3], {'name': 'old', 'description': 'old body'})

    @patch.dict('os.environ', {'GITLAB_PROJECT_ID': '1', 'GITLAB_ACCESS_TOKEN': 'test'})
    def test_does_not_recreate_release_if_tag_was_deleted(self):
        mirror = sync.ReleaseMirror('gitlab', self.release)
        before = {'name': 'v1', 'description': 'notes', 'assets': {'links': []}, 'commit': {'id': 'abc'}}
        with patch.object(mirror, 'snapshot', return_value=None), \
             patch.object(sync, 'request_json', return_value=None) as request:
            with self.assertRaisesRegex(RuntimeError, 'tag ausente'):
                mirror.rollback(before, None)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.args[0], 'GET')

    @patch.dict('os.environ', {'CODEBERG_TOKEN': 'test', 'MIRROR_CODEBERG_OWNER_REPO': 'a/b'})
    def test_new_codeberg_release_with_assets_is_not_deleted(self):
        mirror = sync.ReleaseMirror('codeberg', self.release)
        after = {'id': 10, 'name': 'v1', 'body': 'notes', 'assets': [{'id': 2}]}
        with patch.object(mirror, 'snapshot', return_value=after), patch.object(sync, 'request_json') as request:
            with self.assertRaisesRegex(RuntimeError, 'anexos'):
                mirror.rollback(None, after)
        request.assert_not_called()
