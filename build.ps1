# Construit dist\rushgrab.exe
$ErrorActionPreference = 'Stop'
if (-not (Test-Path .venv)) { python -m venv .venv }
.venv\Scripts\python -m pip install --quiet -r requirements.txt pyinstaller
.venv\Scripts\pyinstaller --noconfirm --onefile --windowed --name rushgrab `
    --icon assets\icon.ico --add-data "assets\icon.ico;assets" `
    --collect-data customtkinter app.py
