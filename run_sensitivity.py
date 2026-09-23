from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from sensitivity.analysis import run_analysis
from sensitivity.config import load_config


ROOT = Path(__file__).resolve().parent
NODE_ROOT = Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node"


def build_workbooks() -> None:
    node = NODE_ROOT / "bin" / "node.exe"
    dependencies = NODE_ROOT / "node_modules"
    builder = ROOT / "work" / "sensitivity_workbook" / "build_sensitivity_workbooks.mjs"
    local_dependencies = builder.parent / "node_modules"
    if not node.exists() or not dependencies.exists() or not builder.exists():
        raise RuntimeError("Bundled Node.js, artifact-tool dependencies, or the workbook builder is unavailable")
    if not local_dependencies.exists():
        command = (
            f"New-Item -ItemType Junction -Path '{local_dependencies}' "
            f"-Target '{dependencies}' | Out-Null"
        )
        link = subprocess.run(["powershell", "-NoProfile", "-Command", command], capture_output=True, text=True)
        if link.returncode:
            raise RuntimeError(f"Could not create the workbook dependency junction: {link.stderr.strip()}")
    result = subprocess.run([str(node), str(builder), str(ROOT)], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        detail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-30:])
        raise RuntimeError(f"Workbook generation failed:\n{detail}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run verified VO PERT-GERT sensitivity and robustness analysis")
    parser.add_argument("--config", default="sensitivity_config.yaml")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--run-tests", action="store_true")
    parser.add_argument("--skip-workbooks", action="store_true")
    args = parser.parse_args()
    if args.run_tests:
        result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"])
        raise SystemExit(result.returncode)
    config = load_config(args.config)
    summary = run_analysis(config, baseline_only=args.baseline_only)
    workbooks_generated = False
    if not args.baseline_only and not args.skip_workbooks:
        build_workbooks()
        workbooks_generated = True
    print(json.dumps({
        "status": summary["status"],
        "output_directory": config["output_directory"],
        "baseline_only": args.baseline_only,
        "distinct_full_simulation_runs": summary.get("distinct_full_simulation_runs", 1),
        "workbooks_generated": workbooks_generated,
    }, indent=2))


if __name__ == "__main__":
    main()
