"""Find the DAW and plugins installed on this computer, to pre-fill the setup screen.

Installed is not licensed: trials and expired licences show up too, so the setup screen
pre-ticks what's found and the user confirms. Only bundle metadata is read (names and
vendor IDs from Info.plist). No plugin is loaded and nothing leaves the computer.

Waves loads every plugin through a shared WaveShell, so a scan can only say that Waves is
installed. Which Waves plugins are owned is chosen by the user, by bundle tier.

Mac only for now. Windows plugins are DLLs without bundle metadata, so they need their own reader.
"""
import plistlib
from pathlib import Path

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


def _bundle_info(path):
    try:
        with open(path / "Contents" / "Info.plist", "rb") as fh:
            return plistlib.load(fh)
    except (OSError, plistlib.InvalidFileException, ValueError):
        return {}


def _bundles(folders, suffixes):
    for folder in folders:
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            if item.suffix.lower() in suffixes and item.is_dir():
                yield item


def scan_daws():
    found = []
    for path in _bundles(APP_FOLDERS, {".app"}):
        info = _bundle_info(path)
        daw = DAW_BUNDLES.get(info.get("CFBundleIdentifier", ""))
        if daw:
            found.append({"id": daw, "app": path.stem, "version": info.get("CFBundleShortVersionString", "")})
    return found


def _package_for(name, bundle_id):
    """Catalog package for one plugin bundle, or None. Matches on vendor ID plus name."""
    lowered = name.lower()
    if bundle_id.startswith("com.izotope") or "izozone" in lowered or "ozone" in lowered:
        if "insight" in lowered:
            return "izotope_insight"
        if "ozone" in lowered or "izozone" in lowered:
            return "izotope_ozone"
    if bundle_id.startswith("com.WavesAudio"):
        return "waves"  # a marker, not a catalog package: see module docstring
    return None


def _vendor(bundle_id):
    """com.arturia.component.X -> com.arturia; jp.co.roland.X -> jp.co.roland."""
    parts = bundle_id.split(".")
    return ".".join(parts[:2] if parts[0] == "com" else parts[:3]) if bundle_id else "unknown"


def scan_plugins():
    """Packages found, and the plugins that didn't match anything the catalog knows."""
    packages, unmatched, seen = {}, set(), set()
    for path in _bundles(PLUGIN_FOLDERS, PLUGIN_SUFFIXES):
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


# If more than one DAW is installed, pre-select the first in this order; the user can change it.
DAW_PRIORITY = ["pro_tools", "logic", "ableton", "fl_studio"]


def scan_this_computer():
    """The result the setup screen pre-fills from."""
    daws = sorted(scan_daws(), key=lambda d: DAW_PRIORITY.index(d["id"]) if d["id"] in DAW_PRIORITY else 99)
    packages, unmatched_vendors = scan_plugins()
    waves = packages.pop("waves", None)
    return {
        "daws": daws,  # [{id, app, version}], usually one
        "packages": {pkg: {"found": names[:6], "count": len(names)} for pkg, names in packages.items()},
        "waves_installed": bool(waves),
        "waves_found": (waves or [])[:6],
        "other_vendors": unmatched_vendors[:20],  # vendors with no fix steps yet
    }
