#!/usr/bin/env python3
"""Relocate the account-free template and restore missing files in an idle prefix."""
import argparse
import os
from pathlib import Path


def relocate(prefix, username):
    if not username or any(character in username for character in '/\\\n\r"'):
        raise ValueError('Invalid profile name')
    profile = prefix / 'drive_c/users/wecom'
    if username != 'wecom':
        profile.rename(profile.with_name(username))
    for name in ('user.reg', 'userdef.reg', 'system.reg'):
        path = prefix / name
        text = path.read_text()
        text = text.replace(r'C:\\users\\wecom', r'C:\\users\\' + username)
        text = text.replace(r'C:\\Users\\wecom', r'C:\\Users\\' + username)
        text = text.replace('"USERNAME"="wecom"', '"USERNAME"="' + username + '"')
        text = text.replace('"RegisteredOwner"="wecom"', '"RegisteredOwner"="' + username + '"')
        temporary = path.with_suffix('.new')
        temporary.write_text(text)
        os.replace(temporary, path)


def restore_missing(source, target, skip=()):
    for entry in source.iterdir():
        if entry.name in skip:
            continue
        path = target / entry.name
        if entry.is_dir() and not entry.is_symlink():
            if path.is_symlink():
                continue
            path.mkdir(mode=entry.stat().st_mode & 0o777, exist_ok=True)
            restore_missing(entry, path)
        else:
            try:
                # Link the complete staged file without overwriting an existing file or following a symlink.
                os.link(entry, path, follow_symlinks=False)
            except FileExistsError:
                continue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prefix', type=Path)
    parser.add_argument('username')
    parser.add_argument('--restore-to', type=Path, help='Restore an existing prefix from the relocated staging tree')
    args = parser.parse_args()
    relocate(args.prefix, args.username)
    if args.restore_to:
        restore_missing(args.prefix, args.restore_to, ('system.reg', '.wecom-application', '.wecom-display-fonts.json'))
        # The launcher treats system.reg as the completion marker.
        os.link(args.prefix / 'system.reg', args.restore_to / 'system.reg')


if __name__ == '__main__':
    main()
