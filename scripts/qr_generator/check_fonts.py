#!/usr/bin/env python3
"""
check_fonts.py - script to list available system fonts.

Usage:
    python check_fonts.py
"""
import sys

def list_fonts_matplotlib():
    try:
        from matplotlib.font_manager import FontManager
    except ImportError:
        return False
    fm = FontManager()
    fonts = fm.ttflist
    if not fonts:
        return False
    for font in sorted(fonts, key=lambda f: f.name):
        print(f"{font.name}\t{font.fname}")
    return True

def list_fonts_fc_list():
    import subprocess
    try:
        output = subprocess.check_output(['fc-list', ':', 'file', 'family'], universal_newlines=True)
    except (OSError, subprocess.CalledProcessError):
        return False
    for line in output.splitlines():
        parts = line.split(':', 1)
        if len(parts) == 2:
            path, family = parts
            print(f"{family.strip()}\t{path}")
        else:
            print(line)
    return True

def main():
    if list_fonts_matplotlib():
        return
    if list_fonts_fc_list():
        return
    sys.stderr.write("Error: Neither matplotlib.font_manager nor fc-list available.\n")
    sys.exit(1)

if __name__ == '__main__':
    main()