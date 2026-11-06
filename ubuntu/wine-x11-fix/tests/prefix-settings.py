#!/usr/bin/env python3
"""Validate packaged DPI migration and real Chinese glyphs without an account."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--files', type=Path, required=True)
parser.add_argument('--qa', type=Path, required=True)
args = parser.parse_args()
files, qa = args.files.resolve(strict=True), args.qa.resolve()
qa.mkdir(parents=True, exist_ok=False)
(qa / '.wecom-frame-qa').touch()
(qa / 'wine').symlink_to(files / 'wine')
# The desktop helper must not bootstrap another Wine prefix before the packaged launcher.
(qa / 'prefix').symlink_to(files / 'template')
sys.path.insert(0, str(Path(__file__).with_name('frame-composition')))
from isolated import desktop
from screencast import recording

probe = qa / 'ui-environment.exe'
probe32 = qa / 'ui-environment32.exe'
for compiler, binary in (('x86_64-w64-mingw32-gcc', probe), ('i686-w64-mingw32-gcc', probe32)):
    subprocess.run([compiler, '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-missing-field-initializers',
                    str(Path(__file__).with_name('ui-environment.c')), '-o', str(binary),
                    '-luser32', '-lgdi32', '-lcomdlg32', '-lshell32'], check=True)
prefix = qa / 'data/wecom/prefix'
report = {'account_used': False, 'real_desktop_used': False, 'cases': []}
report['desktop_locale'] = {key: os.environ.get(key) for key in ('LANG', 'LC_CTYPE', 'LC_ALL')}
original = {name: hashlib.sha256((files / 'template' / name).read_bytes()).hexdigest()
            for name in ('user.reg', 'system.reg')}
hidden = [str(path) for path in (Path('/usr/share/fonts'), Path('/usr/local/share/fonts'),
                                Path.home() / '.local/share/fonts', Path.home() / '.fonts') if path.is_dir()]
(qa / 'empty-fonts').mkdir()
os.environ['WECOM_QA_ROOT'] = str(qa)


def client_env(env):
    result = env | {'LANG': 'zh_CN.UTF-8', 'LC_CTYPE': 'zh_CN.UTF-8', 'LC_MESSAGES': 'zh_CN.UTF-8'}
    result.pop('LC_ALL', None)
    return result


def stop(env):
    result = subprocess.run([env['WINESERVER'], '-k'], env=env)
    assert result.returncode in (0, 1)
    subprocess.run([env['WINESERVER'], '-w'], env=env, check=True, timeout=20)


def inspect(env):
    target = qa / 'inspect.jsonl'
    with target.open('w') as out, (qa / 'inspect.log').open('a') as err:
        process = subprocess.Popen([str(files / 'wine/bin/wine'), str(probe), 'inspect'],
                                   env=client_env(env), stdout=out, stderr=err)
        assert process.wait(timeout=20) == 0
    return [json.loads(line) for line in target.read_text().splitlines() if line.startswith('{')]


def launch(env, capture, label, dpi, override=None, busy=False):
    applied = env.copy()
    if override is not None:
        applied['WECOM_DPI'] = override
    else:
        applied.pop('WECOM_DPI', None)
    stamp = prefix / '.wecom-display-fonts.json'
    before = stamp.stat().st_mtime_ns if stamp.exists() else None
    revision = (files / 'application-version').read_text().split()[1]
    with (qa / (label + '.log')).open('w') as log:
        process = subprocess.Popen([str(files / 'start.sh')], env=applied, stdout=log, stderr=log)
    try:
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            assert process.poll() in (None, 0), (label, process.returncode)
            configured = stamp.exists() and stamp.stat().st_mtime_ns != before
            application = prefix / '.wecom-application'
            if configured and application.exists() and application.read_text().strip() == revision:
                main = [window for window in inspect(env) if window['class'] == 'WeChatLogin']
                if main:
                    break
            time.sleep(.2)
        else:
            raise TimeoutError(label + ': login window did not open')
        assert len(main) == 1 and main[0]['dpi'] == dpi, main
        time.sleep(.3)
        capture(qa / (label + '.png'))
        settings = json.loads(stamp.read_text())
        assert settings['dpi'] == dpi, settings
        if busy:
            before = stamp.read_bytes()
            subprocess.run(['python3', str(files / 'configure-prefix.py'), str(files), str(prefix)],
                           env=env | {'WECOM_DPI': '192'}, check=True, timeout=10)
            assert stamp.read_bytes() == before
            assert next(window for window in inspect(env) if window['class'] == 'WeChatLogin')['dpi'] == dpi
        report['cases'].append({'name': label, 'dpi': dpi, 'main': main[0], 'settings': settings,
                                'busy_prefix_unchanged': busy, 'screenshot': str(qa / (label + '.png'))})
    finally:
        stop(env)
        process.wait(timeout=20)


def glyphs(env, label, expected):
    command = ['bwrap', '--ro-bind', '/', '/', '--bind', str(qa), str(qa), '--bind', '/tmp', '/tmp',
               '--proc', '/proc', '--dev-bind', '/dev', '/dev']
    for path in hidden:
        command += ['--ro-bind', str(qa / 'empty-fonts'), path]
    report[label] = {}
    for bits, binary in ((64, probe), (32, probe32)):
        target = qa / f'{label}-{bits}.jsonl'
        with target.open('w') as out, (qa / f'{label}-{bits}.log').open('w') as err:
            process = subprocess.Popen(command + [str(files / 'wine/bin/wine'), str(binary), 'glyphs'],
                                       env=client_env(env), stdout=out, stderr=err)
            status = process.wait(timeout=30)
        result = next(json.loads(line) for line in target.read_text().splitlines() if line.startswith('{'))
        assert (status == 0) is expected, (bits, status, result)
        assert (result['distinct'] == 4) is expected, result
        report[label][bits] = result | {'host_fonts_hidden': hidden}
        stop(env)


for scale in (1, 2):
    os.environ['WECOM_QA_SCALE'] = str(scale)
    with desktop(qa) as base:
        env = base | {'WINEPREFIX': str(prefix), 'WINESERVER': str(files / 'wine/bin/wineserver'),
                      'WINEDEBUG': '-all'}
        with recording(qa, env, f'prefix-scale-{scale}') as capture:
            if scale == 1:
                launch(env, capture, 'fresh-100-percent', 96, busy=True)
                private = prefix / 'drive_c/users' / os.environ['USER'] / 'Documents/prefix-migration-check.txt'
                private.write_text('preserve application and account data\n')
                private_digest = hashlib.sha256(private.read_bytes()).hexdigest()
                fonts = prefix / 'drive_c/windows/Fonts'
                (qa / 'preserved-cjk-fonts').mkdir()
                for font in fonts.glob('SourceHan*'):
                    font.rename(qa / 'preserved-cjk-fonts' / font.name)
                marker = prefix / '.wecom-display-fonts.json'
                marker.rename(qa / 'settings-before-font-repair.json')
                glyphs(env, 'missing-cjk-negative', False)
                launch(env, capture, 'existing-prefix-font-repair', 96, override='auto')
                glyphs(env, 'repaired-cjk', True)
                assert hashlib.sha256(private.read_bytes()).hexdigest() == private_digest
            else:
                launch(env, capture, 'automatic-200-percent', 192)
                for key in (r'HKCU\Control Panel\Desktop', r'HKCU\Software\Wine\Fonts'):
                    subprocess.run([str(files / 'wine/bin/wine'), 'reg', 'add', key, '/v', 'LogPixels',
                                    '/t', 'REG_DWORD', '/d', '120', '/f'], env=client_env(env), check=True)
                stop(env)
                launch(env, capture, 'manual-dpi-preserved', 120)
                launch(env, capture, 'explicit-return-to-auto', 192, override='auto')
                assert hashlib.sha256(private.read_bytes()).hexdigest() == private_digest

assert all(hashlib.sha256((files / 'template' / name).read_bytes()).hexdigest() == value
           for name, value in original.items())
report.update(passed=True, template_unchanged=True, private_data_preserved=True)
(qa / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False))
