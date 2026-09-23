from pathlib import Path
from vo_pert_gert.engine import demo_only_case, save_case
from vo_pert_gert.outputs import generate_outputs

root = Path(__file__).resolve().parent
portable = root / "VO_PERT_GERT_Simulator_Portable"
portable.mkdir(exist_ok=True)
(portable / "Application_Files").mkdir(exist_ok=True)
(portable / "Input_Templates").mkdir(exist_ok=True)
(portable / "Sample_Run_Outputs").mkdir(exist_ok=True)
(portable / "Source").mkdir(exist_ok=True)
case = demo_only_case()
save_case(case, portable / "Input_Templates" / "default_case.json")
generate_outputs(case, portable / "Sample_Run_Outputs", 1000)
(portable / "README.txt").write_text("Run with bundled/rebuilt Python: python -m vo_pert_gert. Build a Windows exe using build_windows.ps1 on a Windows machine with Python, PySide6 or Tkinter, openpyxl, and PyInstaller.\n", encoding="utf-8")
(portable / "Version_Information.txt").write_text("VO PERT-GERT Monte Carlo Simulator source package 0.1.0\nExecutable build status: not built in this environment; PyInstaller unavailable.\n", encoding="utf-8")
(portable / "User_Manual.pdf").write_bytes(b"%PDF-1.4\n% Minimal placeholder manual generated because report renderer was not invoked.\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF")
