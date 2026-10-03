import copy
import os
from pathlib import Path
import subprocess
import tarfile
import unittest
from unittest.mock import Mock, patch

from helpers import ROOT, TempHomeTestCase, make_package
from mfruitos.apps.manifest import load_manifest
from mfruitos.system.settings import Settings
from mfruitos.updater import catalog, rollback
from mfruitos.updater.installer import InstallError, Installer, InstallRequest
from mfruitos.updater.service import UpdateService
from mfruitos.updater.verifier import sha256_file


class CatalogTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.item = copy.deepcopy(catalog.entries()[0])
        self.source = Path(self.tmp) / 'source'
        self.source.mkdir()
        (self.source / 'app').mkdir()
        (self.source / 'app/main.py').write_text('print("app")\n', encoding='utf-8')

    def test_bundled_catalogue_pins_each_distinct_source(self):
        items = catalog.entries()
        self.assertTrue(items)
        self.assertEqual(len({item['id'] for item in items}), len(items))
        for item in items:
            with self.subTest(app=item['id']):
                self.assertRegex(item['sha256'], r'^[0-9a-f]{64}$')
                self.assertRegex(item['ref'], r'^[0-9a-f]{40}$')
                owner_repo = item['repository'].removeprefix('https://github.com/')
                self.assertEqual(item['url'],
                                 f"https://api.github.com/repos/{owner_repo}/tarball/{item['ref']}")
                if catalog.is_native(item):
                    self.assertRegex(item['version'], r'^\d+\.\d+\.\d+$')
                else:
                    self.assertTrue(item['dependencies'])
                self.assertEqual(catalog.get(item['id']), item)

    def test_radioconnect_replaces_messenger_and_walkietalkie(self):
        ids = [item['id'] for item in catalog.entries()]
        self.assertIn('radioconnect', ids)
        self.assertNotIn('whisplay-lora-messenger', ids)
        self.assertNotIn('whisplay-lora-walkie', ids)
        item = catalog.get('radioconnect')
        self.assertTrue(catalog.is_native(item))
        self.assertEqual(catalog.requirements(item), ['radio'])

    def test_a_native_package_is_installed_as_published(self):
        item = dict(id='weather', name='Weather', description='', native=True, version='2.1.0',
                    repository='https://github.com/example/weather')
        package = make_package(str(Path(self.tmp) / 'native'), app_id='weather', version='2.1.0',
                               install_sh='#!/bin/sh\necho own hook\n')
        before = {p.name: p.read_bytes() for p in Path(package).iterdir() if p.is_file()}
        catalog.prepare(package, item)
        after = {p.name: p.read_bytes() for p in Path(package).iterdir() if p.is_file()}
        self.assertEqual(after, before, 'nothing rewritten')
        for changes in ({'version': '2.0.0'}, {'id': 'other'}):
            with self.subTest(changes=changes):
                with self.assertRaises(catalog.CatalogError):
                    catalog.prepare(package, dict(item, **changes))

    def test_unknown_id_has_actionable_error(self):
        with self.assertRaisesRegex(ValueError, 'Unknown catalogue app'):
            catalog.get('missing-app')

    def test_preparation_replaces_system_scripts_and_embeds_current_sdk(self):
        old = '#!/bin/sh\nexit 99\n'
        for name in ('install.sh', 'update.sh', 'uninstall.sh', 'run.sh', 'test.sh'):
            (self.source / name).write_text(old, encoding='utf-8')
        sdk = self.source / 'mfruit_sdk'
        sdk.mkdir()
        (sdk / 'stale.py').write_text('stale = True\n', encoding='utf-8')
        (self.source / 'config.yaml').write_text('user: config\n', encoding='utf-8')
        with patch.object(rollback, 'safe_rmtree', wraps=rollback.safe_rmtree) as remove:
            catalog.prepare(str(self.source), self.item)
        remove.assert_called_once_with(str(sdk), str(self.source))
        manifest = load_manifest(str(self.source), os_version='1.4.0')
        self.assertEqual(manifest.id, self.item['id'])
        self.assertEqual(manifest.repository, self.item['repository'])
        self.assertEqual(manifest.entrypoint, 'run.sh')
        self.assertEqual(manifest.test, 'test.sh')
        self.assertEqual(manifest.raw['persist'], ['config.yaml', '.env', 'models'])
        self.assertEqual(manifest.exit_gesture, 'none')
        self.assertTrue(manifest.disable_esc_exit_key)
        self.assertFalse((self.source / 'update.sh').exists())
        self.assertFalse((self.source / 'uninstall.sh').exists())
        self.assertFalse((sdk / 'stale.py').exists())
        self.assertEqual((sdk / '__init__.py').read_bytes(),
                         (Path(ROOT) / 'mfruitos/sdk/__init__.py').read_bytes())
        self.assertFalse(list(sdk.rglob('*.pyc')))
        self.assertFalse(list(sdk.rglob('__pycache__')))
        self.assertEqual((self.source / 'config.yaml').read_text(), 'user: config\n')
        for name in ('install.sh', 'run.sh', 'test.sh'):
            body = (self.source / name).read_bytes()
            self.assertNotIn(b'\r', body)
            self.assertNotIn(b'exit 99', body)
            if os.name == 'posix':
                self.assertTrue(os.access(self.source / name, os.X_OK))

    def test_python_module_entry_is_supported(self):
        self.item['entry'] = '-m app.main'
        catalog.prepare(str(self.source), self.item)
        self.assertIn('exec .venv/bin/python -m app.main "$@"',
                      (self.source / 'run.sh').read_text())

    def test_python_package_entry_is_supported(self):
        (self.source / 'app/__main__.py').write_text('print("app")\n', encoding='utf-8')
        self.item['entry'] = '-m app'
        catalog.prepare(str(self.source), self.item)
        self.assertIn('exec .venv/bin/python -m app "$@"',
                      (self.source / 'run.sh').read_text())

    def test_missing_python_entry_rejected_before_changing_package(self):
        original = self.source / 'install.sh'
        original.write_text('keep the original\n', encoding='utf-8')
        for entry in ('missing.py', '-m app.missing'):
            with self.subTest(entry=entry):
                self.item['entry'] = entry
                with self.assertRaisesRegex(ValueError, 'entry is missing'):
                    catalog.prepare(str(self.source), self.item)
                self.assertEqual(original.read_text(), 'keep the original\n')
                self.assertFalse((self.source / 'manifest.json').exists())

    def test_unsafe_python_entry_rejected(self):
        for entry in ('../outside.py', '/outside.py', 'app/main.py; touch marker',
                      '-c "print(1)"', '-m app/main'):
            with self.subTest(entry=entry):
                self.item['entry'] = entry
                with self.assertRaisesRegex(ValueError, 'Invalid catalogue entry'):
                    catalog.prepare(str(self.source), self.item)

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX symlinks')
    def test_entry_symlink_cannot_escape_package(self):
        outside = Path(self.tmp) / 'outside.py'
        outside.write_text('print("outside")\n', encoding='utf-8')
        (self.source / 'main.py').symlink_to(outside)
        self.item['entry'] = 'main.py'
        with self.assertRaisesRegex(ValueError, 'outside the package'):
            catalog.prepare(str(self.source), self.item)
        self.assertEqual(outside.read_text(), 'print("outside")\n')

    @unittest.skipUnless(os.name == 'posix', 'requires POSIX shell and executable files')
    def test_generated_scripts_use_package_venv_and_preserve_arguments(self):
        catalog.prepare(str(self.source), self.item)
        bin_dir = Path(self.tmp) / 'bin'
        bin_dir.mkdir()
        python = bin_dir / 'python3'
        # Record commands instead of downloading dependencies or launching hardware.
        python.write_text('#!/bin/sh\nset -eu\n'
                          'printf "<%s>" "$@" >> "$COMMAND_LOG"\n'
                          'printf "\\n" >> "$COMMAND_LOG"\n'
                          'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then\n'
                          '  mkdir -p .venv/bin\n  cp "$0" .venv/bin/python\nfi\n',
                          encoding='utf-8')
        python.chmod(0o755)
        log = Path(self.tmp) / 'commands.log'
        env = dict(os.environ, PATH=str(bin_dir) + os.pathsep + os.environ['PATH'],
                   COMMAND_LOG=str(log))
        for name in ('install.sh', 'test.sh'):
            subprocess.run(['/bin/sh', str(self.source / name)], cwd=self.source,
                           env=env, check=True, capture_output=True)
        subprocess.run(['/bin/sh', str(self.source / 'run.sh'), 'hello world'],
                       cwd=self.tmp, env=env, check=True, capture_output=True)
        commands = log.read_text().splitlines()
        self.assertEqual(commands[0], '<-m><venv><--system-site-packages><.venv>')
        self.assertEqual(commands[1], '<-m><pip><install><--disable-pip-version-check>' +
                         ''.join(f'<{dep}>' for dep in self.item['dependencies']))
        self.assertIn('<-m><compileall><-q><.><-x><[/]\\.venv[/]>', commands)
        self.assertIn('<-c><import PIL, yaml, mfruit_sdk>', commands)
        self.assertEqual(commands[-1], '<app/main.py><hello world>')


class CatalogInstallerTests(TempHomeTestCase):
    def setUp(self):
        super().setUp()
        self.source = Path(make_package(os.path.join(self.tmp, 'source'),
                                       install_sh='#!/bin/sh\nexit 99\n'))
        (self.source / 'main.py').write_text('print("app")\n', encoding='utf-8')
        self.archive = Path(self.tmp) / 'package.tar.gz'
        with tarfile.open(self.archive, 'w:gz') as tar:
            tar.add(self.source, arcname='owner-source-commit')
        self.item = dict(id='weather', name='Weather', description='Fixture',
                         repository='https://github.com/example/weather',
                         entry='main.py', dependencies=['Pillow>=9', 'PyYAML>=6'],
                         ref='a' * 40, url='https://example.invalid/archive.tar.gz',
                         sha256=sha256_file(str(self.archive)))
        self.lookup = patch.object(catalog, 'entries', return_value=[self.item])
        self.lookup.start()
        self.addCleanup(self.lookup.stop)
        self.settings = Settings(None)
        self.installer = Installer(self.paths, '1.4.0', self.settings)

    def request(self, **changes):
        fields = dict(repository=self.item['repository'], local_path=str(self.archive),
                      expected_sha256=self.item['sha256'], app_id='weather', catalog_id='weather')
        fields.update(changes)
        return InstallRequest(**fields)

    def test_service_passes_exact_pinned_request(self):
        installer = Mock()
        service = UpdateService(self.paths, self.settings, None, installer, '1.4.0')
        progress = Mock()
        service.install_catalog('weather', progress)
        request, callback = installer.run.call_args.args
        self.assertEqual(request, InstallRequest(
            repository=self.item['repository'], version='1.0.0', ref=self.item['ref'],
            url=self.item['url'], expected_sha256=self.item['sha256'],
            app_id='weather', catalog_id='weather'))
        self.assertIs(callback, progress)

    def test_unknown_catalogue_id_is_install_error(self):
        with self.assertRaises(InstallError) as ctx:
            self.installer.run(self.request(catalog_id='unknown'))
        self.assertEqual(ctx.exception.step, 'verify')
        self.assertIn('Unknown catalogue app', ctx.exception.message)
        self.assertEqual(os.listdir(self.paths.apps_dir), [])

    def test_unverified_or_wrong_source_never_prepared(self):
        for changes in ({'expected_sha256': ''}, {'expected_sha256': '0' * 64},
                        {'repository': 'https://github.com/other/weather'}):
            with self.subTest(changes=changes), patch.object(catalog, 'prepare') as prepare:
                with self.assertRaises(InstallError) as ctx:
                    self.installer.run(self.request(**changes))
                self.assertEqual(ctx.exception.step, 'verify')
                prepare.assert_not_called()
                self.assertEqual(os.listdir(self.paths.apps_dir), [])

    def test_matching_request_digest_cannot_override_catalogue_pin(self):
        # Even a valid checksum supplied by the caller must match the catalogue.
        good_digest = self.item['sha256']
        self.item['sha256'] = '0' * 64
        with patch.object(catalog, 'prepare') as prepare:
            with self.assertRaisesRegex(InstallError, 'Catalogue source verification failed'):
                self.installer.run(self.request(expected_sha256=good_digest))
        prepare.assert_not_called()
        self.assertEqual(os.listdir(self.paths.apps_dir), [])

    def test_missing_catalogue_entry_cannot_activate_generated_wrapper(self):
        self.item['entry'] = 'missing.py'
        with patch('mfruitos.updater.installer._run_script') as run_script:
            with self.assertRaises(InstallError) as ctx:
                self.installer.run(self.request())
        self.assertEqual(ctx.exception.step, 'verify')
        self.assertIn('entry is missing', ctx.exception.message)
        run_script.assert_not_called()
        self.assertEqual(os.listdir(self.paths.apps_dir), [])

    @unittest.skipUnless(os.name == 'posix', 'installer activation requires POSIX symlinks')
    def test_verified_install_prepares_copy_and_registers_after_test(self):
        events = []

        def run_script(command, cwd, env, log_path, timeout):
            script = Path(command[-1])
            self.assertNotIn('exit 99', script.read_text())
            self.assertEqual(str(script.parent), cwd)
            events.append(script.name)

        self.installer.register = lambda manifest: events.append('register:' + manifest.id)
        with patch('mfruitos.updater.installer._run_script', side_effect=run_script):
            result = self.installer.run(self.request())
        self.assertTrue(result.verified)
        self.assertEqual(events, ['install.sh', 'test.sh', 'register:weather'])
        current = rollback.current_target(self.paths.app_root('weather'))
        self.assertEqual(load_manifest(current).id, 'weather')
        self.assertTrue((Path(current) / 'mfruit_sdk/__init__.py').is_file())
        self.assertEqual((self.source / 'install.sh').read_text(), '#!/bin/sh\nexit 99\n')

    @unittest.skipUnless(os.name == 'posix', 'installer activation requires POSIX symlinks')
    def test_catalogue_test_failure_keeps_previous_version_and_config(self):
        with patch('mfruitos.updater.installer._run_script'):
            self.installer.run(self.request())
        root = self.paths.app_root('weather')
        current = rollback.current_target(root)
        config = Path(current) / 'config.yaml'
        config.write_text('radio: user-choice\n', encoding='utf-8')
        record = self.installer.read_record(root)

        def run_script(command, cwd, env, log_path, timeout):
            if Path(command[-1]).name == 'test.sh':
                self.assertEqual((Path(cwd) / 'config.yaml').read_text(), 'radio: user-choice\n')
                raise InstallError('test', 'generated self-test failed')

        with patch('mfruitos.updater.installer._run_script', side_effect=run_script):
            with self.assertRaises(InstallError) as ctx:
                self.installer.run(self.request(mode='reinstall'))
        self.assertTrue(ctx.exception.rolled_back)
        self.assertEqual(rollback.current_target(root), current)
        self.assertEqual(config.read_text(), 'radio: user-choice\n')
        self.assertEqual(self.installer.read_record(root), record)
        self.assertEqual(len(os.listdir(os.path.join(root, 'versions'))), 1)


if __name__ == '__main__':
    unittest.main()
