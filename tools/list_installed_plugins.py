"""List the audio plugins installed on this computer, to seed Seraphim's plugin list.

A one-off tool for the person building the list. It is not part of the app and it is not run by it.

    python3 tools/list_installed_plugins.py > my-plugins.json

It looks in the standard plugin folders, reads each plugin's name, vendor, format and version, and prints them as JSON.
It prints no file paths and no user names, reads nothing else, and sends nothing anywhere. Send the JSON to whoever
is building the list: it says what is installed, not what is licensed, so check it before relying on it.

Mac: reads each bundle's Info.plist. Windows: plugins there carry no such metadata, so it goes by file names and the
vendor folder they sit in. The Windows folder names are from how these programs normally install and haven't been
checked on a real PC, so the output also says which folders it looked in.
"""
import argparse
import json
import os
import plistlib
import sys
from pathlib import Path

MAC_SUFFIXES = {".component": "AU", ".vst3": "VST3", ".aaxplugin": "AAX", ".vst": "VST2"}
WINDOWS_SUFFIXES = {".vst3": "VST3", ".aaxplugin": "AAX", ".dll": "VST2"}


def mac_folders():
    system = [Path("/Library/Audio/Plug-Ins") / n for n in ("Components", "VST3", "VST")]
    system.append(Path("/Library/Application Support/Avid/Audio/Plug-Ins"))
    user = [Path.home() / "Library/Audio/Plug-Ins" / n for n in ("Components", "VST3", "VST")]
    return system + user


def windows_folders():
    roots = [Path(os.environ[k]) for k in ("ProgramFiles", "ProgramFiles(x86)", "CommonProgramFiles",
                                           "CommonProgramFiles(x86)") if os.environ.get(k)]
    out = []
    for root in roots:
        for rel in ("VST3", "Avid/Audio/Plug-Ins", "VSTPlugins", "Steinberg/VSTPlugins", "VST2"):
            out.append(root / rel)
            out.append(root / "Common Files" / rel)
    return out


def _vendor_from_id(bundle_id):
    parts = (bundle_id or "").split(".")
    return parts[1] if len(parts) > 2 and parts[0] in ("com", "net", "org", "io", "de", "uk") else None


def _mac_entry(path, fmt):
    info = {}
    try:
        with open(path / "Contents" / "Info.plist", "rb") as fh:
            info = plistlib.load(fh)
    except (OSError, plistlib.InvalidFileException, ValueError):
        pass  # a broken or missing plist still has a name: the file's
    return {"name": str(info.get("CFBundleName") or path.stem), "vendor": _vendor_from_id(info.get("CFBundleIdentifier")),
            "format": fmt, "version": info.get("CFBundleShortVersionString")}


def _walk(folder, suffixes, entry, vendor_folders):
    """Plugins directly in `folder`, and (for Windows) one level down, where vendors keep theirs."""
    found = []
    try:
        items = sorted(folder.iterdir())
    except OSError:
        return found
    for item in items:
        fmt = suffixes.get(item.suffix.lower())
        if fmt:
            found.append(entry(item, fmt, None))
        elif vendor_folders and item.is_dir():
            try:
                for sub in sorted(item.iterdir()):
                    sfmt = suffixes.get(sub.suffix.lower())
                    if sfmt:
                        found.append(entry(sub, sfmt, item.name))
            except OSError:
                pass
    return found


def list_plugins(platform=None, folders=None):
    """{platform, folders, count, plugins}: every plugin found, de-duplicated by name and format."""
    platform = platform or ("mac" if sys.platform == "darwin" else "windows" if sys.platform == "win32" else "other")
    if platform == "mac":
        folders = folders if folders is not None else mac_folders()
        found = [e for f in folders for e in _walk(f, MAC_SUFFIXES, lambda p, fmt, _v: _mac_entry(p, fmt), False)]
    elif platform == "windows":
        folders = folders if folders is not None else windows_folders()
        entry = lambda p, fmt, v: {"name": p.stem, "vendor": v, "format": fmt, "version": None}
        found = [e for f in folders for e in _walk(f, WINDOWS_SUFFIXES, entry, True)]
    else:
        folders, found = folders or [], []
    unique = {(e["name"].lower(), e["format"]): e for e in found}
    plugins = sorted(unique.values(), key=lambda e: (e["name"].lower(), e["format"]))
    # Say which folders were found, by their last two parts ("Plug-Ins/VST3"), so no user name or full path leaks.
    looked = sorted({"/".join(Path(f).parts[-2:]) for f in folders if Path(f).is_dir()})
    return {"platform": platform, "folders_found": looked, "count": len(plugins), "plugins": plugins}


def main(argv=None):
    parser = argparse.ArgumentParser(description="List installed audio plugins as JSON (names only, no paths).")
    parser.add_argument("--out", help="Write to this file instead of the screen")
    args = parser.parse_args(argv)
    text = json.dumps(list_plugins(), indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Wrote {args.out}")
    else:
        print(text)


if __name__ == "__main__":
    main()
