"""Framelet — select a region, record, trim and export. No screenshots."""
import logging
import os
from pathlib import Path
import shutil
import sys
import tempfile

from PySide6.QtCore import QObject, Signal, QTimer, Qt, QLockFile, QSettings
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QGuiApplication, QImage, QCursor
from PySide6.QtWidgets import QApplication,QSystemTrayIcon,QMessageBox

from capture_geometry import (monitor_for_screen,exclude_from_capture,
                              external_foreground_window,restore_foreground_window)
from lucide_icons import lucide_icon
from popup_menu import PopupMenu
from theme import ACCENT_TEXT, MUTED, STYLE
from widgets import (HomeWindow,FloatBar,PreviewDialog,RecordingOutline,
                     RecordingMask,CountdownOverlay)
from hotkeys import GlobalHotkeys

HOTKEY = 'F6'
PAUSE_HOTKEY = 'Ctrl+Shift+P'
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
# Qt 6 uses per-monitor DPI awareness. Do NOT disable DPI scaling.

RUN_KEY = r'Software\Microsoft\Windows\CurrentVersion\Run'


def autostart_command():
    """Launch command for the Windows Run key: packaged exe, or pythonw + main.py."""
    if getattr(sys,'frozen',False):
        return f'"{sys.executable}"'
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return f'"{exe}" "{Path(__file__).resolve()}"'


def set_auto_start(enabled):
    """Add or remove Framelet from per-user Windows autostart. Returns success."""
    if sys.platform != 'win32': return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,RUN_KEY,0,winreg.KEY_SET_VALUE) as key:
            if enabled:
                winreg.SetValueEx(key,'Framelet',0,winreg.REG_SZ,autostart_command())
            else:
                try: winreg.DeleteValue(key,'Framelet')
                except FileNotFoundError: pass
        return True
    except OSError:
        return False


def make_tray_icon():
    base = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
    icon = QIcon(str(base/'Framelet.png'))
    if not icon.isNull():
        return icon
    # Keep a functional fallback for an incomplete source checkout.
    pm = QPixmap(64,64)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor('#C93430'))
    p.drawRoundedRect(6,6,52,52,12,12)
    p.setBrush(QColor('white'))
    p.drawRoundedRect(22,22,20,20,4,4)
    p.end()
    return QIcon(pm)


class HotkeyBridge(QObject):
    record = Signal()
    pause = Signal()
    cancel = Signal()


class Controller(QObject):
    def __init__(self,app,lock=None):
        super().__init__()
        self.app,self.lock = app,lock
        self.overlays = []
        self.detector = None
        self.recorder,self.floatbar,self.preview = None,None,None
        self.outline,self.recording_mask = None,None
        self.countdown = None
        self.countdown_outline,self.countdown_mask = None,None
        self._target_window = None
        self._pending_record = None
        self._countdown_remaining = 3
        self._countdown_timer = QTimer(self)
        self._countdown_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._countdown_timer.setInterval(1000)
        self._countdown_timer.timeout.connect(self._countdown_tick)
        self.state,self.temp_dir = 'idle',None
        self.settings = QSettings('Framelet','Framelet')
        self.home = HomeWindow()
        self.home.sigStart.connect(self.start_snip)
        self.home.sigRecordShortcut.connect(self._save_shortcut)
        self.home.sigAutoStart.connect(self._save_auto_start)
        auto_start = self.settings.value('autoStart',True,type=bool)
        self.home.set_auto_start(auto_start)
        if not set_auto_start(auto_start):
            self.home.status.setText('无法写入开机自启动设置，请检查注册表权限。')
        self.tray = QSystemTrayIcon(make_tray_icon(),app)
        self.tray.setToolTip(f'Framelet · 双击打开设置 · {HOTKEY} 录屏')
        self.menu = PopupMenu()
        self.menu.setMinimumWidth(172+self.menu.SHADOW.left()+self.menu.SHADOW.right())
        self.menu.addAction(lucide_icon('scan',ACCENT_TEXT,16),'选择区域录制',self.hotkey_record)
        self.menu.addSeparator()
        self.menu.addAction(lucide_icon('power',MUTED,16),'退出 Framelet',self.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        if self.tray_available: self.tray.show()
        else:
            app.setQuitOnLastWindowClosed(True)
            self.home.status.setText('系统托盘不可用，请保持主窗口打开。')
        self.bridge = HotkeyBridge()
        self.bridge.record.connect(self.hotkey_record)
        self.bridge.pause.connect(self.toggle_pause)
        self.bridge.cancel.connect(self.cancel_countdown)
        self.hotkeys = GlobalHotkeys(self)
        record_key = str(self.settings.value('recordShortcut',HOTKEY))
        try:
            self.hotkeys.set_shortcuts(record_key,PAUSE_HOTKEY)
        except ValueError:
            record_key = HOTKEY
            self.hotkeys.set_shortcuts(record_key,PAUSE_HOTKEY)
        self.home.set_shortcut(record_key,PAUSE_HOTKEY)
        self.tray.setToolTip(f'Framelet · 双击打开设置 · {record_key} 录屏')
        self.hotkeys.record.connect(self.bridge.record.emit)
        self.hotkeys.pause.connect(self.bridge.pause.emit)
        self.hotkeys.escape.connect(self.bridge.cancel.emit)
        if not self.hotkeys.available:
            self.home.status.setText('全局快捷键不可用，请使用主窗口或托盘操作。')
        app.screenRemoved.connect(self._screens_changed)
        # Stay quiet on launch. Only expose a fallback if the OS has no tray.
        if not self.tray_available: self.home.show()

    def _tray_activated(self,reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick: self.show_home()

    def _return_to_idle(self):
        self.state = 'idle'
        self.home.hide()
        if not self.tray_available: self.home.show()

    def show_home(self):
        if self.preview:
            if self.preview.isMinimized():
                self.preview.setWindowState(self.preview.windowState() & ~Qt.WindowState.WindowMinimized)
            self.preview.show()
            self.preview.raise_()
            self.preview.activateWindow()
        elif self.state == 'recording':
            self.tray.showMessage('Framelet',f'录制中：{self.hotkeys.record_shortcut} 完成，{self.hotkeys.pause_shortcut} 暂停 / 继续。')
        elif self.state == 'idle':
            self._remember_target_window()
            self.home.showNormal()
            self.home.raise_()
            self.home.activateWindow()

    def hotkey_record(self):
        if self.home.isVisible() and self.home.shortcut_editing(): return
        if self.state == 'recording': self.stop_recording()
        elif self.state in ('countdown','starting'): self.cancel_countdown()
        elif self.state == 'idle': self.start_snip()
        elif self.preview: self.show_home()

    def toggle_pause(self):
        if self.home.isVisible() and self.home.shortcut_editing(): return
        if self.state == 'recording' and self.floatbar: self.floatbar.toggle_pause()

    def _save_shortcut(self,record):
        try:
            self.hotkeys.set_shortcuts(record,PAUSE_HOTKEY)
        except ValueError as exc:
            self.home.set_shortcut(self.hotkeys.record_shortcut,PAUSE_HOTKEY)
            self.home.shortcut_feedback.setText('未保存：'+str(exc))
            return
        self.settings.setValue('recordShortcut',self.hotkeys.record_shortcut)
        self.settings.sync()
        self.home.set_shortcut(self.hotkeys.record_shortcut,PAUSE_HOTKEY)
        self.home.shortcut_feedback.setText('快捷键已保存并立即生效。')
        self.tray.setToolTip(f'Framelet · 双击打开设置 · {self.hotkeys.record_shortcut} 录屏')

    def _save_auto_start(self,enabled):
        if set_auto_start(enabled):
            self.settings.setValue('autoStart',enabled)
            self.settings.sync()
            if enabled:
                self.home.shortcut_feedback.clear()
            else:
                self.home.shortcut_feedback.setText('开机自动启动已关闭。')
        else:
            self.home.set_auto_start(not enabled)
            self.home.shortcut_feedback.setText('无法写入开机自启动设置，请检查注册表权限。')

    def start_snip(self):
        if self.state != 'idle':
            if self.preview: self.show_home()
            return
        self._remember_target_window()
        self.state = 'preparing'
        self.home.hide()
        # Allow the compositor to remove our launcher before taking backgrounds.
        QTimer.singleShot(220,self._show_selection)

    def _remember_target_window(self):
        target = external_foreground_window()
        if target is not None: self._target_window = target

    def _show_selection(self):
        if self.state != 'preparing':
            return
        try:
            import mss
            from overlay import SnipOverlay
            try:
                from element_detect import DetectThread
                self.detector = DetectThread(self)
                self.detector.start()
            except Exception:
                self.detector = None
            # Match Qt screens to native monitors. Screenshots only feed the
            # pixel magnifier; the selection itself stays live and transparent.
            with mss.mss() as sct:
                monitors = sct.monitors[1:]
                for screen in self.app.screens():
                    monitor = monitor_for_screen(screen, monitors)
                    shot = sct.grab(monitor)
                    background = QImage(bytes(shot.raw),shot.width,shot.height,
                                        QImage.Format.Format_ARGB32).copy()
                    overlay = SnipOverlay(screen, monitor, background, self.detector)
                    overlay.sigAbort.connect(self.abort_selection)
                    overlay.sigSelected.connect(self._select_monitor)
                    overlay.sigCountdownStart.connect(self._prepare_record)
                    self.overlays.append(overlay)
            active = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            for overlay in self.overlays:
                overlay.show()
                exclude_from_capture(overlay)
                if overlay.screen_info == active:
                    overlay.raise_()
                    overlay.activateWindow()
            self.state = 'selecting'
        except Exception as exc:
            logging.exception('Selection failed')
            self.abort_selection()
            QMessageBox.warning(self.home, '无法选择区域', str(exc))
    def _select_monitor(self,selected):
        for overlay in self.overlays:
            if overlay is not selected: overlay.reset()

    def _close_overlays(self):
        for overlay in self.overlays:
            overlay.close()
            overlay.deleteLater()
        self.overlays.clear()
        if self.detector:
            self.detector.stop()
            self.detector.deleteLater()
            self.detector = None

    def abort_selection(self):
        self._clear_countdown()
        self._close_overlays()
        self._return_to_idle()

    def _prepare_record(self,region,rect):
        if self.state != 'selecting': return
        self.state = 'countdown'
        self._pending_record = (dict(region),rect)
        self._countdown_remaining = 3
        self.countdown_mask = RecordingMask(rect)
        self.countdown_mask.show()
        self.countdown_outline = RecordingOutline(rect)
        self.countdown_outline.show()
        restore_foreground_window(self._target_window)
        self._close_overlays()
        self.countdown = CountdownOverlay(rect,self.hotkeys.record_shortcut)
        self.countdown.show()
        self._countdown_timer.start()

    def _clear_countdown(self,keep_selection_visuals=False):
        self._countdown_timer.stop()
        if self.countdown:
            self.countdown.close()
            self.countdown.deleteLater()
            self.countdown = None
        if self.countdown_outline and not keep_selection_visuals:
            self.countdown_outline.close()
            self.countdown_outline.deleteLater()
            self.countdown_outline = None
        if self.countdown_mask and not keep_selection_visuals:
            self.countdown_mask.close()
            self.countdown_mask = None
        self._pending_record = None

    def cancel_countdown(self):
        if self.state in ('countdown','starting'):
            self._clear_countdown()
            self._return_to_idle()

    def _countdown_tick(self):
        if self.state != 'countdown': return
        self._countdown_remaining -= 1
        if self._countdown_remaining > 0:
            self.countdown.set_remaining(self._countdown_remaining)
            return
        pending = self._pending_record
        self._clear_countdown(keep_selection_visuals=True)
        self.state = 'starting'
        self._pending_record = pending
        # Let the compositor remove the countdown before collecting frame one.
        QTimer.singleShot(220,lambda:self._finish_countdown(pending))

    def _finish_countdown(self,pending):
        if self.state == 'starting' and self._pending_record is pending:
            self._pending_record = None
            self._start_record(*pending)

    def _start_record(self,region,rect):
        if self.state != 'starting': return
        try:
            from recorder import Recorder
            self.recorder = Recorder(region,self.home.fps.currentData(),self.home.duration.currentData(),self)
            self.floatbar = FloatBar(rect,self.recorder.max_seconds)
            self.floatbar.btn_stop.setToolTip(f'停止并进入裁剪 · {self.hotkeys.record_shortcut}')
            self.floatbar.btn_pause.setToolTip(f'暂停 / 继续 · {self.hotkeys.pause_shortcut}')
            self.floatbar.sigPause.connect(self.recorder.set_paused)
            self.floatbar.sigStop.connect(self.stop_recording)
            self.floatbar.sigCancel.connect(lambda:self.stop_recording(False))
            self.recorder.sigElapsed.connect(self.floatbar.set_elapsed)
            self.recorder.finished.connect(self._record_finished)
            self.floatbar.show()
            excluded = exclude_from_capture(self.floatbar)
            self.floatbar.allow_drag = excluded
            if not excluded and self.floatbar.geometry().intersects(rect):
                self.floatbar.hide()
                if not self.hotkeys.available and not self.tray.isVisible():
                    raise RuntimeError('无法提供录制停止入口，请选择较小区域。')
                self.tray.showMessage('Framelet',f'控制条已隐藏以避免录入画面。{self.hotkeys.record_shortcut} 完成录制；也可使用托盘。')
            self.outline,self.countdown_outline = self.countdown_outline,None
            if not self.outline:
                self.outline = RecordingOutline(rect)
                self.outline.show()
            exclude_from_capture(self.outline)
            self.recording_mask,self.countdown_mask = self.countdown_mask,None
            if not self.recording_mask:
                self.recording_mask = RecordingMask(rect)
                self.recording_mask.show()
            self.state = 'recording'
            self.recorder.start()
        except Exception as exc:
            if self.outline:
                self.outline.close()
                self.outline.deleteLater()
                self.outline = None
            if self.recording_mask:
                self.recording_mask.close()
                self.recording_mask = None
            if self.floatbar:
                self.floatbar.close()
                self.floatbar.deleteLater()
                self.floatbar = None
            if self.recorder:
                self.recorder.deleteLater()
                self.recorder = None
            self._return_to_idle()
            QMessageBox.warning(self.home,'无法开始录制',str(exc))

    def stop_recording(self,save=True):
        if self.recorder and self.state == 'recording':
            self.state = 'stopping'
            self.floatbar.set_stopping()
            self.recorder.stop(save)

    def _record_finished(self):
        recorder,self.recorder = self.recorder,None
        if self.outline:
            self.outline.close()
            self.outline.deleteLater()
            self.outline = None
        if self.recording_mask:
            self.recording_mask.close()
            self.recording_mask = None
        if self.floatbar:
            self.floatbar.close()
            self.floatbar.deleteLater()
            self.floatbar = None
        self.temp_dir = recorder.frames_dir
        error = recorder.error
        if recorder.saved:
            try:
                self.preview = PreviewDialog(recorder.frames_dir,recorder.fps)
                self.preview.finished.connect(self._preview_finished)
                self.state = 'editing'
                self.preview.show()
                self.preview.raise_()
                self.preview.activateWindow()
            except Exception as exc:
                # Preserve source frames if editor construction fails.
                error = f'{exc}\n录制帧已保留在：{recorder.frames_dir}'
                self.temp_dir = None
                self._return_to_idle()
        else:
            self._cleanup_temp()
            self._return_to_idle()
        if error:
            QMessageBox.warning(self.preview or self.home,'录制提示',error)
        recorder.deleteLater()

    def _cleanup_temp(self):
        if self.temp_dir:
            path = Path(self.temp_dir).resolve()
            # Only delete a completed recording's exact, owned temporary directory.
            if path.parent == Path(tempfile.gettempdir()).resolve() and path.name.startswith('framelet-recording-'):
                shutil.rmtree(path,ignore_errors=True)
            self.temp_dir = None

    def _preview_finished(self):
        self.preview.deleteLater()
        self.preview = None
        self._cleanup_temp()
        self._return_to_idle()

    def _screens_changed(self,*args):
        if self.state in ('preparing','selecting','countdown','starting'):
            self.abort_selection()
            self.home.status.setText('显示器配置发生变化，请重新选择录制区域。')
        elif self.state == 'recording':
            self.stop_recording()

    def quit(self):
        if self.recorder:
            if QMessageBox.question(self.floatbar,'结束录制？','先结束录制并打开裁剪窗口，以免丢失内容。') == QMessageBox.StandardButton.Yes:
                self.stop_recording()
            return
        if self.preview and not self.preview.close(): return
        self.state = 'quitting'
        self._clear_countdown()
        self._close_overlays()
        self.hotkeys.stop()
        self.tray.hide()
        if self.lock: self.lock.unlock()
        self.app.quit()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('Framelet')
    app.setOrganizationName('Framelet')
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    app.setWindowIcon(make_tray_icon())
    app.setQuitOnLastWindowClosed(False)
    # Retain old lock name to avoid simultaneous capture with a previous version.
    lock = QLockFile(os.path.join(tempfile.gettempdir(),'RegionScreenRecorder.lock'))
    if not lock.tryLock(100):
        QMessageBox.information(None,'Framelet 已运行','请通过系统托盘打开。若旧版本还在运行，请先退出旧版本再启动。')
        return 0
    controller = Controller(app,lock)
    return app.exec()


if __name__ == '__main__':
    logging.basicConfig(filename=Path(__file__).with_name('framelet.log'),level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s',encoding='utf-8')
    try:
        sys.exit(main())
    except Exception:
        logging.exception('Framelet startup failed')
        raise
