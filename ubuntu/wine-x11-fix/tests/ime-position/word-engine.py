#!/usr/bin/env python3
"""Register a deterministic input engine with the current private test daemon."""
import threading
import gi

gi.require_version('IBus', '1.0')
from gi.repository import GLib, IBus


class WordEngine(IBus.Engine):
    """Deterministic words; the real daemon and XIM frontend deliver the callbacks."""
    __gtype_name__ = 'WeComContinuousEngine'

    def __init__(self, *arguments, **keywords):
        super().__init__(*arguments, **keywords)
        self.word = ''

    def do_process_key_event(self, keyval, keycode, state):
        if state & IBus.ModifierType.RELEASE_MASK: return False
        if keyval == ord(' ') and self.word:
            self.commit_text(IBus.Text.new_from_string(
                {'ceshi': '测试', 'wenjian': '文件', 'zhongwen': '中文'}.get(self.word, self.word)))
            self.word = ''
            self.hide_preedit_text()
            return True
        if ord('a') <= keyval <= ord('z'):
            self.word += chr(keyval)
            self.update_preedit_text(IBus.Text.new_from_string(self.word), len(self.word), True)
            return True
        return False

    def do_reset(self):
        self.word = ''
        self.hide_preedit_text()


IBus.init()
bus = IBus.Bus.new()
assert bus.is_connected(), 'Private fixture engine could not connect'
factory = IBus.Factory.new(bus.get_connection())
factory.add_engine('wecom-continuous', WordEngine)
component = IBus.Component.new('org.freedesktop.IBus.WeComContinuous', 'Continuous input fixture',
                               '1', 'MIT', 'WeCom QA', '', '', '')
component.add_engine(IBus.EngineDesc.new('wecom-continuous', 'WeCom QA', 'Fixture',
                                        'zh_CN', 'MIT', 'WeCom QA', '', 'us'))
assert bus.register_component(component)
loop = GLib.MainLoop()

worker = threading.Thread(target=loop.run, daemon=True)
worker.start()
assert bus.set_global_engine('wecom-continuous')
print('ready', flush=True)
worker.join()
