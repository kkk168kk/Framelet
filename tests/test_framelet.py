import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from pathlib import Path
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt,QRect,QSize,QPoint
from PySide6.QtGui import QImage,QColor,QFontDatabase,QFont,QKeySequence
from PySide6.QtWidgets import (QApplication,QMessageBox,QDoubleSpinBox,QPushButton,
                               QSystemTrayIcon,QKeySequenceEdit)
from PySide6.QtTest import QTest
import imageio_ffmpeg

from capture_geometry import physical_region,monitor_for_screen
from overlay import SnipOverlay
from widgets import PreviewDialog,HomeWindow,FloatBar,RecordingMask
from hotkeys import GlobalHotkeys,parse_shortcut
from theme import STYLE
from util import export_clip,ExportWorker
from recorder import Recorder
from cursor_capture import scaled_cursor_geometry
from icon_builder import make_ico

APP = QApplication.instance() or QApplication([])
for font in ('msyh.ttc','msyhbd.ttc','segoeui.ttf'):
    path = Path('C:/Windows/Fonts')/font
    if path.exists(): QFontDatabase.addApplicationFont(str(path))
APP.setFont(QFont('Microsoft YaHei UI',10))
APP.setStyle('Fusion')
APP.setStyleSheet(STYLE)


class FakeScreen:
    def geometry(self): return QRect(0,0,2048,1152)
    def name(self): return '125% monitor'


def synthetic_frames(directory,count=12,width=160,height=90):
    for i in range(count):
        img = QImage(width,height,QImage.Format.Format_RGB32)
        img.fill(QColor(i*17%255,80,200-i*9))
        assert img.save(str(Path(directory)/f'f_{i+1:05d}.png'))


class GeometryTests(unittest.TestCase):
    def test_custom_app_icon_and_windows_ico(self):
        from main import make_tray_icon
        self.assertFalse(make_tray_icon().isNull())
        with tempfile.TemporaryDirectory(prefix='framelet-icon-test-') as directory:
            output = Path(directory)/'Framelet.ico'
            make_ico(Path(__file__).resolve().parent.parent/'Framelet.png',output)
            data = output.read_bytes()
            self.assertEqual(data[:6],b'\x00\x00\x01\x00\x01\x00')
            self.assertGreater(len(data),1000)

    def test_full_screen_125(self):
        m = dict(left=0,top=0,width=2560,height=1440)
        self.assertEqual(physical_region(QRect(0,0,2048,1152),QSize(2048,1152),m),m)

    def test_negative_monitor_origin_not_scaled(self):
        m = dict(left=-2560,top=-200,width=2560,height=1440)
        self.assertEqual(physical_region(QRect(100,80,800,400),QSize(2048,1152),m),
                         dict(left=-2435,top=-100,width=1000,height=500))

    def test_fractional_dpi_edges(self):
        for scale in (1,1.25,1.5,1.75,2):
            width,height = int(1600*scale),int(900*scale)
            m = dict(left=1600,top=0,width=width,height=height)
            self.assertEqual(physical_region(QRect(0,0,1600,900),QSize(1600,900),m),m)

    def test_unknown_monitor_is_not_silently_recorded(self):
        with self.assertRaises(RuntimeError): monitor_for_screen(FakeScreen(),[])


class OverlayTests(unittest.TestCase):
    def setUp(self):
        img = QImage(2560,1440,QImage.Format.Format_RGB32)
        img.fill(QColor('#234567'))
        # A marker at the far lower-right used to disappear in the old UI.
        from PySide6.QtGui import QPainter
        p = QPainter(img)
        p.fillRect(QRect(2200,1200,360,240),QColor('#00AA66'))
        p.end()
        self.w = SnipOverlay(FakeScreen(),dict(left=0,top=0,width=2560,height=1440))

    def tearDown(self): self.w.close()

    def test_selection_window_is_transparent_to_keep_desktop_live(self):
        self.w.sel = QRect(0,0,2048,1152)
        image = self.w.grab().toImage()
        self.assertTrue(self.w.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground))
        image = self.w.grab().toImage()
        # alpha=1: visually clear, but layered-window clicks must NOT pass through
        self.assertEqual(image.pixelColor(1900,1050).alpha(),1)

    def test_selection_keeps_inside_clear_and_dims_outside(self):
        self.w.sel,self.w.state = QRect(100,100,400,200),'ready'
        image = self.w.grab().toImage()
        self.assertEqual(image.pixelColor(200,180).alpha(),1)
        self.assertEqual(image.pixelColor(40,400).alpha(),105)

    def test_recording_mask_never_overlaps_capture_and_passes_input(self):
        screen = APP.primaryScreen().geometry()
        capture = QRect(screen.left()+100,screen.top()+80,400,240)
        mask = RecordingMask(capture)
        try:
            self.assertTrue(mask.panels)
            total = 0
            for panel in mask.panels:
                self.assertFalse(panel.geometry().intersects(capture))
                self.assertTrue(panel.windowFlags() & Qt.WindowType.WindowTransparentForInput)
                self.assertTrue(panel.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
                total += panel.geometry().width()*panel.geometry().height()
            self.assertEqual(total,screen.width()*screen.height()-capture.width()*capture.height())
        finally:
            mask.close()

    def test_begin_hands_countdown_to_controller(self):
        self.w.sel,self.w.state = QRect(100,100,400,200),'ready'
        events = []
        self.w.sigCountdownStart.connect(lambda *a: events.append(a))
        self.w.begin()
        self.assertEqual(self.w.state,'done')
        self.assertEqual(len(events),1)
        self.assertEqual(events[0][0]['width'],500)
        self.w.begin()
        self.assertEqual(len(events),1)

    def test_selection_controls_remove_reset_and_align_right(self):
        self.w.sel,self.w.state = QRect(300,180,720,320),'ready'
        self.w._place_bar()
        labels = [b.text() for b in self.w.bar.findChildren(QPushButton)]
        self.assertEqual(labels,['开始录制  ↵','取消  Esc'])
        self.assertEqual(self.w.bar.geometry().right(),self.w.sel.right())

    def test_handle_outside_rect_is_resize(self):
        self.w.sel,self.w.state = QRect(100,100,400,200),'ready'
        QTest.mousePress(self.w,Qt.MouseButton.LeftButton,pos=QPoint(97,100))
        self.assertEqual(self.w.mode,'resize')

    def test_move_does_not_shrink_at_edge(self):
        self.w.sel,self.w.state = QRect(100,100,400,200),'ready'
        QTest.mousePress(self.w,Qt.MouseButton.LeftButton,pos=QPoint(200,200))
        QTest.mouseMove(self.w,QPoint(2040,1100))
        QTest.mouseRelease(self.w,Qt.MouseButton.LeftButton,pos=QPoint(2040,1100))
        self.assertEqual(self.w.sel.size(),QSize(400,200))
        self.assertTrue(self.w.rect().contains(self.w.sel))


class FakeDetector:
    def __init__(self, rect):
        self.rect = rect
        self.calls = 0
    def rect_at(self, x, y):
        self.calls += 1
        return self.rect


class ElementDetectTests(unittest.TestCase):
    def test_top_window_at_offscreen_point_finds_nothing(self):
        from element_detect import top_window_at
        self.assertIsNone(top_window_at(-32000,-32000,os.getpid()))

    def test_detect_thread_reports_asynchronously_off_gui_thread(self):
        import time as _time
        from element_detect import DetectThread
        thread = DetectThread(detector_factory=lambda: FakeDetector((0,0,640,400)))
        events = []
        thread.detected.connect(lambda req,rect: events.append((req,rect)))
        thread.start()
        try:
            thread.request('overlay',10,10)
            thread.request('overlay',20,20)
            # QTest.qWait/QSignalSpy.wait hold the GIL and would starve the
            # Python worker; pump with real sleeps instead.
            deadline = _time.monotonic()+5
            while _time.monotonic() < deadline and not events:
                _time.sleep(0.02)
                APP.processEvents()
            self.assertEqual(events[-1],('overlay',(0,0,640,400)))
        finally:
            thread.stop()

    def test_full_monitor_hit_is_not_treated_as_element(self):
        w = SnipOverlay(FakeScreen(),dict(left=0,top=0,width=2560,height=1440),
                        detector=FakeDetector((0,0,2560,1440)))
        try:
            w._detect_at(QPoint(200,200))
            self.assertFalse(w.detected.isValid())
        finally:
            w.close()

    def test_async_detection_roundtrip_restores_input(self):
        from PySide6.QtCore import QObject, Signal as _Signal
        class FakeAsync(QObject):
            detected = _Signal(object,object)
            def __init__(self,rect):
                super().__init__()
                self.rect,self.requests = rect,[]
            def request(self,requester,x,y):
                self.requests.append((x,y))
                self.detected.emit(requester,self.rect)
        det = FakeAsync((100,100,700,400))
        w = SnipOverlay(FakeScreen(),dict(left=0,top=0,width=2560,height=1440),detector=det)
        try:
            w.cursor_pos = QPoint(200,200)
            w._detect_settled()
            self.assertEqual(det.requests,[(250,250)])
            self.assertEqual(w.detected,QRect(80,80,480,240))
        finally:
            w.close()

    def test_detected_element_highlight_and_click_adopts(self):
        w = SnipOverlay(FakeScreen(),dict(left=0,top=0,width=2560,height=1440),
                        detector=FakeDetector((100,100,700,400)))
        try:
            w._detect_at(QPoint(200,200))
            self.assertEqual(w.detected,QRect(80,80,480,240))
            image = w.grab().toImage()
            self.assertEqual(image.pixelColor(150,150).alpha(),1)
            self.assertEqual(image.pixelColor(40,400).alpha(),105)
            QTest.mousePress(w,Qt.MouseButton.LeftButton,pos=QPoint(200,200))
            self.assertEqual(w.mode,'maybe-adopt')
            QTest.mouseRelease(w,Qt.MouseButton.LeftButton,pos=QPoint(200,200))
            self.assertEqual(w.sel,QRect(80,80,480,240))
            self.assertEqual(w.state,'ready')
        finally:
            w.close()

    def test_drag_overrides_detected_element(self):
        w = SnipOverlay(FakeScreen(),dict(left=0,top=0,width=2560,height=1440),
                        detector=FakeDetector((100,100,700,400)))
        try:
            w._detect_at(QPoint(200,200))
            QTest.mousePress(w,Qt.MouseButton.LeftButton,pos=QPoint(200,200))
            QTest.mouseMove(w,QPoint(320,280))
            self.assertEqual(w.mode,'new')
            QTest.mouseRelease(w,Qt.MouseButton.LeftButton,pos=QPoint(320,280))
            self.assertEqual(w.sel,QRect(QPoint(200,200),QPoint(320,280)))
            self.assertEqual(w.state,'ready')
            self.assertFalse(w.detected.isValid())
        finally:
            w.close()

    def test_magnifier_shows_magnified_snapshot(self):
        bg = QImage(2560,1440,QImage.Format.Format_RGB32)
        bg.fill(QColor('#224466'))
        w = SnipOverlay(FakeScreen(),dict(left=0,top=0,width=2560,height=1440),background=bg)
        try:
            w.cursor_pos = QPoint(100,100)
            w.update()
            image = w.grab().toImage()
            self.assertEqual(image.pixelColor(148,148).name(),'#224466')
            self.assertEqual(image.pixelColor(40,400).alpha(),105)
            w.cursor_pos = None
            w.update()
            image = w.grab().toImage()
            self.assertEqual(image.pixelColor(148,148).name(),'#0c1118')
        finally:
            w.close()


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='framelet-test-')
        synthetic_frames(self.tmp.name)
        self.w = PreviewDialog(self.tmp.name,10)

    def test_default_gif_and_copy_button_state(self):
        self.assertEqual(self.w.format.currentData(),'gif')
        self.assertTrue(self.w.copy_button.isVisibleTo(self.w) is False or not self.w.isVisible())
        self.assertTrue(self.w.copy_button.isEnabled())
        self.assertEqual(self.w.copy_button.text(),'复制')
        self.assertTrue(self.w.copy_button.property('primary'))
        self.assertFalse(self.w.export_button.property('primary'))
        self.assertGreater(self.w.footer.indexOf(self.w.copy_button),
                           self.w.footer.indexOf(self.w.export_button))
        self.assertEqual(self.w.footer.indexOf(self.w.support_button)+1,
                         self.w.footer.indexOf(self.w.copy_button))
        self.assertEqual(self.w.support_button.text(),'')
        self.assertEqual(self.w.support_button.accessibleName(),'支持作者')

    def test_format_menu_opens_above_footer_at_screen_bottom(self):
        bounds = self.w.screen().availableGeometry()
        self.w.show()
        self.w.move(bounds.left(),bounds.bottom()-self.w.height()-6)
        self.w.activateWindow()
        picker = self.w.format
        picker.setFocus()
        APP.processEvents()
        self.addCleanup(picker.hidePopup)

        QTest.keyClick(picker,Qt.Key.Key_Space)
        menu = picker.menu
        self.assertTrue(menu.isVisible())
        self.assertFalse(self.w.timer.isActive())
        self.assertTrue(bounds.contains(menu.geometry()))
        self.assertLess(menu.geometry().bottom(),picker.mapToGlobal(QPoint()).y())
        panel = menu.rect().marginsRemoved(menu.SHADOW)
        self.assertEqual(panel.width(),picker.width())
        snapshot = menu.grab().toImage()
        ratio = snapshot.devicePixelRatio()
        corner = snapshot.pixelColor(round(panel.left()*ratio),round(panel.top()*ratio))
        center = snapshot.pixelColor(round(panel.center().x()*ratio),round(panel.center().y()*ratio))
        self.assertLess(corner.alpha(),128)
        self.assertEqual(center.alpha(),255)
        self.assertEqual([action.text() for action in menu.actions()],['GIF 动图','MP4 视频'])
        for action in menu.actions():
            self.assertTrue(menu.rect().contains(menu.actionGeometry(action)))

        QTest.keyClick(menu,Qt.Key.Key_Escape)
        self.assertFalse(menu.isVisible())
        self.assertEqual(picker.currentData(),'gif')
        QTest.mouseClick(picker,Qt.MouseButton.LeftButton)
        QTest.mouseClick(menu,Qt.MouseButton.LeftButton,
                         pos=menu.actionGeometry(menu.actions()[1]).center())
        self.assertFalse(menu.isVisible())
        self.assertEqual(picker.currentData(),'mp4')

    def tearDown(self):
        if self.w.worker:
            self.w.worker.cancel()
            self.w.worker.wait(15000)
            APP.processEvents()
        self.w.exported_range = (self.w.start,self.w.end)
        self.w.close()
        APP.processEvents()
        self.tmp.cleanup()

    def test_trim_bounds_without_numeric_controls(self):
        self.w.set_range(2,8)
        self.assertEqual((self.w.timeline.start,self.w.timeline.end),(2,8))
        self.assertEqual(self.w.findChildren(QDoubleSpinBox),[])
        self.assertNotIn('重置裁剪',[b.text() for b in self.w.findChildren(QPushButton)])
        self.assertEqual(self.w.duration_label.text(),'保留 0.60 秒')
        self.w.set_range(99,-4)
        self.assertEqual((self.w.start,self.w.end),(11,12))

    def test_playback_loops_selected_range(self):
        self.w.set_range(3,6)
        self.w.show_frame(5)
        self.w.advance()
        self.assertEqual(self.w.position,3)

    def test_centered_playback_button_toggles_icon_and_accessible_name(self):
        self.w.resize(620,510)
        self.w.show()
        self.w.activateWindow()
        APP.processEvents()
        play = self.w.play_button
        self.assertIs(self.w.focusWidget(),play)
        self.assertEqual(play.text(),'')
        self.assertAlmostEqual(play.geometry().center().x(),self.w.view.geometry().center().x(),delta=1)
        idle_icon = play.icon().cacheKey()
        self.assertEqual(play.accessibleName(),'播放片段')

        QTest.keyClick(play,Qt.Key.Key_Space)
        self.assertTrue(self.w.timer.isActive())
        self.assertNotEqual(play.icon().cacheKey(),idle_icon)
        self.assertEqual(play.accessibleName(),'暂停播放')

        QTest.mouseClick(play,Qt.MouseButton.LeftButton)
        self.assertFalse(self.w.timer.isActive())
        self.assertEqual(play.icon().cacheKey(),idle_icon)

    def test_editor_support_button_opens_popup_with_keyboard(self):
        self.w.show()
        self.w.activateWindow()
        heart = self.w.support_button
        heart.setFocus()
        APP.processEvents()
        with patch('widgets._animations_enabled',return_value=True):
            QTest.keyClick(heart,Qt.Key.Key_Space)
        self.assertTrue(heart.popup.isVisible())
        self.assertFalse(self.w.timer.isActive())
        self.assertFalse(heart.popup.qr.pixmap().isNull())
        self.assertTrue(heart.popup.confetti.timer.isActive())
        self.assertTrue(heart.popup.panel.geometry().contains(heart.popup.confetti.origin.toPoint()))

        QTest.keyClick(heart.popup,Qt.Key.Key_Escape)
        self.assertFalse(heart.popup.isVisible())
        self.assertFalse(heart.popup.confetti.timer.isActive())
        self.assertFalse(heart.popup.confetti.pieces)
        self.assertTrue(self.w.isVisible())

        with patch('widgets._animations_enabled',return_value=False):
            QTest.mouseClick(heart,Qt.MouseButton.LeftButton)
        self.assertTrue(heart.popup.isVisible())
        self.assertFalse(heart.popup.confetti.timer.isActive())
        self.assertFalse(heart.popup.confetti.pieces)
        QTest.mouseClick(heart.popup.close_button,Qt.MouseButton.LeftButton)
        self.assertFalse(heart.popup.isVisible())

    def test_dragging_end_previews_last_kept_frame(self):
        self.w.set_range(0,8)
        self.assertEqual(self.w.position,7)
        self.w.exported_range,self.w.last_path = (0,8),'previous.mp4'
        self.w.set_range(0,6)
        self.assertIn('尚未导出',self.w.status.text())

    def test_timeline_handles_and_keyboard(self):
        t = self.w.timeline
        t.resize(600,100)
        QTest.mousePress(t,Qt.MouseButton.LeftButton,pos=QPoint(round(t.frame_x(0)),30))
        QTest.mouseMove(t,QPoint(round(t.frame_x(3)),30))
        QTest.mouseRelease(t,Qt.MouseButton.LeftButton,pos=QPoint(round(t.frame_x(3)),30))
        self.assertEqual(self.w.start,3)
        QTest.keyClick(t,Qt.Key.Key_Right)
        self.assertEqual(self.w.position,4)

    def test_focused_timeline_preserves_frame_and_unselected_shading(self):
        self.w.resize(900,620)
        self.w.show()
        self.w.activateWindow()
        self.w.set_range(2,10)
        APP.processEvents()
        timeline = self.w.timeline
        x = round(timeline.frame_x(4.7))
        outside_x = round(timeline.frame_x(1.2))

        def track_colors():
            image = timeline.grab().toImage()
            ratio = image.devicePixelRatio()
            return [image.pixelColor(round(point*ratio),round(40*ratio))
                    for point in (x,outside_x)]

        before = track_colors()
        click_x = round(timeline.frame_x(7.1))
        QTest.mouseClick(timeline,Qt.MouseButton.LeftButton,pos=QPoint(click_x,40))
        self.assertTrue(timeline.hasFocus())
        self.assertEqual(track_colors(),before)
        QTest.keyClick(timeline,Qt.Key.Key_Right)
        self.assertEqual(self.w.position,8)
        self.assertEqual(track_colors(),before)

    def test_unsaved_close_requires_confirmation(self):
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):
            self.assertFalse(self.w.can_close())
        self.w.exported_range = (0,12)
        self.assertTrue(self.w.can_close())

    def test_custom_caption_restores_and_respects_close_guard(self):
        self.w.show()
        APP.processEvents()
        bar = self.w.frame.title_bar
        self.assertTrue(self.w.windowFlags() & Qt.WindowType.FramelessWindowHint)
        QTest.mouseDClick(bar,Qt.MouseButton.LeftButton,pos=QPoint(280,20))
        self.assertTrue(self.w.isMaximized())
        self.assertEqual(bar.maximize_button.glyph,'restore')
        QTest.mouseClick(bar.maximize_button,Qt.MouseButton.LeftButton)
        self.assertFalse(self.w.isMaximized())
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel) as confirm:
            QTest.mouseClick(bar.close_button,Qt.MouseButton.LeftButton)
        confirm.assert_called_once()
        self.assertTrue(self.w.isVisible())

    def test_export_ui_lifecycle_and_close_guard(self):
        with tempfile.TemporaryDirectory(prefix='framelet-ui-export-') as output:
            path = str(Path(output)/'clip.gif')
            self.w.set_range(2,7)
            with patch('widgets.QFileDialog.getSaveFileName',return_value=(path,'')):
                self.w.export()
            self.assertIsNotNone(self.w.worker)
            self.assertFalse(self.w.timeline.isEnabled())
            self.assertFalse(self.w.can_close())
            for _ in range(200):
                if self.w.worker is None: break
                QTest.qWait(25)
            self.assertIsNone(self.w.worker)
            self.assertTrue(self.w.timeline.isEnabled())
            self.assertEqual(self.w.exported_range,(2,7))
            self.assertTrue(Path(path).exists())
            self.assertIn('已保存',self.w.status.text())
            self.assertTrue(self.w.copy_button.isEnabled())
            with patch('widgets.copy_file_to_clipboard') as copy:
                self.w.copy_export()
                copy.assert_called_once_with(path)
            self.assertIn('已复制文件',self.w.status.text())

    def wait_for_copy(self):
        for _ in range(400):
            if self.w.worker is None: break
            QTest.qWait(25)
        self.assertIsNone(self.w.worker)

    def test_copy_without_export_encodes_current_trim_and_survives_close(self):
        with tempfile.TemporaryDirectory(prefix='framelet-copy-test-') as output:
            path = str(Path(output)/'clip.gif')
            self.w.set_range(2,7)
            self.w.show()
            APP.processEvents()
            with patch('widgets.clipboard_cache_path',return_value=path),\
                 patch('widgets.copy_file_to_clipboard') as copy,\
                 patch('widgets.QFileDialog.getSaveFileName') as save:
                QTest.mouseClick(self.w.copy_button,Qt.MouseButton.LeftButton)
                self.assertIsNotNone(self.w.worker)
                self.assertEqual(self.w.worker.args[3:],(2,7,'gif'))
                self.assertFalse(self.w.copy_button.isEnabled())
                self.assertFalse(self.w.can_close())
                self.wait_for_copy()
                save.assert_not_called()
                copy.assert_called_once_with(path)
                self.assertTrue(self.w.copy_button.isEnabled())
                self.assertEqual(Path(path).read_bytes()[:3],b'GIF')
                self.assertEqual(self.w.copied_range,(2,7))
                self.assertEqual(self.w.last_path,'')
                self.assertTrue(self.w.can_close())
                self.w.close()
                self.tmp.cleanup()
                self.assertTrue(Path(path).is_file())

    def test_copy_reuses_same_clip_but_reencodes_changed_trim_and_format(self):
        with tempfile.TemporaryDirectory(prefix='framelet-copy-test-') as output:
            paths = [str(Path(output)/name) for name in ('first.gif','trim.gif','clip.mp4')]
            with patch('widgets.clipboard_cache_path',side_effect=paths) as cache,\
                 patch('widgets.copy_file_to_clipboard') as copy:
                self.w.copy_export()
                self.wait_for_copy()
                self.w.copy_export()
                self.assertIsNone(self.w.worker)
                self.assertEqual(cache.call_count,1)
                self.w.set_range(3,8)
                self.assertEqual(self.w.copy_button.text(),'复制')
                self.w.copy_export()
                self.wait_for_copy()
                self.w.format.setCurrentIndex(self.w.format.findData('mp4'))
                self.w.copy_export()
                self.assertEqual(self.w.worker.args[3:],(3,8,'mp4'))
                self.wait_for_copy()
                self.assertEqual(cache.call_count,3)
                self.assertEqual([c.args[0] for c in copy.call_args_list],[paths[0],*paths])
                self.assertIn(b'ftyp',Path(paths[-1]).read_bytes()[:20])

    def test_copy_failure_is_explained_and_retry_reuses_generated_file(self):
        with tempfile.TemporaryDirectory(prefix='framelet-copy-test-') as output:
            path = str(Path(output)/'clip.gif')
            with patch('widgets.clipboard_cache_path',return_value=path) as cache,\
                 patch('widgets.copy_file_to_clipboard',side_effect=[RuntimeError('busy'),True]) as copy,\
                 patch.object(QMessageBox,'warning') as warning:
                self.w.copy_export()
                self.wait_for_copy()
                warning.assert_called_once()
                self.assertIsNone(self.w.copied_range)
                self.assertTrue(self.w.copy_button.isEnabled())
                self.assertIn('复制失败',self.w.status.text())
                self.w.copy_export()
                self.assertIsNone(self.w.worker)
                cache.assert_called_once()
                self.assertEqual(copy.call_count,2)
                self.assertEqual(self.w.copied_range,(0,12))

    def test_cancel_copy_reenables_button_without_copying(self):
        def wait_until_cancelled(*args,cancel=None):
            cancel.wait(5)
            raise InterruptedError('cancelled')
        with tempfile.TemporaryDirectory(prefix='framelet-copy-test-') as output:
            path = str(Path(output)/'clip.gif')
            with patch('widgets.clipboard_cache_path',return_value=path),\
                 patch('util.export_clip',side_effect=wait_until_cancelled),\
                 patch('widgets.copy_file_to_clipboard') as copy:
                self.w.copy_export()
                self.w.cancel_export()
                self.wait_for_copy()
                copy.assert_not_called()
                self.assertTrue(self.w.copy_button.isEnabled())
                self.assertFalse(Path(path).exists())
                self.assertIn('已取消复制',self.w.status.text())

    def test_copy_encoder_failure_preserves_recording_and_reenables_button(self):
        with tempfile.TemporaryDirectory(prefix='framelet-copy-test-') as output:
            with patch('widgets.clipboard_cache_path',return_value=str(Path(output)/'clip.gif')),\
                 patch('util.export_clip',side_effect=RuntimeError('encoder failed')),\
                 patch('widgets.copy_file_to_clipboard') as copy,\
                 patch.object(QMessageBox,'warning') as warning:
                self.w.copy_export()
                self.wait_for_copy()
                warning.assert_called_once()
                copy.assert_not_called()
                self.assertTrue(self.w.copy_button.isEnabled())
                self.assertEqual(len(list(Path(self.tmp.name).glob('f_*.png'))),12)

    def test_copy_cache_creation_failure_is_recoverable(self):
        with patch('widgets.clipboard_cache_path',side_effect=PermissionError('denied')),\
             patch.object(QMessageBox,'warning') as warning:
            self.w.copy_export()
            warning.assert_called_once()
            self.assertIsNone(self.w.worker)
            self.assertTrue(self.w.copy_button.isEnabled())

    def test_missing_previously_copied_file_is_regenerated(self):
        with tempfile.TemporaryDirectory(prefix='framelet-copy-test-') as output:
            path = str(Path(output)/'replacement.gif')
            self.w.copy_cache[('gif',0,12)] = str(Path(output)/'missing.gif')
            with patch('widgets.clipboard_cache_path',return_value=path),\
                 patch('widgets.copy_file_to_clipboard') as copy:
                self.w.copy_export()
                self.wait_for_copy()
                copy.assert_called_once_with(path)

    def test_render_editor_and_home(self):
        artifacts = Path(__file__).resolve().parent.parent/'test-artifacts'
        artifacts.mkdir(exist_ok=True)
        self.w.resize(940,720)
        self.w.show()
        APP.processEvents()
        self.assertTrue(self.w.copy_button.isVisible())
        self.w.set_range(2,10)
        self.w.timeline.setFocus()
        self.assertTrue(self.w.grab().save(str(artifacts/'editor.png')))
        home = HomeWindow()
        home.set_shortcut('Ctrl+Alt+8')
        self.assertIn('Ctrl+Alt+8',home.status.text())
        self.assertEqual(home.start_key.text(),'Ctrl+Alt+8')
        self.assertTrue(home.windowFlags() & Qt.WindowType.FramelessWindowHint)
        home.show()
        APP.processEvents()
        self.assertTrue(home.grab().save(str(artifacts/'home.png')))
        home.close()


class TrayBehaviorTests(unittest.TestCase):
    def setUp(self):
        from main import Controller
        settings_type = self.enterContext(patch('main.QSettings'))
        self.settings = settings_type.return_value
        self.settings.value.side_effect = lambda name,default,**kwargs: default
        self.auto_start = self.enterContext(patch('main.set_auto_start',return_value=True))
        tray_type = self.enterContext(patch('main.QSystemTrayIcon'))
        tray_type.ActivationReason = QSystemTrayIcon.ActivationReason
        tray_type.isSystemTrayAvailable.return_value = True
        self.enterContext(patch('main.external_foreground_window',return_value=None))
        self.restore_focus = self.enterContext(patch('main.restore_foreground_window'))
        self.c = Controller(APP)
        self.c.hotkeys.stop()

    def tearDown(self):
        self.c._clear_countdown()
        self.c.home.close()
        APP.screenRemoved.disconnect(self.c._screens_changed)
        self.c.tray.hide()
        self.c.deleteLater()

    def test_starts_hidden_with_24_fps(self):
        self.assertFalse(self.c.home.isVisible())
        self.assertEqual(self.c.home.fps.currentData(),24)
        self.assertEqual(Recorder(dict(left=0,top=0,width=20,height=20)).fps,24)
        self.assertNotIn('打开 Framelet',[a.text() for a in self.c.menu.actions()])

    def test_auto_start_defaults_on_and_toggle_persists(self):
        self.assertTrue(self.c.home.auto_start.isChecked())
        self.auto_start.assert_called_with(True)
        self.c.home.auto_start.setChecked(False)
        self.auto_start.assert_called_with(False)
        self.settings.setValue.assert_any_call('autoStart',False)
        self.assertIn('已关闭',self.c.home.shortcut_feedback.text())
        self.c.home.auto_start.setChecked(True)
        self.auto_start.assert_called_with(True)
        self.settings.setValue.assert_any_call('autoStart',True)
        self.assertTrue(self.c.home.auto_start.isChecked())
        self.assertEqual(self.c.home.shortcut_feedback.text(),'')

    def test_tray_menu_has_one_clear_recording_entry(self):
        labels = [action.text() for action in self.c.menu.actions() if not action.isSeparator()]
        self.assertEqual(labels,['选择区域录制','退出 Framelet'])

    def test_custom_shortcuts_save_immediately_and_persist(self):
        self.c._save_shortcut('F6')
        self.assertEqual(self.c.hotkeys.record_shortcut,'F6')
        self.assertEqual(self.c.hotkeys.pause_shortcut,'Ctrl+Shift+P')
        self.settings.setValue.assert_any_call('recordShortcut','F6')
        self.assertIn('已保存',self.c.home.shortcut_feedback.text())

    def test_f6_keypress_displays_and_saves_without_button(self):
        labels = [child.text() for child in self.c.home.findChildren(QPushButton)]
        self.assertNotIn('保存快捷键',labels)
        self.assertEqual(len(self.c.home.findChildren(QKeySequenceEdit)),1)
        self.c.home.show()
        self.c.home.record_shortcut.setFocus()
        QTest.keyClick(self.c.home.record_shortcut,Qt.Key.Key_F6)
        QTest.qWait(10)
        self.assertEqual(self.c.home.record_shortcut.keySequence().toString(),'F6')
        self.assertEqual(self.c.hotkeys.record_shortcut,'F6')
        self.settings.setValue.assert_any_call('recordShortcut','F6')

    def test_invalid_or_duplicate_shortcuts_do_not_replace_current_values(self):
        self.c._save_shortcut('R')
        self.assertEqual(self.c.hotkeys.record_shortcut,'F6')
        self.assertIn('未保存',self.c.home.shortcut_feedback.text())
        self.c._save_shortcut('Ctrl+Shift+P')
        self.assertEqual(self.c.hotkeys.record_shortcut,'F6')

    def test_shortcut_can_start_repeatedly_after_cancellation(self):
        for _ in range(6):
            self.c.hotkeys.record.emit()
            self.assertEqual(self.c.state,'preparing')
            self.c.abort_selection()
            self.assertEqual(self.c.state,'idle')

    def test_single_click_ignored_double_click_opens(self):
        self.c._tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
        self.assertFalse(self.c.home.isVisible())
        self.c._tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
        self.assertTrue(self.c.home.isVisible())

    def test_cancel_selection_returns_silently(self):
        self.c.show_home()
        self.c.state = 'selecting'
        self.c.abort_selection()
        self.assertEqual(self.c.state,'idle')
        self.assertFalse(self.c.home.isVisible())

    def test_closing_editor_does_not_open_home(self):
        from unittest.mock import Mock
        self.c.preview = Mock()
        self.c.state = 'editing'
        self.c._preview_finished()
        self.assertEqual(self.c.state,'idle')
        self.assertIsNone(self.c.preview)
        self.assertFalse(self.c.home.isVisible())

    def test_discard_recording_returns_silently(self):
        from unittest.mock import Mock
        self.c.recorder = Mock(frames_dir='',error='',saved=False)
        self.c.state = 'stopping'
        self.c._record_finished()
        self.assertEqual(self.c.state,'idle')
        self.assertFalse(self.c.home.isVisible())

    def _begin_countdown(self):
        from unittest.mock import Mock
        self.selection_windows = [Mock(),Mock()]
        self.c.overlays = self.selection_windows.copy()
        self.c.state = 'selecting'
        self.c._prepare_record(dict(left=100,top=100,width=400,height=300),QRect(100,100,400,300))

    def test_countdown_closes_all_selection_windows_and_passes_input(self):
        self.c._target_window = 1234
        self._begin_countdown()
        self.restore_focus.assert_called_once_with(1234)
        for w in self.selection_windows:
            w.close.assert_called_once()
        self.assertFalse(self.c.overlays)
        self.assertEqual(self.c.state,'countdown')
        self.assertIsNone(self.c.recorder)
        flags = self.c.countdown.windowFlags()
        self.assertTrue(flags & Qt.WindowType.WindowTransparentForInput)
        self.assertTrue(flags & Qt.WindowType.WindowDoesNotAcceptFocus)
        self.assertTrue(self.c.countdown.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating))
        self.assertIsNotNone(self.c.countdown_mask)
        self.assertIsNotNone(self.c.countdown_outline)
        self.assertTrue(self.c.countdown_mask.panels)
        for panel in self.c.countdown_mask.panels:
            self.assertTrue(panel.windowFlags() & Qt.WindowType.WindowTransparentForInput)
            self.assertFalse(panel.geometry().intersects(QRect(100,100,400,300)))

    def test_escape_cancels_countdown_without_recording(self):
        self._begin_countdown()
        self.c.bridge.cancel.emit()
        self.assertEqual(self.c.state,'idle')
        self.assertIsNone(self.c.countdown)
        self.assertIsNone(self.c.countdown_mask)
        self.assertIsNone(self.c.countdown_outline)
        self.assertIsNone(self.c.recorder)
        self.assertFalse(self.c._countdown_timer.isActive())
        self.assertFalse(self.c.home.isVisible())

    def test_capture_starts_only_after_countdown_is_hidden(self):
        self._begin_countdown()
        original_mask = self.c.countdown_mask
        original_outline = self.c.countdown_outline
        with patch.object(self.c,'_start_record') as capture:
            self.c._countdown_tick()
            self.assertEqual(self.c.countdown.remaining,2)
            capture.assert_not_called()
            self.c._countdown_tick()
            self.assertEqual(self.c.countdown.remaining,1)
            self.c._countdown_tick()
            self.assertIsNone(self.c.countdown)
            self.assertIs(self.c.countdown_mask,original_mask)
            self.assertIs(self.c.countdown_outline,original_outline)
            capture.assert_not_called()
            QTest.qWait(280)
            capture.assert_called_once()

    def test_countdown_visuals_can_be_retained_then_cleaned(self):
        self._begin_countdown()
        mask,outline = self.c.countdown_mask,self.c.countdown_outline
        self.c._clear_countdown(keep_selection_visuals=True)
        self.assertIs(self.c.countdown_mask,mask)
        self.assertIs(self.c.countdown_outline,outline)
        self.c._clear_countdown()
        self.assertIsNone(self.c.countdown_mask)
        self.assertIsNone(self.c.countdown_outline)

    def test_hotkey_cancel_invalidates_delayed_start(self):
        self._begin_countdown()
        with patch.object(self.c,'_start_record') as capture:
            for _ in range(3): self.c._countdown_tick()
            self.c.hotkey_record()
            QTest.qWait(280)
            capture.assert_not_called()
            self.assertEqual(self.c.state,'idle')


class GlobalHotkeyTests(unittest.TestCase):
    def test_shortcut_parser_accepts_safe_keys_and_rejects_plain_key(self):
        self.assertEqual(parse_shortcut('Ctrl+Alt+8')[2],'Ctrl+Alt+8')
        self.assertEqual(parse_shortcut('Shift+F12')[2],'Shift+F12')
        self.assertEqual(parse_shortcut('F6')[2],'F6')
        with self.assertRaises(ValueError): parse_shortcut('R')

    def test_custom_shortcuts_drive_polling(self):
        down,events = set(),[]
        hotkeys = GlobalHotkeys(key_state=lambda key:key in down)
        hotkeys.stop()
        hotkeys.set_shortcuts('F6','F7')
        hotkeys.record.connect(lambda:events.append('record'))
        down.add(0x75)
        hotkeys.poll(); hotkeys.poll()
        self.assertEqual(events,['record'])

    def test_shortcuts_fire_once_per_press_and_recover_across_repeated_use(self):
        down = set()
        hotkeys = GlobalHotkeys(key_state=lambda key:key in down)
        hotkeys.stop()
        events = []
        hotkeys.record.connect(lambda:events.append('record'))
        hotkeys.pause.connect(lambda:events.append('pause'))
        hotkeys.escape.connect(lambda:events.append('escape'))
        for _ in range(8):
            down.update((hotkeys.VK_CONTROL,hotkeys.VK_SHIFT,hotkeys.VK_R))
            hotkeys.poll(); hotkeys.poll()
            down.clear(); hotkeys.poll()
        down.update((hotkeys.VK_CONTROL,hotkeys.VK_SHIFT,hotkeys.VK_P))
        hotkeys.poll(); down.clear(); hotkeys.poll()
        down.add(hotkeys.VK_ESCAPE)
        hotkeys.poll(); hotkeys.poll()
        self.assertEqual(events,['record']*8+['pause','escape'])


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='framelet-export-test-')
        self.root = Path(self.tmp.name)
        self.frames = self.root/'frames'
        self.frames.mkdir()
        synthetic_frames(self.frames,width=19,height=13)

    def tearDown(self): self.tmp.cleanup()

    def decode(self,path):
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(),'-v','error','-i',str(path),
               '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24','-']
        result = subprocess.run(cmd,capture_output=True,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.assertEqual(result.returncode,0,result.stderr)
        return result.stdout

    def test_mp4_exact_selected_frames_and_odd_size_padding(self):
        out = self.root/'trim.mp4'
        export_clip(self.frames,10,out,3,8,'mp4')
        data = self.decode(out)
        self.assertEqual(len(data),5*20*14*3)
        self.assertLess(abs(data[0]-51),10)
        self.assertLess(abs(data[-20*14*3]-119),10)

    def test_gif_exact_selected_frames(self):
        out = self.root/'trim.gif'
        export_clip(self.frames,10,out,3,8,'gif')
        data = self.decode(out)
        self.assertEqual(len(data),5*19*13*3)
        self.assertLess(abs(data[0]-51),8)

    def test_16_fps_exports_preserve_selected_frames(self):
        for kind,stride in [('gif',19*13*3),('mp4',20*14*3)]:
            out = self.root/f'sixteen.{kind}'
            export_clip(self.frames,16,out,2,10,kind)
            self.assertEqual(len(self.decode(out)),8*stride)

    def test_cancel_preserves_destination(self):
        out = self.root/'existing.mp4'
        out.write_bytes(b'original')
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError): export_clip(self.frames,10,out,0,12,'mp4',cancel)
        self.assertEqual(out.read_bytes(),b'original')
        self.assertFalse(list(self.root.glob('.framelet-*')))

    def test_invalid_range(self):
        with self.assertRaises(ValueError): export_clip(self.frames,10,self.root/'x.mp4',4,4,'mp4')

    def test_worker_finishes(self):
        worker = ExportWorker(self.frames,10,str(self.root/'worker.mp4'),0,2,'mp4')
        worker.start()
        self.assertTrue(worker.wait(15000))
        self.assertFalse(worker.error)
        self.assertTrue(Path(worker.path).exists())

    def test_single_frame_and_last_frame_export(self):
        for kind in ('gif','mp4'):
            out = self.root/f'last.{kind}'
            export_clip(self.frames,10,out,11,12,kind)
            data = self.decode(out)
            stride = 19*13*3 if kind == 'gif' else 20*14*3
            self.assertEqual(len(data),stride)
            self.assertLess(abs(data[0]-187),10)

    def test_destination_inside_recording_is_rejected(self):
        folder = self.frames/'output'
        folder.mkdir()
        with self.assertRaises(ValueError): export_clip(self.frames,10,folder/'x.gif',0,2,'gif')

    def test_encoder_failure_preserves_destination(self):
        out = self.root/'existing.mp4'
        out.write_bytes(b'original')
        with patch('util.imageio_ffmpeg.get_ffmpeg_exe',return_value='missing-framelet-ffmpeg.exe'):
            with self.assertRaises(OSError): export_clip(self.frames,10,out,0,2,'mp4')
        self.assertEqual(out.read_bytes(),b'original')
        self.assertFalse(list(self.root.glob('.framelet-*')))


class RecorderTests(unittest.TestCase):
    def test_cursor_size_follows_monitor_dpi_and_pointer_setting(self):
        self.assertEqual(scaled_cursor_geometry(32,32,4,7,32,96),(32,32,4,7))
        self.assertEqual(scaled_cursor_geometry(32,32,4,8,32,120),(40,40,5,10))
        self.assertEqual(scaled_cursor_geometry(32,32,4,8,64,120),(80,80,10,20))

    def test_already_scaled_cursor_bitmap_is_not_shrunk_or_enlarged_twice(self):
        self.assertEqual(scaled_cursor_geometry(64,64,8,10,32,120),(64,64,8,10))

    def test_capture_pipeline_composites_cursor_before_save(self):
        class Shot:
            width,height,raw = 20,20,bytes([30,80,120,255])*400
        with tempfile.TemporaryDirectory(prefix='framelet-worker-test-') as directory:
            with patch('recorder.tempfile.mkdtemp',return_value=directory),patch('recorder.mss.mss') as capture,\
                 patch('recorder.compose_cursor',side_effect=lambda raw,*args: raw) as cursor:
                capture.return_value.__enter__.return_value.grab.return_value = Shot()
                worker = Recorder(dict(left=7,top=9,width=20,height=20),fps=1,max_seconds=.01)
                worker.run()
                cursor.assert_called_once_with(Shot.raw,20,20,worker.region)
                self.assertTrue(Path(directory,'f_00001.png').exists())

    def test_capture_failure_finishes_with_error(self):
        with tempfile.TemporaryDirectory(prefix='framelet-worker-test-') as directory:
            with patch('recorder.tempfile.mkdtemp',return_value=directory),patch('recorder.mss.mss',side_effect=OSError('capture failed')):
                worker = Recorder(dict(left=0,top=0,width=20,height=20))
                worker.start()
                self.assertTrue(worker.wait(5000))
                self.assertIn('capture failed',worker.error)
                self.assertFalse(worker.saved)

    def test_stop_during_pause(self):
        with tempfile.TemporaryDirectory(prefix='framelet-worker-test-') as directory:
            with patch('recorder.tempfile.mkdtemp',return_value=directory),patch('recorder.mss.mss'):
                worker = Recorder(dict(left=0,top=0,width=20,height=20))
                worker.set_paused(True)
                worker.start()
                QTest.qWait(60)
                self.assertEqual(worker.frame_count,0)
                worker.stop(False)
                self.assertTrue(worker.wait(5000))
                self.assertFalse(worker.saved)

    def test_partial_frames_survive_capture_error(self):
        class Shot:
            width,height,raw = 20,20,bytes([30,80,120,255])*400
        with tempfile.TemporaryDirectory(prefix='framelet-worker-test-') as directory:
            with patch('recorder.tempfile.mkdtemp',return_value=directory),patch('recorder.mss.mss') as capture:
                capture.return_value.__enter__.return_value.grab.side_effect = [Shot(),OSError('lost display')]
                worker = Recorder(dict(left=0,top=0,width=20,height=20),fps=30)
                worker.start()
                self.assertTrue(worker.wait(5000))
                self.assertTrue(worker.saved)
                self.assertEqual(worker.frame_count,1)
                self.assertIn('lost display',worker.error)


if __name__ == '__main__': unittest.main()
