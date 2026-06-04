@echo off
rem ============================================================
rem  resource.dll build batch
rem
rem  Compiles resource.rc (which #includes resource_r.h) and
rem  produces a resource-only DLL (resource.dll) that contains
rem  no code. Self-contained: does not use rena.dsp / VS.
rem
rem  resource.rc and resource_r.h are generated from sakura.rc
rem  and resource.h by make_resource_rc.py. Run release.bat to
rem  regenerate them and build in one step, or run
rem  make_resource_rc.py manually before this batch.
rem ============================================================

setlocal
cd /d "%~dp0"

rem --- Setup VC++ environment (vcvars32.bat) -------------------
rem  vcvars32.bat should be reachable on PATH if any VC++ is
rem  installed. Skip if the tools (rc.exe) are already available.
where vcvars32.bat >nul 2>&1
if errorlevel 1 goto :novcvars
call vcvars32.bat
:vcdone

rem --- Precondition: generated sources must exist --------------
if not exist "resource.rc"   goto :nosrc
if not exist "resource_r.h"  goto :nosrc

rem --- 1) Compile resource:  resource.rc -> Release\resource.res
echo [1/2] Compiling resource: resource.rc
rc.exe /l 0x409 /d "NDEBUG" /fo "resource.res" "resource.rc"
if errorlevel 1 goto :error

rem --- 2) Link:  resource.res -> resource.dll -------------------
echo [2/2] Linking: resource.dll
del "resource.dll"
link.exe /nologo /dll /pdb:none /machine:I386 /nodefaultlib /out:"resource.dll" /noentry "resource.res"
del "resource.res"
if errorlevel 1 goto :error

echo.
echo [OK] resource.dll built successfully.
endlocal
exit /b 0

:novcvars
echo.
echo [FAILED] vcvars32.bat not found on PATH.
echo          Install Visual C++ or run this from a VC command prompt.
endlocal
exit /b 1

:nosrc
echo.
echo [FAILED] resource.rc / resource_r.h not found.
echo          Run make_resource_rc.py or release.bat first.
endlocal
exit /b 1

:error
echo.
echo [FAILED] build failed.
endlocal
exit /b 1
