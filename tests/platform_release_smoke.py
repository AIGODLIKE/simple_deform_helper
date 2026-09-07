"""Build, install and exercise a release in isolated CI profiles."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


SOURCE = Path(__file__).resolve().parents[1]
MODULE = "bl_ext.sdh_test.simple_deform_helper"


def blender_phase():
    import bpy

    root = Path(os.environ["SDH_PLATFORM_ROOT"]).resolve()
    for kind in ("CONFIG", "SCRIPTS", "DATAFILES", "EXTENSIONS"):
        expected = (root / kind.lower()).resolve()
        actual = Path(bpy.utils.user_resource(kind)).resolve()
        if actual != expected or not expected.is_dir():
            raise RuntimeError(f"Resource isolation failed: {kind}: {actual}")
    bpy.context.preferences.filepaths.temporary_directory = str(root / "temp")
    bpy.context.preferences.view.show_splash = False
    if bpy.app.version_string != os.environ["SDH_PLATFORM_VERSION"]:
        # LTS is a display suffix, not a different version.
        actual = ".".join(str(part) for part in bpy.app.version)
        if actual != os.environ["SDH_PLATFORM_VERSION"]:
            raise RuntimeError(f"Unexpected Blender version: {bpy.app.version_string}")
    print(f"ISOLATION_OK::{bpy.app.version_string}")
    phase = os.environ["SDH_PLATFORM_PHASE"]
    if phase == "prepare":
        bpy.ops.wm.save_userpref()
    elif phase == "enable":
        import addon_utils

        module = addon_utils.enable(MODULE, default_set=True)
        if module is None or not addon_utils.check(MODULE)[1]:
            raise RuntimeError("Installed extension did not enable")
        bpy.ops.wm.save_userpref()
        print("INSTALLED_ENABLE_OK")
    elif phase == "restart":
        import addon_utils

        if not addon_utils.check(MODULE)[1]:
            raise RuntimeError("Installed extension did not auto-enable on restart")
        print("INSTALLED_RESTART_OK")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--blender", default=os.environ.get("BLENDER_EXE"), required=False)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--gui-scripts", nargs="+", default=[])
    args = parser.parse_args()
    if not args.blender:
        parser.error("--blender or BLENDER_EXE is required")
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="sdh-", dir=args.output)).resolve()
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("BLENDER_USER_")}
    for kind in ("CONFIG", "SCRIPTS", "DATAFILES", "EXTENSIONS"):
        directory = root / kind.lower()
        directory.mkdir()
        env[f"BLENDER_USER_{kind}"] = str(directory)
    (root / "temp").mkdir()
    (root / "repository").mkdir()
    env.update({
        "TEMP": str(root / "temp"), "TMP": str(root / "temp"),
        "TMPDIR": str(root / "temp"), "SDH_PLATFORM_ROOT": str(root),
        "SDH_PLATFORM_VERSION": args.version, "PYTHONDONTWRITEBYTECODE": "1",
    })
    archive = root / "simple_deform_helper.zip"
    steps = []

    def run(name, *tail, phase="guard", factory=True, installed=False, gui=False):
        command = [str(Path(args.blender).resolve())]
        if gui:
            command.append("--enable-event-simulate")
        else:
            command.append("--background")
        if factory:
            command.append("--factory-startup")
        command += ["--python-exit-code", "1", "--python", str(Path(__file__).resolve())]
        command.extend(str(part) for part in tail)
        child_env = dict(env, SDH_PLATFORM_PHASE=phase)
        if installed:
            child_env["SDH_TEST_MODULE"] = MODULE
        result = subprocess.run(command, env=child_env, cwd=SOURCE,
                                capture_output=True, text=True,
                                encoding="utf-8", timeout=240)
        (root / f"{name}.stdout.log").write_text(result.stdout, encoding="utf-8")
        (root / f"{name}.stderr.log").write_text(result.stderr, encoding="utf-8")
        (root / f"{name}.command.json").write_text(json.dumps(command), encoding="utf-8")
        print(f"{name}: exit {result.returncode}", flush=True)
        if result.returncode or "ISOLATION_OK" not in result.stdout:
            raise RuntimeError(f"{name} failed\n{result.stdout}\n{result.stderr}")
        steps.append(name)
        return result

    if args.gui_scripts:
        run("gui-preferences", phase="prepare")
        for script in args.gui_scripts:
            script_path = SOURCE / "tests" / script
            result_path = root / f"{script_path.stem}.txt"
            screenshot = root / f"{script_path.stem}.png"
            process = run(script_path.stem, "--python", script_path, "--", result_path,
                          screenshot, gui=True)
            if not result_path.read_text(encoding="utf-8").startswith("PASS"):
                raise RuntimeError(f"GUI test failed: {result_path.read_text(encoding='utf-8')}")
            if script == "stack_preset_redo_regression.py":
                for preset in ("AA Redo Regression Stack", "ZZ Retained Preset"):
                    if f"Deleted preset {preset}" not in process.stdout:
                        raise RuntimeError(f"Deleted preset report missing: {preset}")
        (root / "result.json").write_text(json.dumps({
            "result": "PASS", "version": args.version, "steps": steps,
            "platform": sys.platform,
        }, indent=2), encoding="utf-8")
        print(f"PLATFORM_GUI_PASS::{root}")
        return

    run("source-validate", "--command", "extension", "validate", SOURCE)
    for script in ("runtime_regression", "legacy_lattice_origin_regression",
                   "legacy_animation_migration_regression", "cage_deform_regression",
                   "unified_deform_stack_regression", "selection_watch_idle_regression",
                   "chain_prefix_parameter_sync_regression",
                   "ffd_native_edit_regression",
                   "registration_conflict_regression"):
        run(script, "--python", SOURCE / "tests" / f"{script}.py")
    run("build", "--command", "extension", "build", "--source-dir", SOURCE,
        "--output-filepath", archive)
    run("zip-validate", "--command", "extension", "validate", archive)
    run("repository", "--command", "extension", "repo-add", "sdh_test", "--name",
        "SDH Test", "--directory", root / "repository")
    run("install", "--command", "extension", "install-file", "-r", "sdh_test",
        archive, factory=False)
    run("enable", phase="enable", factory=False)
    run("restart", phase="restart", factory=False)
    run("installed-lifecycle", "--python", SOURCE / "tests" / "installed_lifecycle.py",
        factory=False, installed=True)
    report = {"version": args.version, "platform": sys.platform, "steps": steps,
              "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "result": "PASS"}
    (root / "result.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"PLATFORM_RELEASE_PASS::{root}")


if __name__ == "__main__":
    if os.environ.get("SDH_PLATFORM_PHASE"):
        blender_phase()
    else:
        main()
