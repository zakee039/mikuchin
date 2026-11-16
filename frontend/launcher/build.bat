@echo off
setlocal
cd /d "%~dp0"
set "PATH=%USERPROFILE%\.cargo\bin;%PATH%"
if not exist node_modules (call npm ci --no-audit --no-fund || exit /b 1)
call npm run build || exit /b 1
if not exist portable mkdir portable
for /f "delims=" %%V in ('node -p "require('./package.json').version"') do set "APP_VERSION=%%V"
if not defined APP_VERSION exit /b 1
copy /y "src-tauri\target\release\mikuchin.exe" "portable\Mikuchin.exe" >nul
if errorlevel 1 (
  rem Do not terminate a running portable launcher just to replace its executable.
  copy /y "src-tauri\target\release\mikuchin.exe" "portable\Mikuchin-v%APP_VERSION%.exe" >nul || exit /b 1
  echo Running launcher is in use. Built: %CD%\portable\Mikuchin-v%APP_VERSION%.exe
) else (
  echo Portable build: %CD%\portable\Mikuchin.exe
)
