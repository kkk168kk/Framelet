"""Opt-in Windows smoke check: briefly display/capture only our own test canvas.

Run directly, NOT via unittest discovery. Never saves the surrounding desktop.
"""
import os
from pathlib import Path
import sys
import tempfile
import ctypes
from ctypes import wintypes
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from PySide6.QtCore import Qt,QRect,QPoint,QSize
from PySide6.QtGui import QPainter,QColor,QImage
from PySide6.QtWidgets import QApplication,QWidget,QSystemTrayIcon
from PySide6.QtTest import QTest
import mss

from capture_geometry import physical_region,monitor_for_screen,exclude_from_capture
from overlay import SnipOverlay
from recorder import Recorder
from widgets import FloatBar,PreviewDialog,HomeWindow
from util import export_clip
from theme import STYLE
from cursor_capture import compose_cursor


class Canvas(QWidget):
    clicks = 0

    def mousePressEvent(self,event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicks += 1
            self.update()

    def paintEvent(self,event):
        p = QPainter(self)
        p.fillRect(self.rect(),QColor('#224466'))
        p.fillRect(QRect(self.width()//2,self.height()//2,self.width()//2,self.height()//2),QColor('#00AA66'))
        p.end()


def click_test_canvas(canvas,x,y):
    """Dispatch real input only after native hit testing confirms our canvas."""
    api = ctypes.windll.user32
    api.WindowFromPoint.argtypes = [wintypes.POINT]
    api.WindowFromPoint.restype = wintypes.HWND
    assert api.WindowFromPoint(wintypes.POINT(x,y)) == int(canvas.winId()), 'Test canvas is not at click target'
    old = wintypes.POINT()
    api.GetCursorPos(ctypes.byref(old))
    try:
        api.SetCursorPos(x,y)
        api.mouse_event(0x0002,0,0,0,0)
        api.mouse_event(0x0004,0,0,0,0)
        QTest.qWait(100)
    finally:
        api.SetCursorPos(old.x,old.y)


app = QApplication([])
app.setStyle('Fusion')
app.setStyleSheet(STYLE)
app.setQuitOnLastWindowClosed(False)
screen = app.primaryScreen()
g = screen.geometry()
canvas = Canvas()
canvas.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
canvas.setGeometry(g.x()+160,g.y()+180,640,400)
overlay = bar = preview = None
try:
    canvas.show()
    canvas.raise_()
    QTest.qWait(350)
    from element_detect import ElementDetector
    detector = ElementDetector()
    probe = detector.rect_at(g.x()+300,g.y()+380)
    detector.close()
    assert probe is not None and probe[2] > probe[0] and probe[3] > probe[1]
    print('NATIVE_ELEMENT_DETECT_OK',probe)
    with mss.mss() as sct:
        monitor = monitor_for_screen(screen,sct.monitors[1:])
        shot = sct.grab(monitor)
        bg = QImage(bytes(shot.raw),shot.width,shot.height,QImage.Format.Format_RGB32).copy()
        local = QRect(canvas.pos()-g.topLeft(),canvas.size())
        region = physical_region(local,g.size(),monitor)
        old_cursor = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(old_cursor))
        try:
            cursor_x,cursor_y = region['left']+130,region['top']+120
            ctypes.windll.user32.SetCursorPos(cursor_x,cursor_y)
            QTest.qWait(80)
            no_cursor = sct.grab(region)
            plain = bytes(no_cursor.raw)
            composed = compose_cursor(plain,no_cursor.width,no_cursor.height,region)
            assert composed != plain,'Visible native cursor was not composited'
            assert sum(a != b for a,b in zip(plain,composed)) >= 20,'Cursor changed too few pixels'
            with tempfile.TemporaryDirectory(prefix='framelet-cursor-test-') as cursor_dir:
                with patch('recorder.tempfile.mkdtemp',return_value=cursor_dir):
                    cursor_worker = Recorder(region,fps=1,max_seconds=.05)
                    cursor_worker.start()
                    for _ in range(100):
                        if cursor_worker.isFinished(): break
                        QTest.qWait(20)
                    assert cursor_worker.wait(2000) and cursor_worker.saved
                    recorded = QImage(str(Path(cursor_dir)/'f_00001.png'))
                    baseline = QImage(plain,no_cursor.width,no_cursor.height,QImage.Format.Format_ARGB32)
                    local_x,local_y = cursor_x-region['left'],cursor_y-region['top']
                    changed = 0
                    for y in range(max(0,local_y-40),min(recorded.height(),local_y+70)):
                        for x in range(max(0,local_x-40),min(recorded.width(),local_x+70)):
                            changed += recorded.pixel(x,y) != baseline.pixel(x,y)
                    assert changed >= 5,'Saved recorder frame did not contain the cursor'
            print('NATIVE_CURSOR_COMPOSITE_OK')
        finally:
            ctypes.windll.user32.SetCursorPos(old_cursor.x,old_cursor.y)
        overlay = SnipOverlay(screen,monitor,bg)
        overlay.sel,overlay.state = local,'ready'
        overlay.show()
        overlay.raise_()
        QTest.qWait(250)
        captured = sct.grab(region)
        image = QImage(bytes(captured.raw),captured.width,captured.height,QImage.Format.Format_RGB32).copy()
        assert image.pixelColor(int(image.width()*.8),int(image.height()*.8)).name() == '#00aa66'
        assert image.pixelColor(int(image.width()*.2),int(image.height()*.2)).name() == '#224466'
        print('NATIVE_DPI_OK',g.getRect(),screen.devicePixelRatio(),region)
        overlay.close()
        overlay = None
        QTest.qWait(250)
        bar = FloatBar(canvas.geometry())
        bar.move(canvas.pos()+QPoint(12,12))
        bar.show()
        excluded = exclude_from_capture(bar)
        QTest.qWait(250)
        if excluded:
            captured = sct.grab(region)
            image = QImage(bytes(captured.raw),captured.width,captured.height,QImage.Format.Format_RGB32).copy()
            sx = region['width']/canvas.width()
            assert image.pixelColor(round(40*sx),round(30*sx)).name() == '#224466'
        print('CONTROL_EXCLUSION_OK',excluded)
        bar.close()
        bar = None
    QTest.qWait(150)
    with tempfile.TemporaryDirectory(prefix='framelet-native-') as directory:
        root = Path(directory)
        frames = root/'frames'
        frames.mkdir()
        with patch('recorder.tempfile.mkdtemp',return_value=str(frames)):
            worker = Recorder(region,fps=10,max_seconds=.3)
            worker.start()
            for _ in range(100):
                if worker.isFinished(): break
                QTest.qWait(30)
            assert worker.wait(3000)
            assert not worker.error,worker.error
            assert worker.saved and worker.frame_count == 3
        for kind in ('gif','mp4'):
            export_clip(frames,10,root/f'native.{kind}',1,3,kind)
        print('NATIVE_RECORD_TRIM_EXPORT_OK',worker.frame_count)
        canvas.hide()
        preview = PreviewDialog(str(frames),10)
        preview.set_range(1,3)
        preview.show()
        QTest.qWait(200)
        artifacts = Path(__file__).resolve().parent.parent/'test-artifacts'
        artifacts.mkdir(exist_ok=True)
        preview.grab().save(str(artifacts/'editor-native.png'))
        preview.exported_range = (1,3)
        preview.close()
        preview = None
        print('NATIVE_EDITOR_OK')
        # Exercise actual controller transitions without installing global hooks.
        from main import Controller
        with patch('main.GlobalHotkeys') as hotkey_type, patch('main.set_auto_start',return_value=True):
            hotkey_type.return_value.available = True
            controller = Controller(app)
            assert not controller.home.isVisible()
            assert controller.home.fps.currentData() == 24
            assert controller.home.auto_start.isChecked()
            controller._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
            assert not controller.home.isVisible()
            controller._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
            assert controller.home.isVisible()
            print('NATIVE_TRAY_DOUBLE_CLICK_AND_24_FPS_OK')
            controller.home.hide()
            controller.home.fps.setCurrentIndex(0)
            controller.home.duration.addItem('test',.3)
            controller.home.duration.setCurrentIndex(controller.home.duration.count()-1)
            canvas.show()
            canvas.raise_()
            canvas.activateWindow()
            QTest.qWait(200)
            # Background test processes cannot assume Windows grants activation.
            # Establish the same genuine user-input precondition as real usage.
            click_test_canvas(canvas,region['left']+30,region['top']+30)
            lifecycle_frames = root/'lifecycle-frames'
            lifecycle_frames.mkdir()
            with patch('recorder.tempfile.mkdtemp',return_value=str(lifecycle_frames)):
                controller.state = 'selecting'
                # This own-process canvas stands in for the user's prior app.
                controller._target_window = int(canvas.winId())
                selection = SnipOverlay(screen,monitor,bg)
                selection.sel,selection.state = local,'ready'
                selection.sigCountdownStart.connect(controller._prepare_record)
                controller.overlays = [selection]
                selection.show()
                selection.raise_()
                selection.activateWindow()
                QTest.qWait(100)
                selection.begin()
                QTest.qWait(120)
                assert controller.state == 'countdown'
                assert controller.recorder is None
                assert not controller.overlays
                controller.countdown.grab().save(str(artifacts/'countdown-native.png'))
                # Real Windows input, guarded to target only our test canvas.
                user32 = ctypes.windll.user32
                user32.GetForegroundWindow.restype = wintypes.HWND
                user32.WindowFromPoint.argtypes = [wintypes.POINT]
                user32.WindowFromPoint.restype = wintypes.HWND
                center = controller.countdown.geometry().center()-g.topLeft()
                hit = physical_region(QRect(center,QSize(1,1)),g.size(),monitor)
                point = wintypes.POINT(hit['left'],hit['top'])
                assert user32.GetForegroundWindow() == int(canvas.winId()), 'Countdown stole focus'
                assert user32.WindowFromPoint(point) == int(canvas.winId()), 'Countdown blocks native hit testing'
                before = canvas.clicks
                click_test_canvas(canvas,point.x,point.y)
                assert canvas.clicks == before+1, 'Underlying canvas did not receive click'
                assert controller.state == 'countdown'
                print('NATIVE_COUNTDOWN_REAL_CLICK_THROUGH_OK')
                for _ in range(200):
                    if controller.preview: break
                    QTest.qWait(25)
                assert controller.state == 'editing',controller.state
                assert controller.recorder is None
                assert controller.outline is None
                assert controller.preview.total == 3
            controller.preview.exported_range = (0,3)
            controller.preview.close()
            assert controller.state == 'idle'
            assert controller.preview is None
            assert not controller.home.isVisible()
            controller.quit()
            controller.home.close()
            print('NATIVE_CONTROLLER_LIFECYCLE_OK')
finally:
    if overlay: overlay.close()
    if bar: bar.close()
    if preview:
        preview.exported_range = (preview.start,preview.end)
        preview.close()
    canvas.close()
