@echo off
rem Gera dist\MacroControle.exe (um arquivo so, com as macros padrao, o icone e o driver dentro).
cd /d "%~dp0"
set R=%~dp0
py -3 -m pip install --quiet pygame vgamepad keyboard customtkinter pillow pyinstaller
for /f "delims=" %%i in ('py -3 -c "import vgamepad,os;print(os.path.join(os.path.dirname(vgamepad.__file__),'win','vigem','install','x64'))"') do set VIGEM=%%i
for %%f in ("%VIGEM%\*.msi") do set MSI=%%~ff
py -3 -m PyInstaller --noconfirm --onefile --windowed --name MacroControle --icon "%R%icone.ico" ^
  --add-data "%R%icone.ico;." --add-data "%R%icone.png;." --add-data "%R%padrao;padrao" ^
  --add-data "%MSI%;." --collect-all vgamepad --collect-all customtkinter ^
  --distpath "%R%dist" --workpath "%R%build" --specpath "%R%build" "%R%app.py"
