#!/usr/bin/env python3
"""Package locally cross-compiled codecs with a verified standalone Python runtime.

The runtime archive SHA-256 must match its official python-build-standalone
release metadata. macOS execution requires a Mac; Windows can be tested in Wine.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

ROOT=Path(__file__).resolve().parent.parent
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('target',choices=['macos-arm64','macos-x86_64','windows-x86_64'])
parser.add_argument('--runtime',type=Path,required=True)
parser.add_argument('--runtime-sha256',required=True)
parser.add_argument('--zig',required=True)
parser.add_argument('--output',type=Path,required=True)
args=parser.parse_args()
assert hashlib.sha256(args.runtime.read_bytes()).hexdigest()==args.runtime_sha256,'Runtime checksum mismatch'
args.output.mkdir(parents=True,exist_ok=True)
windows=args.target.startswith('windows')
suffix='.exe' if windows else ''
triple={'macos-arm64':'aarch64-macos.11.0','macos-x86_64':'x86_64-macos.11.0','windows-x86_64':'x86_64-windows-gnu'}[args.target]
with tempfile.TemporaryDirectory(prefix='mobipeg-cross-package-') as temp:
    bundle=Path(temp)/'MobiPEGStudio';bundle.mkdir()
    with tarfile.open(args.runtime) as runtime:runtime.extractall(bundle,filter='data')
    (bundle/'local/bin').mkdir(parents=True)
    for name in ['ffmpeg','ffprobe']:
        shutil.copy2(ROOT/'.build/cross'/args.target/'local/bin'/(name+suffix),bundle/'local/bin'/(name+suffix))
    subprocess.run([args.zig,'cc','-target',triple,str(ROOT/'scripts/portable-launcher.c'),
                    *(['-municode'] if windows else []),'-O2','-o',str(bundle/('MobiPEGStudio'+suffix))],check=True,env={**os.environ,'ZIG_GLOBAL_CACHE_DIR':os.environ.get('ZIG_GLOBAL_CACHE_DIR',str(ROOT/'.build/zig-launcher-cache'))})
    for module in (ROOT/'native').glob('*.py'):
        shutil.copy2(module,bundle/module.name)
    shutil.copy2(ROOT/'LICENSE',bundle/'LICENSE')
    shutil.copy2(ROOT/'native/PORTABLE_BUILDS.md',bundle/'README.md')
    (bundle/'BUILD.txt').write_text(f'Target: {args.target}\nCross-compiler: Zig 0.14.1\nRuntime: {args.runtime.name}\nRuntime SHA256: {args.runtime_sha256}\nMac packages are cross-compiled; Mac execution/GUI is unverified.\n')
    with zipfile.ZipFile(bundle/'corresponding-source.zip','w',zipfile.ZIP_DEFLATED) as archive:
        names=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
        for name in names:
            if name.startswith('native/source/'):archive.write(ROOT/name,name)
        for module in (ROOT/'native').glob('*.py'):
            archive.write(module,module.relative_to(ROOT))
        for name in ['native/BUILD_FOR_LINUX.sh','native/BUILD_FOR_MAC.command','native/BUILD_FOR_WINDOWS.sh','native/PORTABLE_BUILDS.md','scripts/build-cross.sh','scripts/package-cross.py','scripts/portable-launcher.c','scripts/smoke-cross-windows.py','LICENSE']:
            archive.write(ROOT/name,name)
    label='MobiPEG-'+args.target
    # tar preserves macOS runtime symlinks and executable modes.
    path=Path(shutil.make_archive(str(args.output/label),'zip' if windows else 'gztar',bundle.parent,bundle.name))
    path.with_name(path.name+'.sha256').write_text(hashlib.sha256(path.read_bytes()).hexdigest()+'  '+path.name+'\n')
    print(path)
