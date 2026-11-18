# First console check for browser-built movie CIAs

Generate the two synthetic fixtures from the repository root with the existing native encoder installed:

```sh
python3 scripts/prepare-cia-device-test.py /path/to/new-test-directory
node scripts/dev-server.mjs
```

Open `http://localhost:4173/cia.html` on the computer running the server. Select both generated MOFLEX files in episode order and your own legally obtained compatible collection-player CIA template. The template and player are processed locally. No template or player executable is included in this kit. Choose an unused title ID. The generated project suggests `C7E57`, which must be changed if already installed. The device report should record the selected title ID and the commit used.

Set the menu names to `1: red / 440 Hz pulses` and `2: blue / 880 Hz pulses`. Optionally choose a banner image and a short mono/stereo PCM16 WAV. Build the CIA, save its checksum, and independently inspect it before copying to the SD card:

```sh
python3 native/cia_builder.py verify movie.cia
sha256sum movie.cia
```

Both fixtures contain six seconds at 24 fps, 400×240, 2D video with ADPCM audio. White flashes and a short tone occur together every second. Episode one has a red background and 440 Hz pulses. Episode two has a blue background and 880 Hz pulses. These files are generated from filters and contain no private media.

## Console run

Record console model, system software, custom firmware version, installer version, SD filesystem, title ID, CIA checksum and MobiPEG commit.

1. Install the CIA with FBI and record any error code exactly.
2. Return to the HOME Menu. Confirm title, icon, banner image and optional banner sound.
3. Launch the application. Confirm a two-episode menu with the correct names and thumbnails.
4. Select episode one. Confirm red background, white flashes and low tone pulses. Let it finish.
5. Return to the menu and play episode two. Confirm blue background and higher tone pulses.
6. Reopen episode one. Check pause/resume, seek and return-to-menu behavior where available. Record whether each flash and tone remain aligned.
7. Close the app, relaunch it and confirm episode selection still works.

Report each step as pass/fail/untested. Include error codes, visible symptoms and repeatability. A phone recording can help compare flash/tone alignment. Avoid including personal account information or other installed titles in screenshots.

This first check covers a small 2D collection. Separate follow-up tests must cover stereoscopic movies, longer playback, long seeks, FastAudio, 20–27 episode navigation, large-file installation and browser/iPhone storage behavior. Software verification and native banner previews do not establish physical console compatibility.
