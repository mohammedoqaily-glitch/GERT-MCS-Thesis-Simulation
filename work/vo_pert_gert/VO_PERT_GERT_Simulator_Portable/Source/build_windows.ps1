$ErrorActionPreference = "Stop"
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install openpyxl pyinstaller
.\.venv\Scripts\pyinstaller.exe --noconfirm --onedir --windowed --name VO_PERT_GERT_Simulator vo_pert_gert\__main__.py
New-Item -ItemType Directory -Force -Path VO_PERT_GERT_Simulator_Portable\Application_Files | Out-Null
Copy-Item -Recurse -Force dist\VO_PERT_GERT_Simulator\* VO_PERT_GERT_Simulator_Portable\Application_Files\
Copy-Item -Force dist\VO_PERT_GERT_Simulator\VO_PERT_GERT_Simulator.exe VO_PERT_GERT_Simulator_Portable\VO_PERT_GERT_Simulator.exe
