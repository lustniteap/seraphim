"""Find the DAW and plugins installed on this computer, to pre-fill the setup screen.

Installed is not licensed: trials and expired licences show up too, so the setup screen
pre-ticks what's found and the user confirms. Nothing is loaded or sent anywhere.

Mac: reads names and vendor IDs from each bundle's Info.plist.
Windows: plugins there have no such metadata, so it goes by file names and vendor folders.
It looks in the standard places for DAWs and for VST3, VST2 and AAX plugins.

Waves loads every plugin through a shared WaveShell, so a scan can only say that Waves is
installed. Which Waves plugins are owned is chosen by the user, by bundle.

The Windows folder names are from how these programs normally install and haven't been checked
on a real PC yet, so `python -m mixcheck.scan` prints what was looked at and found, for anyone
testing to send back. Linux isn't supported: there's no scan, and the user chooses by hand.
"""
import os
import plistlib
import sys
from pathlib import Path

PLATFORM = "mac" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "other"
PLATFORM_NAMES = {"mac": "Mac", "windows": "PC", "other": "computer"}
LAUNCHERS = {"mac": "Seraphim.command", "windows": "Seraphim.bat"}

# ---------------------------------------------------------------- Mac

# Bundle ID -> DAW id in catalog.DAWS. Logic and Ableton IDs are from memory and not yet
# checked on a Mac that has them installed.
DAW_BUNDLES = {
    "com.avid.ProTools": "pro_tools",
    "com.apple.logic10": "logic",
    "com.ableton.live": "ableton",
    "com.image-line.flstudio": "fl_studio",
}

PLUGIN_FOLDERS = [
    Path("/Library/Audio/Plug-Ins/Components"),
    Path("/Library/Audio/Plug-Ins/VST3"),
    Path("/Library/Application Support/Avid/Audio/Plug-Ins"),
    Path.home() / "Library/Audio/Plug-Ins/Components",
    Path.home() / "Library/Audio/Plug-Ins/VST3",
]
APP_FOLDERS = [Path("/Applications"), Path.home() / "Applications"]
PLUGIN_SUFFIXES = {".component", ".vst3", ".aaxplugin"}

# ---------------------------------------------------------------- Windows

# Windows DAWs: (daw id, display name, folders under a Program Files or ProgramData root, glob for the exe).
# FL Studio and Pro Tools install under Program Files; Ableton under ProgramData (and sometimes Program Files).
WINDOWS_DAWS = [
    ("pro_tools", "Pro Tools", ["Avid/Pro Tools"], "Pro*Tools.exe"),
    ("ableton", None, ["Ableton/Live */Program"], "Ableton Live*.exe"),
    ("fl_studio", None, ["Image-Line/FL Studio*"], "FL*.exe"),
]
WINDOWS_PLUGIN_SUFFIXES = {".vst3", ".aaxplugin"}
VST2_SUFFIX = ".dll"


def _dirs(*env_names):
    """Existing folders named by environment variables, without repeats."""
    seen, out = set(), []
    for name in env_names:
        value = os.environ.get(name)
        if value and value not in seen:
            seen.add(value)
            out.append(Path(value))
    return out


def windows_plugin_folders():
    """(folders with .vst3 and .aaxplugin, folders with VST2 .dll files)."""
    common = _dirs("CommonProgramFiles", "CommonProgramFiles(x86)", "CommonProgramW6432")
    local = _dirs("LOCALAPPDATA")
    programs = _dirs("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)")
    bundle_folders = ([c / "VST3" for c in common] + [c / "Avid" / "Audio" / "Plug-Ins" for c in common]
                      + [p / "Programs" / "Common" / "VST3" for p in local])
    vst2_folders = [p / "VSTPlugins" for p in programs] + [p / "Steinberg" / "VSTPlugins" for p in programs]
    return bundle_folders, vst2_folders


def windows_app_roots():
    return _dirs("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)", "ProgramData")


# ---------------------------------------------------------------- finding things

def _bundle_info(path):
    try:
        with open(path / "Contents" / "Info.plist", "rb") as fh:
            return plistlib.load(fh)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}


def _bundles(folders, suffixes, depth=1, files_ok=False):
    """Plugin or app bundles in folders; vendor sub-folders are searched `depth` levels down.
    A matching folder is a bundle and isn't searched further. files_ok: a matching file counts too
    (Windows VST3 and VST2 plugins can be single files)."""
    for folder in folders:
        try:
            items = sorted(folder.iterdir())
        except OSError:
            continue
        for item in items:
            if item.suffix.lower() in suffixes and (files_ok or item.is_dir()):
                yield item
            elif depth > 0 and item.is_dir():
                yield from _bundles([item], suffixes, depth - 1, files_ok)


def scan_daws():
    """Mac: DAW apps by bundle ID."""
    found = []
    for path in _bundles(APP_FOLDERS, {".app"}, depth=0):
        info = _bundle_info(path)
        daw = DAW_BUNDLES.get(info.get("CFBundleIdentifier", ""))
        if daw:
            found.append({"id": daw, "app": path.stem, "version": info.get("CFBundleShortVersionString", "")})
    return found


def scan_daws_windows(roots=None):
    """Windows: DAWs by their usual install folders and program files."""
    found = []
    for root in roots if roots is not None else windows_app_roots():
        for daw, label, patterns, exe in WINDOWS_DAWS:
            for pattern in patterns:
                for folder in sorted(root.glob(pattern)):
                    if not folder.is_dir() or not any(folder.glob(exe)):
                        continue
                    # Ableton's folder is "Live 12 Suite/Program": name it after the folder above.
                    named = folder.parent.name if folder.name == "Program" else folder.name
                    app = label or (f"Ableton {named}" if daw == "ableton" and named.startswith("Live") else named)
                    if not any(d["id"] == daw for d in found):
                        found.append({"id": daw, "app": app, "version": ""})
    return found


def _package_for(name, bundle_id="", vendor_hint=""):
    """Catalog package for one plugin, or None. Matches on vendor ID or folder plus name."""
    lowered = name.lower()
    who = f"{bundle_id} {vendor_hint}".lower()
    izotope = "izotope" in who or "izozone" in lowered or lowered.startswith("iz")
    if "insight" in lowered and izotope:
        return "izotope_insight"
    if "ozone" in lowered:
        return "izotope_ozone"
    if bundle_id.startswith("com.WavesAudio") or "waveshell" in lowered:
        return "waves"  # a marker, not a catalog package: see module docstring
    return None


def _vendor(bundle_id):
    """com.arturia.component.X -> com.arturia; jp.co.roland.X -> jp.co.roland."""
    parts = bundle_id.split(".")
    return ".".join(parts[:2] if parts[0] == "com" else parts[:3]) if bundle_id else "unknown"


def scan_plugins():
    """Mac: packages found, and the vendors of plugins that didn't match anything the catalog knows."""
    packages, unmatched, seen = {}, set(), set()
    for path in _bundles(PLUGIN_FOLDERS, PLUGIN_SUFFIXES, depth=0):
        info = _bundle_info(path)
        bundle_id = info.get("CFBundleIdentifier", "")
        name = path.stem
        if name in seen:
            continue
        seen.add(name)
        package = _package_for(name, bundle_id)
        if package:
            packages.setdefault(package, []).append(name)
        else:
            unmatched.add(_vendor(bundle_id))
    return packages, sorted({v.lower() for v in unmatched})


def scan_plugins_windows(bundle_folders=None, vst2_folders=None):
    """Windows: packages found by file name and vendor folder, and the vendor folders that didn't match."""
    if bundle_folders is None and vst2_folders is None:
        bundle_folders, vst2_folders = windows_plugin_folders()
    packages, unmatched, seen = {}, set(), set()
    roots = set(bundle_folders or []) | set(vst2_folders or [])
    found = list(_bundles(bundle_folders or [], WINDOWS_PLUGIN_SUFFIXES, depth=1, files_ok=True)) \
        + list(_bundles(vst2_folders or [], {VST2_SUFFIX}, depth=1, files_ok=True))
    for path in found:
        name = path.stem
        # A vendor sub-folder such as "iZotope" is a clue; a plugin straight in the plugin folder has none.
        hint = "" if path.parent in roots else path.parent.name
        key = (hint, name)
        if key in seen:
            continue
        seen.add(key)
        package = _package_for(name, vendor_hint=hint)
        if package:
            packages.setdefault(package, []).append(name)
        elif hint:
            unmatched.add(hint.lower())
    return packages, sorted(unmatched)


# If more than one DAW is installed, pre-select the first in this order; the user can change it.
DAW_PRIORITY = ["pro_tools", "logic", "ableton", "fl_studio"]


def scan_this_computer():
    """The result the setup screen pre-fills from."""
    if PLATFORM == "mac":
        daws = scan_daws()
        packages, others = scan_plugins()
    elif PLATFORM == "windows":
        daws = scan_daws_windows()
        packages, others = scan_plugins_windows()
    else:
        daws, packages, others = [], {}, []
    daws = sorted(daws, key=lambda d: DAW_PRIORITY.index(d["id"]) if d["id"] in DAW_PRIORITY else 99)
    waves = packages.pop("waves", None)
    return {
        "platform": PLATFORM,
        "supported": PLATFORM in ("mac", "windows"),
        "daws": daws,  # [{id, app, version}], usually one
        "packages": {pkg: {"found": names[:6], "count": len(names)} for pkg, names in packages.items()},
        "waves_installed": bool(waves),
        "waves_found": (waves or [])[:6],
        "other_vendors": others[:20],  # vendors with no fix steps yet
    }


if __name__ == "__main__":
    # For anyone testing on a PC: print what was looked at and found, to send back.
    import json
    print(f"Platform: {PLATFORM}")
    if PLATFORM == "windows":
        bundles, vst2 = windows_plugin_folders()
        print("DAW roots:", [str(p) for p in windows_app_roots()])
        print("Plugin folders:", [(str(p), p.is_dir()) for p in bundles + vst2])
    print(json.dumps(scan_this_computer(), indent=2))
