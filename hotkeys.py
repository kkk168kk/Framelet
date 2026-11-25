"""Reliable, non-suppressing Windows shortcut polling for Framelet."""
import ctypes
import sys

from PySide6.QtCore import QObject, QTimer, Signal


MODIFIERS = {'Ctrl':0x11,'Shift':0x10,'Alt':0x12,'Win':0x5B}


def parse_shortcut(text):
    parts = [part.strip() for part in str(text).split('+') if part.strip()]
    aliases = {'control':'Ctrl','ctrl':'Ctrl','shift':'Shift','alt':'Alt',
               'meta':'Win','win':'Win','windows':'Win'}
    modifiers,key = [],None
    function_key = False
    for part in parts:
        canonical = aliases.get(part.lower())
        if canonical:
            if canonical not in modifiers: modifiers.append(canonical)
            continue
        token = part.upper()
        if len(token) == 1 and token.isascii() and token.isalnum(): vk = ord(token)
        elif token.startswith('F') and token[1:].isdigit() and 1 <= int(token[1:]) <= 12:
            vk = 0x70+int(token[1:])-1
            function_key = True
        else: raise ValueError('快捷键仅支持字母、数字或 F1–F12。')
        if key is not None: raise ValueError('每个快捷键只能包含一个主按键。')
        key = (token,vk)
    if key is None:
        raise ValueError('请按下一个快捷键。')
    if not modifiers and not function_key:
        raise ValueError('不带组合键时仅支持 F1–F12。')
    order = [name for name in ('Ctrl','Shift','Alt','Win') if name in modifiers]
    return tuple(MODIFIERS[name] for name in order),key[1],'+'.join(order+[key[0]])


class GlobalHotkeys(QObject):
    """Observe Ctrl+Shift+R/P and Escape without installing a fragile hook."""
    record = Signal()
    pause = Signal()
    escape = Signal()

    VK_CONTROL = 0x11
    VK_SHIFT = 0x10
    VK_ESCAPE = 0x1B
    VK_P = 0x50
    VK_R = 0x52

    def __init__(self,parent=None,key_state=None):
        super().__init__(parent)
        self.available = False
        self._latched = {'record':False,'pause':False,'escape':False}
        self.set_shortcuts('Ctrl+Shift+R','Ctrl+Shift+P')
        self._key_state = key_state
        if self._key_state is None and sys.platform == 'win32':
            try:
                get_state = ctypes.windll.user32.GetAsyncKeyState
                get_state.argtypes = [ctypes.c_int]
                get_state.restype = ctypes.c_short
                self._key_state = lambda key: bool(get_state(key) & 0x8000)
            except Exception:
                self._key_state = None
        self.timer = QTimer(self)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self.poll)
        self.available = self._key_state is not None
        if self.available: self.timer.start()

    def _edge(self,name,active,signal):
        if active and not self._latched[name]: signal.emit()
        self._latched[name] = active

    def set_shortcuts(self,record,pause):
        record_binding = parse_shortcut(record)
        pause_binding = parse_shortcut(pause)
        if record_binding[:2] == pause_binding[:2]:
            raise ValueError('开始录制和暂停快捷键不能相同。')
        self.record_binding,self.pause_binding = record_binding,pause_binding
        self.record_shortcut,self.pause_shortcut = record_binding[2],pause_binding[2]
        for name in self._latched: self._latched[name] = False

    def _active(self,binding):
        modifiers,key,_ = binding
        return all(self._key_state(vk) for vk in modifiers) and self._key_state(key)

    def poll(self):
        if not self._key_state: return
        try:
            self._edge('record',self._active(self.record_binding),self.record)
            self._edge('pause',self._active(self.pause_binding),self.pause)
            self._edge('escape',self._key_state(self.VK_ESCAPE),self.escape)
        except Exception:
            # Keep the timer alive: a transient desktop/session switch can make a
            # single Win32 query fail, but the next poll normally succeeds.
            return

    def stop(self):
        self.timer.stop()
        for name in self._latched: self._latched[name] = False
