"""Freeze a pinned original KaTrain and bundle the local Metal KataGo runtime."""

import hashlib
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
ROOT = APP
BUILD = APP / "build"
UPSTREAM = BUILD / "upstream"
RESOURCES = BUILD / "resources"
# Deliberately ignore working-tree changes made for KaTrain Workspace.
REVISION = "f4981cf905cece90085ce4e3967415d0c16d525f"
UPSTREAM_URL = "https://github.com/sanderland/katrain.git"


def run(*args, **kwargs):
    subprocess.run([str(a) for a in args], check=True, **kwargs)


def bundle_macho(source, destination, copied):
    source = Path(source).resolve()
    destination = Path(destination)
    if source in copied:
        return copied[source]
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)
    destination.chmod(0o755)
    copied[source] = destination
    dependencies = subprocess.check_output(["otool", "-L", str(source)], text=True).splitlines()[1:]
    for line in dependencies:
        dep = line.strip().split(" (", 1)[0]
        if dep.startswith(("/opt/homebrew/", "/usr/local/")):
            dependency = bundle_macho(dep, destination.parent / Path(dep).name, copied)
            run("install_name_tool", "-change", dep, "@loader_path/" + dependency.name, destination)
    run("codesign", "--force", "--sign", "-", destination)
    return destination


def main():
    if sys.platform != "darwin":
        raise SystemExit("This packaging target is macOS; build Windows/Linux bundles on their target OS.")
    BUILD.mkdir(parents=True, exist_ok=True)
    binary = os.environ.get("KATAGO_BINARY") or shutil.which("katago")
    model_value = os.environ.get("KATAGO_MODEL")
    if not binary or not Path(binary).is_file():
        raise SystemExit("Set KATAGO_BINARY to a local macOS arm64 KataGo executable.")
    if not model_value or not Path(model_value).is_file():
        raise SystemExit("Set KATAGO_MODEL to a local compatible KataGo .bin.gz model.")
    source_repo = BUILD / "upstream-git"
    if not (source_repo / ".git").exists():
        run("git", "init", source_repo)
    run("git", "-C", source_repo, "fetch", "--depth=1", UPSTREAM_URL, REVISION)
    if UPSTREAM.exists():
        shutil.rmtree(UPSTREAM)
    UPSTREAM.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryFile() as archive:
        run("git", "archive", REVISION, "katrain", "LICENSE", "README.md", cwd=source_repo, stdout=archive)
        archive.seek(0)
        with tarfile.open(fileobj=archive) as files:
            files.extractall(UPSTREAM, filter="data")
    # Models are supplied as an explicit resource, not an unrelated duplicate.
    shutil.rmtree(UPSTREAM / "katrain/models", ignore_errors=True)
    run(
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "katrain-host",
        "--distpath",
        BUILD / "frozen",
        "--workpath",
        BUILD / "pyinstaller",
        "--specpath",
        BUILD,
        "--paths",
        UPSTREAM,
        "--add-data",
        f"{UPSTREAM / 'katrain'}:katrain",
        "--collect-data",
        "kivy",
        "--collect-all",
        "ffpyplayer",
        "--collect-data",
        "pygame",
        "--hidden-import",
        "kivy.core.window.window_sdl2",
        "--hidden-import",
        "kivy.core.image.img_sdl2",
        "--hidden-import",
        "kivy.core.text.text_sdl2",
        "--hidden-import",
        "kivy.core.clipboard.clipboard_sdl2",
        "--collect-data",
        "certifi",
        "--exclude-module",
        "tkinter",
        "--exclude-module",
        "pytest",
        APP / "backend/host.py",
        cwd=UPSTREAM,
    )
    RESOURCES.mkdir(parents=True, exist_ok=True)
    backend = RESOURCES / "backend"
    if backend.exists():
        shutil.rmtree(backend)
    shutil.copytree(BUILD / "frozen/katrain-host", backend, symlinks=True)
    engine = RESOURCES / "engine"
    engine.mkdir(exist_ok=True)
    bundle_macho(binary, engine / "katago", {})
    model = Path(model_value)
    destination = engine / "model.bin.gz"
    if destination.is_symlink():
        destination.unlink()
    shutil.copy2(model, destination)
    license_dir = RESOURCES / "licenses"
    license_dir.mkdir(exist_ok=True)
    shutil.copy2(UPSTREAM / "LICENSE", license_dir / "KaTrain-LICENSE.txt")
    for package in ("katago", "libzip", "zstd", "xz", "openssl@3"):
        prefix = Path("/opt/homebrew/opt") / package
        if prefix.exists():
            for license_file in prefix.glob("*LICENSE*"):
                if license_file.is_file():
                    shutil.copy2(license_file, license_dir / f"{package}-{license_file.name}")
    for name in (
        "kivy",
        "ffpyplayer",
        "pygame",
        "pysgf",
        "docutils",
        "chardet",
        "urllib3",
        "websocket-client",
        "certifi",
    ):
        distribution = importlib.metadata.distribution(name)
        for file in distribution.files or []:
            if any(word in str(file).lower() for word in ("license", "copying")):
                source = Path(distribution.locate_file(file))
                if source.is_file():
                    target = license_dir / name / str(file).replace("/", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    manifest = {
        "katrain_revision": subprocess.check_output(["git", "rev-parse", REVISION], cwd=source_repo, text=True).strip(),
        "python": sys.version,
        "model_filename": model.name,
        "model_sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
        "katago": subprocess.check_output([str(engine / "katago"), "version"], text=True).strip(),
    }
    (RESOURCES / "build-info.json").write_text(json.dumps(manifest, indent=2))
    print("Backend ready:", RESOURCES)


if __name__ == "__main__":
    main()
