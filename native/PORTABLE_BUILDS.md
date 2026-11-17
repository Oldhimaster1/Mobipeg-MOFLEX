# Portable desktop builds

Packages are built locally; GitHub Actions is not required. Linux uses the native
build and PyInstaller. Windows and both Mac architectures can be cross-compiled
on Linux with Zig 0.14.1 and the LLVM archive tools from Emscripten 4.0.10. The
cross packages include a checksum-verified Python 3.12.16 standalone runtime
from the official astral-sh/python-build-standalone release 20261110.

Windows cross packages are checked with Wine. Mac packages have their binary
architecture/imports checked, but Mac execution and GUI behavior require a Mac
and remain unverified. Cross-compiled Mac encoders target macOS 11 or later.

Each archive includes the Python/Tk runtime, this project's custom FFmpeg and
ffprobe, and corresponding project source with its upstream license notices.
Python and stock FFmpeg do not need to be installed by the user. Extract the
entire archive. Linux packages keep `_internal` beside the executable; cross
packages keep `python`, `local`, and `MobiPEG_Studio_V15.py` beside the launcher.

Open `MobiPEGStudio.exe` on Windows or `MobiPEGStudio` on Linux/macOS to launch
the graphical interface. A graphical desktop is required. For command-line use:

```sh
./MobiPEGStudio --input movie.mp4 --mode 2d --preset quality
./MobiPEGStudio --help
```

On Windows use `MobiPEGStudio.exe` in place of `./MobiPEGStudio`.
Existing destination files are preserved unless `--overwrite` is supplied.

Linux packages inherit their build host's glibc requirements and need desktop
display libraries for Tk. See `BUILD.txt` for the build OS and libc version. Mac builds are
separate for Intel and Apple Silicon;
the workflow currently creates unsigned portable binaries, not signed or notarized
app installers. Windows builds are also unsigned. Hardware playback validation
is separate from the package's software encode/decode tests.

## Build locally

From the repository root, build the encoder with the script for your platform:

```sh
bash native/BUILD_FOR_LINUX.sh
# macOS: bash native/BUILD_FOR_MAC.command
# Windows, inside MSYS2 MINGW64: bash native/BUILD_FOR_WINDOWS.sh
```

Install Python 3.12 with Tk support, then use a virtual environment:

```sh
python -m pip install pyinstaller==6.16.0
python scripts/package-native.py --output /absolute/path/outside/checkout
```

PyInstaller packages the host platform; run it on the intended OS and architecture.
The packager tests the frozen executable's 2D and half-SBS conversions with generated
audio/video, checks packet counts and codecs, decodes the output, and checks
existing-file protection before creating an archive. GUI interaction still needs
platform-specific manual testing. Build logs must establish success before a
platform's package is described as available or verified.

## Cross-build locally on Linux

Set `ZIG` to Zig 0.14.1's executable and `LLVM_TOOLS` to the Emscripten SDK's
`upstream/bin` directory. Build each required target:

```sh
bash scripts/build-cross.sh windows-x86_64
bash scripts/build-cross.sh macos-arm64
bash scripts/build-cross.sh macos-x86_64
```

Download the matching `install_only_stripped` Python runtime from the official
python-build-standalone 20261110 release and verify its digest against that
release's asset metadata or SHA256SUMS. Then package with:

```sh
python3 scripts/package-cross.py macos-arm64 --runtime RUNTIME.tar.gz --runtime-sha256 VERIFIED_SHA256 --zig "$ZIG" --output /absolute/output/directory
```

Use the matching target/runtime for Windows or Intel Mac. This produces a native
launcher, the custom FFmpeg/ffprobe pair, the Python/Tk runtime, licenses and exact
corresponding project sources. Cross packages are not signed or notarized.
