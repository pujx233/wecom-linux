#!/usr/bin/env python3
"""Relocate the account-free template to the current Linux user's Wine profile."""
import os
from pathlib import Path
import sys

prefix = Path(sys.argv[1])
username = sys.argv[2]
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
