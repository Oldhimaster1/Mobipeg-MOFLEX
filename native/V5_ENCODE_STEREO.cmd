@echo off
setlocal
py -3 "%~dp0V5\encode_stereo_v5.py" %*
exit /b %ERRORLEVEL%
