@echo off
rem SubFontMKV launcher (ASCII only: keep this file free of non-ASCII text,
rem changing the code page mid-batch corrupts cmd.exe line parsing).
setlocal
cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo [ERROR] Python 3.7+ was not found in PATH.
  echo         Install Python from https://www.python.org/downloads/
  pause
  exit /b 1
)

%PYEXE% -c "import tkinter" >nul 2>nul
if errorlevel 1 (
  echo [ERROR] This Python has no tkinter, so the GUI cannot start.
  echo         Use the command line instead: subfontmkv.bat "your-video.mkv"
  pause
  exit /b 1
)

%PYEXE% -c "import fontTools" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing missing dependency: fonttools ...
  %PYEXE% -m pip install fonttools
)

%PYEXE% -m subfontmkv gui %*
if errorlevel 1 pause
endlocal
