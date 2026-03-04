"""
py2app build script for Writers Room menu bar app.

Usage:
    python3 setup.py py2app          # build .app bundle
    python3 setup.py py2app --alias  # dev mode (fast, symlinks source files)

Output: dist/Writers Room.app
"""

from setuptools import setup

APP     = ["menubar_app.py"]
OPTIONS = {
    "argv_emulation": False,
    "semi_standalone": False,
    "plist": {
        # Hide Dock icon — menu bar only
        "LSUIElement": True,
        "CFBundleName": "Writers Room",
        "CFBundleDisplayName": "Writers Room",
        "CFBundleIdentifier": "com.writersroom.menubar",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "© 2025 Writers Room",
        # Allow outgoing connections (OpenAI API + AppleScript)
        "NSAppleEventsUsageDescription": (
            "Writers Room uses AppleScript to open notes in the Notes app."
        ),
    },
    # Packages that need to be bundled fully
    "packages": [
        "openai",
        "numpy",
        "bs4",
        "dotenv",
        "rumps",
        "objc",
        "AppKit",
        "Foundation",
    ],
    # Source files that are local modules
    "includes": [
        "searcher",
        "preferences",
        "search_panel",
        "utils",
    ],
    # Don't strip debug info (keeps tracebacks readable)
    "strip": False,
}

setup(
    name="Writers Room",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
