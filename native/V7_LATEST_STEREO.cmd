@echo off
setlocal
set "ROOT=%~dp0"
if "%~1"=="" (echo Usage: V7_LATEST_STEREO.cmd source_HSBS.mp4 [options] & exit /b 1)
if not exist "%ROOT%local\bin\ffmpeg.exe" (echo ERROR: V7 Windows ffmpeg.exe must be built before running. & exit /b 2)
if not exist "%ROOT%local\bin\ffprobe.exe" (echo ERROR: ffprobe.exe missing. & exit /b 2)
py -3 "%ROOT%V7\encode_stereo_v7.py" "%~1" --encoder "%ROOT%local\bin\ffmpeg.exe" --probe "%ROOT%local\bin\ffprobe.exe" %2 %3 %4 %5 %6 %7 %8 %9
exit /b %errorlevel%
