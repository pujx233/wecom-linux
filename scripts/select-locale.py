#!/usr/bin/env python3
"""Select an installed UTF-8 locale for Wine and prefix configuration."""
import locale


def select_locale():
    for name in ('zh_CN.UTF-8', 'C.UTF-8'):
        try:
            locale.setlocale(locale.LC_ALL, name)
        except locale.Error:
            continue
        return name
    raise SystemExit('WeCom requires an available UTF-8 locale (zh_CN.UTF-8 or C.UTF-8).')


if __name__ == '__main__':
    print(select_locale())
