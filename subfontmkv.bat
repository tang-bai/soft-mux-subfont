@echo off
rem SubFontMKV command line launcher (ASCII only).
setlocal
cd /d "%~dp0"

set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if not defined PYEXE where python >nul 2>nul && set "PYEXE=python"
if not defined PYEXE (
  echo [ERROR] Python 3.7+ was not found in PATH.
  exit /b 1
)

%PYEXE% -c "import fontTools" >nul 2>nul
if errorlevel 1 (
  echo [INFO] Installing missing dependency: fonttools ...
  %PYEXE% -m pip install fonttools
)

%PYEXE% -m subfontmkv %*
endlocal
