# Portable desktop builds

The `Native portable packages` GitHub Actions workflow builds Linux x86-64,
Windows x86-64, macOS Intel, and macOS Apple Silicon independently. Run it manually
or push a `native-v*` tag. Each successful job uploads an archive and SHA-256 file
as workflow artifacts. Successful tag builds also attach packages to an existing matching GitHub prerelease. Manual runs can specify an existing release tag. The workflow does not create a release.

Each archive includes the Python/Tk runtime, this project's custom FFmpeg and
ffprobe, and corresponding project source with its upstream license notices.
Python and stock FFmpeg do not need to be installed by the user. Extract the
entire archive; keep `_internal` beside the executable.

Open `MobiPEGStudio.exe` on Windows or `MobiPEGStudio` on Linux/macOS to launch
the graphical interface. A graphical desktop is required. For command-line use:

```sh
./MobiPEGStudio --input movie.mp4 --mode 2d --preset quality
./MobiPEGStudio --help
```

On Windows use `MobiPEGStudio.exe` in place of `./MobiPEGStudio`.
Existing destination files are preserved unless `--overwrite` is supplied.

CI Linux builds target glibc 2.35 or later (Ubuntu 22.04 or compatible) and need
desktop display libraries for Tk. Local packages inherit their build host's
requirements; see `BUILD.txt` for the build OS and libc version. Mac builds are
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
