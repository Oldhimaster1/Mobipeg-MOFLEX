#!/usr/bin/env python3
"""Package the locally built encoder and Python/Tk runtime, without publishing."""
import argparse
import hashlib
import platform
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='Directory outside the checkout for archives')
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents:
        parser.error('Choose an output directory outside the checkout')
    system = {'Linux': 'linux', 'Darwin': 'macos', 'Windows': 'windows'}[platform.system()]
    machine = platform.machine().lower()
    arch = {'amd64': 'x86_64', 'aarch64': 'arm64'}.get(machine, machine)
    label = f'MobiPEG-{system}-{arch}'
    suffix = '.exe' if system == 'windows' else ''
    binaries = [ROOT / 'native/local/bin' / (name + suffix)
                for name in ('ffmpeg', 'ffprobe')]
    for binary in binaries:
        if not binary.is_file():
            parser.error(f'Build the custom encoder first: missing {binary}')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mobipeg-package-') as temp:
        work = Path(temp)
        command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
                   '--onedir', '--name', 'MobiPEGStudio',
                   '--distpath', str(work / 'dist'), '--workpath', str(work / 'build'),
                   '--specpath', str(work)]
        for binary in binaries:
            command += ['--add-binary', f'{binary}:local/bin']
        command += [str(ROOT / 'native/MobiPEG_Studio_V15.py')]
        subprocess.run(command, cwd=ROOT, check=True)
        bundle = work / 'dist/MobiPEGStudio'
        # Test the frozen executable, including its bundled encoder, before shipping.
        subprocess.run([sys.executable, str(ROOT / 'scripts/smoke-native-package.py'),
                        str(bundle / ('MobiPEGStudio' + suffix))], check=True)
        shutil.copy2(ROOT / 'LICENSE', bundle / 'LICENSE')
        shutil.copy2(ROOT / 'native/PORTABLE_BUILDS.md', bundle / 'README.md')
        (bundle / 'BUILD.txt').write_text(
            f'Platform: {platform.platform()}\nArchitecture: {arch}\n'
            f'Build libc: {platform.libc_ver()}\nPython: {platform.python_version()}\n'
            'Local Linux packages require a compatible build-host libc.\n'
            'GUI interaction and physical 3DS playback are not covered by package smoke tests.\n')
        # Ship exact corresponding project sources and their upstream notices.
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode().split('\0')
        with zipfile.ZipFile(bundle / 'corresponding-source.zip', 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in tracked:
                if name and name.startswith('native/source/'):
                    archive.write(ROOT / name, name)
            for module in (ROOT/'native').glob('*.py'):
                archive.write(module,module.relative_to(ROOT))
            for name in ['LICENSE', 'README.md',
                         'native/BUILD_FOR_LINUX.sh', 'native/BUILD_FOR_MAC.command',
                         'native/BUILD_FOR_WINDOWS.sh', 'native/PORTABLE_BUILDS.md',
                         'scripts/package-native.py', 'scripts/smoke-native-package.py',
                         'scripts/build-cross.sh', 'scripts/package-cross.py',
                         'scripts/portable-launcher.c', 'scripts/check-macho.py', 'scripts/smoke-cross-windows.py']:
                archive.write(ROOT / name, name)
        if system == 'windows':
            archive_path = Path(shutil.make_archive(str(output / label), 'zip', bundle.parent, bundle.name))
        else:
            archive_path = Path(shutil.make_archive(str(output / label), 'gztar', bundle.parent, bundle.name))
        digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        archive_path.with_name(archive_path.name + '.sha256').write_text(f'{digest}  {archive_path.name}\n')
        print(archive_path)


if __name__ == '__main__':
    main()
