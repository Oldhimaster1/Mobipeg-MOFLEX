@echo off
setlocal
if "%~1"=="" (
  echo Usage: V8_ENCODE_STEREO.cmd input_HSBS.mp4 [additional options]
  exit /b 2
)
set "INPUT=%~1"
py -3 "%~dp0V8\encode_stereo_v8.py" "%INPUT%" --encoder "%~dp0local\bin\ffmpeg.exe" --probe "%~dp0local\bin\ffprobe.exe"
exit /b %ERRORLEVEL%
