@echo off
rem ============================================================
rem  Music Library Optimizer v1.1.0 - executable builder
rem  Produces: Music Library Optimizer.exe (GUI) + mlo.exe (CLI)
rem  Requires: pip install pyinstaller mutagen pillow PySide6
rem ============================================================
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
    --icon app_icon.ico --hidden-import mutagen.aac ^
    --name "Music Library Optimizer" app.py || goto :err

python -m PyInstaller --noconfirm --clean --onefile --console ^
    --icon app_icon.ico --hidden-import mutagen.aac ^
    --name mlo mlo_cli.py || goto :err

copy /y "dist\Music Library Optimizer.exe" . >nul
copy /y "dist\mlo.exe" . >nul
echo.
echo Built: Music Library Optimizer.exe + mlo.exe (project root)
pause
exit /b 0

:err
echo BUILD FAILED
pause
exit /b 1
