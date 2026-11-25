"""Framelet launcher, recording controls and non-destructive trim editor."""
from collections import OrderedDict
import ctypes
from datetime import datetime
from pathlib import Path
import sys

from PySide6.QtCore import (
    Qt, QEvent, QMargins, QTimer, Signal, QUrl, QRect, QRectF, QPoint, QPointF,
    QSize, QVariantAnimation,
)
from PySide6.QtGui import (QPainter, QColor, QImageReader, QDesktopServices,
                           QIcon, QKeySequence, QShortcut, QPen, QFont, QPixmap)
from PySide6.QtWidgets import (QWidget,QLabel,QHBoxLayout,QVBoxLayout,QDialog,
    QFileDialog,QMessageBox,QApplication,QSizePolicy,QComboBox,QProgressBar,
    QKeySequenceEdit,QCheckBox,QFrame,QGraphicsDropShadowEffect,QToolButton,
    QLayout,QPushButton)
from confetti import ConfettiLayer
from lucide_icons import lucide_icon
from popup_menu import PopupMenu
from theme import ACCENT, ACCENT_TEXT, DARK, FOCUS, LIGHT_INK, MUTED, PREVIEW_MATTE, SIGNAL_RED, button
from timeline import TrimTimeline,timecode
from util import ExportWorker,copy_file_to_clipboard,clipboard_cache_path
from window_frame import WindowFrame


class StyledComboBox(QComboBox):
    def __init__(self, parent=None, prefer_above=False):
        super().__init__(parent)
        self.prefer_above = prefer_above
        self.setObjectName('styledCombo')
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.chevron = lucide_icon('chevron-down',MUTED,16)
        self.menu = PopupMenu(self,choices=True)
        self.menu.aboutToHide.connect(self._popup_hidden)

    def paintEvent(self,event):
        super().paintEvent(event)
        painter = QPainter(self)
        mode = QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled
        painter.translate(self.width()-17,self.height()/2)
        if self.menu.isVisible():
            painter.rotate(180)
        self.chevron.paint(painter,QRect(-8,-8,16,16),mode=mode)
        painter.end()

    def event(self,event):
        if (event.type() == QEvent.Type.ShortcutOverride and
                event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self,event):
        if event.key() == Qt.Key.Key_Space and event.modifiers() == Qt.KeyboardModifier.NoModifier:
            self.showPopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def showPopup(self):
        if not self.count() or not self.isEnabled() or self.menu.isVisible():
            return
        self.menu.clear()
        selected = None
        for row in range(self.count()):
            index = self.model().index(row,self.modelColumn(),self.rootModelIndex())
            action = self.menu.addAction(self.itemText(row))
            action.setEnabled(bool(self.model().flags(index) & Qt.ItemFlag.ItemIsEnabled))
            action.setCheckable(True)
            action.triggered.connect(lambda _checked,row=row:self._choose(row))
            if row == self.currentIndex():
                action.setChecked(True)
                selected = action
        shadow = self.menu.SHADOW
        self.menu.setMinimumWidth(self.width()+shadow.left()+shadow.right())
        size = self.menu.sizeHint()
        width,height = size.width(),size.height()
        bounds = self.screen().availableGeometry()
        anchor = self.mapToGlobal(QPoint())
        gap = 8
        below = anchor.y()+self.height()+gap-shadow.top()
        above = anchor.y()-height-gap+shadow.bottom()
        use_above = above >= bounds.top() and (self.prefer_above or below+height > bounds.bottom()+1)
        x = max(bounds.left(),min(anchor.x()-shadow.left(),bounds.right()-width+1))
        y = max(bounds.top(),min(above if use_above else below,bounds.bottom()-height+1))
        self.menu.popup(QPoint(x,y))
        if selected:
            self.menu.setActiveAction(selected)
        self.update()

    def hidePopup(self):
        if self.menu.isVisible():
            self.menu.hide()
        else:
            super().hidePopup()

    def _popup_hidden(self):
        super().hidePopup()
        self.update()

    def _choose(self,index):
        self.setCurrentIndex(index)
        self.activated.emit(index)
        self.textActivated.emit(self.itemText(index))


class SettingsSwitch(QCheckBox):
    def __init__(self):
        super().__init__()
        self.setFixedSize(48,34)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def hitButton(self,position):
        return self.rect().contains(position)

    def paintEvent(self,event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        checked = self.isChecked()
        if self.hasFocus():
            painter.setPen(QPen(QColor(FOCUS),1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(1,2,46,30),15,15)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QColor(ACCENT if checked else '#777580')
        if self.underMouse():
            track = track.lighter(107)
        if self.isDown():
            track = track.darker(115)
        if not self.isEnabled():
            track = QColor('#BEC4C9')
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(4,6,40,22),11,11)
        thumb_x = 23 if checked else 7
        painter.setBrush(QColor(LIGHT_INK))
        painter.drawEllipse(QRectF(thumb_x,9,16,16))
        painter.end()


class LucideGlyph(QWidget):
    def __init__(self,name,color,size,container_size=None):
        super().__init__()
        self.glyph = lucide_icon(name,color,size)
        self.glyph_size = size
        extent = container_size or size
        self.setFixedSize(extent,extent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self,event):
        offset = (self.width()-self.glyph_size)//2
        painter = QPainter(self)
        self.glyph.paint(painter,QRect(offset,offset,self.glyph_size,self.glyph_size))
        painter.end()


class HomeWindow(QWidget):
    sigStart = Signal()
    sigRecordShortcut = Signal(str)
    sigAutoStart = Signal(bool)

    def __init__(self):
        super().__init__()
        self.setObjectName('home')
        self.setWindowTitle('Framelet · 区域录屏')
        self.resize(518,540)
        self.frame = WindowFrame(self,'设置')
        content = QWidget()
        content.setObjectName('homeContent')
        content.setCursor(Qt.CursorShape.ArrowCursor)
        self.frame.content.addWidget(content,1)
        root = QVBoxLayout(content)
        root.setContentsMargins(23,19,23,15)
        root.setSpacing(12)

        header = QVBoxLayout()
        header.setSpacing(4)
        title = QLabel('区域录屏')
        title.setObjectName('settingsTitle')
        header.addWidget(title)
        hint = QLabel('录下桌面操作，裁剪成 GIF 或 MP4。')
        hint.setObjectName('settingsSubtitle')
        hint.setWordWrap(True)
        header.addWidget(hint)
        root.addLayout(header)

        self.start_button = button('',True)
        self.start_button.setObjectName('startRecording')
        self.start_button.setAccessibleName('选择录制区域')
        self.start_button.clicked.connect(self.sigStart.emit)
        action_row = QHBoxLayout(self.start_button)
        action_row.setContentsMargins(15,10,17,10)
        action_row.setSpacing(12)
        symbol = LucideGlyph('scan',LIGHT_INK,22,40)
        symbol.setObjectName('startSymbol')
        action_row.addWidget(symbol)
        action_text = QVBoxLayout()
        action_text.setSpacing(3)
        for text,name in (('选择录制区域','startTitle'),('录制画面与鼠标指针 · 无音频','startDetail')):
            label = QLabel(text)
            label.setObjectName(name)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            action_text.addWidget(label)
        action_row.addLayout(action_text,1)
        self.start_key = QLabel('F6')
        self.start_key.setObjectName('startKey')
        self.start_key.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.start_key.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        action_row.addWidget(self.start_key,0,Qt.AlignmentFlag.AlignVCenter)
        root.addWidget(self.start_button)

        section = QVBoxLayout()
        section.setSpacing(8)
        settings_title = QLabel('录制设置')
        settings_title.setObjectName('settingsHeading')
        section.addWidget(settings_title)
        card = QFrame()
        card.setObjectName('settingsPanel')
        body = QVBoxLayout(card)
        body.setContentsMargins(14,4,14,4)
        body.setSpacing(0)
        self.fps = StyledComboBox()
        for value in (10,16,24,30): self.fps.addItem(f'{value} fps',value)
        self.fps.setCurrentIndex(self.fps.findData(24))
        self.fps.setAccessibleName('录制帧率')
        self.fps.setMinimumWidth(112)
        self.duration = StyledComboBox()
        for value in (30,60,120): self.duration.addItem(f'{value} 秒',value)
        self.duration.setCurrentIndex(2)
        self.duration.setAccessibleName('最长录制时长')
        self.duration.setMinimumWidth(112)

        self.record_shortcut = QKeySequenceEdit()
        self.record_shortcut.setMaximumSequenceLength(1)
        self.record_shortcut.setClearButtonEnabled(True)
        clear = self.record_shortcut.findChild(QToolButton)
        if clear is not None:
            clear.setIcon(lucide_icon('x',MUTED,15))
            clear.setObjectName('shortcutClear')
        self.record_shortcut.setAccessibleName('开始和完成录制快捷键')
        self.record_shortcut.setFixedWidth(186)
        self._setting_shortcuts = False
        self._shortcut_save_timer = QTimer(self)
        self._shortcut_save_timer.setSingleShot(True)
        self._shortcut_save_timer.setInterval(0)
        self._shortcut_save_timer.timeout.connect(self._emit_shortcut)
        self.record_shortcut.keySequenceChanged.connect(lambda _sequence:self._queue_shortcut_save())
        self._setting_auto_start = False
        self.auto_start = SettingsSwitch()
        self.auto_start.setAccessibleName('开机自动启动')
        self.auto_start.toggled.connect(self._auto_start_toggled)
        for icon,text,control in (('gauge','帧率',self.fps),('timer','最长录制',self.duration),
                                  ('keyboard','开始 / 完成录制',self.record_shortcut),
                                  ('power','开机自动启动',self.auto_start)):
            if body.count():
                divider = QFrame()
                divider.setObjectName('settingsDivider')
                divider.setFixedHeight(1)
                body.addWidget(divider)
            row = QHBoxLayout()
            row.setContentsMargins(0,6,0,6)
            row.setSpacing(10)
            row.addWidget(LucideGlyph(icon,MUTED,17))
            label = QLabel(text)
            label.setBuddy(control)
            row.addWidget(label,1)
            row.addWidget(control)
            body.addLayout(row)
        section.addWidget(card)
        self.shortcut_feedback = QLabel('修改快捷键后自动保存。')
        self.shortcut_feedback.setObjectName('homeNote')
        self.shortcut_feedback.setWordWrap(True)
        section.addWidget(self.shortcut_feedback)
        root.addLayout(section)

        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.status = QLabel()
        self.status.setObjectName('homeNote')
        self.status.setWordWrap(True)
        footer.addWidget(self.status,1)
        self.support_button = SupportButton()
        footer.addWidget(self.support_button,0,Qt.AlignmentFlag.AlignBottom)
        root.addStretch()
        root.addLayout(footer)

        self.setTabOrder(self.start_button,self.fps)
        self.setTabOrder(self.fps,self.duration)
        self.setTabOrder(self.duration,self.record_shortcut)
        self.setTabOrder(self.record_shortcut,self.auto_start)
        self.setTabOrder(self.auto_start,self.support_button)
        self.start_button.setFocus()

    def _queue_shortcut_save(self):
        if self._setting_shortcuts: return
        # QKeySequenceEdit emits an intermediate empty value before the final
        # key. Coalesce changes from one key event so F6/F7 are not rolled back.
        self._shortcut_save_timer.start()

    def _emit_shortcut(self):
        self.sigRecordShortcut.emit(
            self.record_shortcut.keySequence().toString(QKeySequence.SequenceFormat.PortableText))

    def set_shortcut(self,record,pause='Ctrl+Shift+P'):
        self._shortcut_save_timer.stop()
        self._setting_shortcuts = True
        try:
            self.record_shortcut.setKeySequence(QKeySequence(record))
        finally:
            self._setting_shortcuts = False
        self.start_key.setText(record)
        self.status.setText(f'{record} 开始 / 完成  ·  {pause} 暂停 / 继续')

    def _auto_start_toggled(self,checked):
        if not self._setting_auto_start: self.sigAutoStart.emit(checked)

    def set_auto_start(self,enabled):
        self._setting_auto_start = True
        try:
            self.auto_start.setChecked(enabled)
        finally:
            self._setting_auto_start = False

    def shortcut_editing(self):
        return self.record_shortcut.hasFocus()


def _animations_enabled():
    if sys.platform != 'win32':
        return True
    enabled = ctypes.c_int()
    # SPI_GETCLIENTAREAANIMATION, the Windows accessibility animation preference.
    success = ctypes.windll.user32.SystemParametersInfoW(0x1042,0,ctypes.byref(enabled),0)
    return not success or bool(enabled.value)


class SupportButton(QPushButton):
    WIGGLE_INTERVAL_MS = 2000

    def __init__(self):
        super().__init__()
        self.popup = None
        self.setObjectName('supportButton')
        self.heart_icon = lucide_icon('heart',ACCENT_TEXT,18,filled=True)
        self.setIcon(self.heart_icon)
        self.setIconSize(QSize(18,18))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName('支持作者')
        self.setToolTip('支持作者')
        self.setAutoDefault(False)
        self.setFixedSize(38,38)
        self.clicked.connect(self.show_popup)
        self._wiggle = QVariantAnimation(self)
        self._wiggle.setDuration(480)
        self._wiggle.setKeyValues([(0.0,0.0),(0.18,-12.0),(0.37,11.0),
                                  (0.56,-7.0),(0.74,4.0),(1.0,0.0)])
        self._wiggle.valueChanged.connect(self._rotate_heart)
        self._wiggle.finished.connect(self._stop_wiggle)
        self._wiggle_timer = QTimer(self)
        self._wiggle_timer.setSingleShot(True)
        self._wiggle_timer.setInterval(self.WIGGLE_INTERVAL_MS)
        self._wiggle_timer.timeout.connect(self._maybe_wiggle)

    def event(self,event):
        if (event.type() == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Space
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            event.accept()
            return True
        return super().event(event)

    def show_popup(self):
        self._stop_wiggle()
        if self.popup is None:
            self.popup = SupportPopup(self.window())
        self.popup.show_at(self)

    def showEvent(self,event):
        super().showEvent(event)
        self._wiggle_timer.start()

    def enterEvent(self,event):
        self._stop_wiggle()
        super().enterEvent(event)

    def hideEvent(self,event):
        self._wiggle_timer.stop()
        self._stop_wiggle()
        if self.popup is not None and self.popup.isVisible():
            self.popup.reject()
        super().hideEvent(event)

    def _maybe_wiggle(self):
        self._wiggle_timer.start()
        if (self.window().isActiveWindow() and not self.underMouse()
                and not (self.popup and self.popup.isVisible()) and _animations_enabled()):
            self._wiggle.start()

    def _rotate_heart(self,angle):
        size = self.iconSize().width()
        ratio = self.devicePixelRatioF()
        pixels = round(size*ratio)
        frame = QPixmap(pixels,pixels)
        frame.setDevicePixelRatio(ratio)
        frame.fill(Qt.GlobalColor.transparent)
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.translate(size/2,size/2)
        painter.rotate(angle)
        self.heart_icon.paint(painter,QRect(-size//2,-size//2,size,size))
        painter.end()
        self.setIcon(QIcon(frame))

    def _stop_wiggle(self):
        self._wiggle.stop()
        self.setIcon(self.heart_icon)


class SupportPopup(QDialog):
    EMAIL = 'Kwaneu96@qq.com'
    QR_SIZE = 180
    SHADOW = QMargins(12,8,12,14)
    CONFETTI_SPACE = QMargins(260,225,260,115)

    def __init__(self,parent):
        super().__init__(parent,Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                         Qt.WindowType.NoDropShadowWindowHint)
        self.setObjectName('supportPopup')
        self.setWindowTitle('支持 Framelet 作者')
        self.setAccessibleName('支持 Framelet 作者')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.confetti = ConfettiLayer(self)
        outer = QVBoxLayout(self)
        outer.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        outer.setContentsMargins(self.SHADOW)

        panel = QFrame()
        self.panel = panel
        panel.setObjectName('supportPanel')
        panel.setFixedWidth(304)
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(22)
        shadow.setOffset(0,4)
        shadow.setColor(QColor(28,32,37,44))
        panel.setGraphicsEffect(shadow)
        outer.addWidget(panel)
        body = QVBoxLayout(panel)
        body.setContentsMargins(12,12,12,14)
        body.setSpacing(10)

        intro = QFrame()
        intro.setObjectName('supportHeading')
        intro_layout = QVBoxLayout(intro)
        intro_layout.setContentsMargins(12,8,8,10)
        intro_layout.setSpacing(2)
        heading = QHBoxLayout()
        title = QLabel('请作者喝杯咖啡')
        title.setObjectName('supportTitle')
        heading.addWidget(title,1)
        self.close_button = button('',icon='x',icon_size=16)
        self.close_button.setObjectName('supportClose')
        self.close_button.setFixedSize(28,28)
        self.close_button.setAccessibleName('关闭支持作者浮层')
        self.close_button.setToolTip('关闭')
        self.close_button.clicked.connect(self.reject)
        heading.addWidget(self.close_button)
        intro_layout.addLayout(heading)

        description = QLabel('如果 Framelet 帮你省了一点时间，你的支持会给我继续打磨它的动力。')
        description.setObjectName('supportNote')
        description.setWordWrap(True)
        intro_layout.addWidget(description)
        body.addWidget(intro)

        qr_card = QFrame()
        qr_card.setObjectName('supportQrCard')
        qr_layout = QVBoxLayout(qr_card)
        qr_layout.setContentsMargins(8,7,8,7)
        qr_layout.setSpacing(4)
        self.qr = QLabel()
        self.qr.setFixedSize(self.QR_SIZE,self.QR_SIZE)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr.setAccessibleName('微信打赏二维码')
        qr_layout.addWidget(self.qr,0,Qt.AlignmentFlag.AlignHCenter)
        scan = QLabel('微信扫码打赏')
        scan.setObjectName('supportNote')
        qr_layout.addWidget(scan,0,Qt.AlignmentFlag.AlignHCenter)
        body.addWidget(qr_card,0,Qt.AlignmentFlag.AlignHCenter)
        base = Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent))
        self.qr_source = QPixmap(str(base/'support-qr.png'))

        email_row = QHBoxLayout()
        email_row.setContentsMargins(4,0,4,0)
        email_row.setSpacing(8)
        email_row.addWidget(LucideGlyph('mail',MUTED,16))
        email = QLabel(self.EMAIL)
        email.setAccessibleName('作者邮箱 '+self.EMAIL)
        email.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        email_row.addWidget(email,1)
        self.copy_button = button('复制',icon='copy',icon_color=ACCENT_TEXT,icon_size=14)
        self.copy_button.setObjectName('supportCopy')
        self.copy_button.setAccessibleName('复制作者邮箱')
        self.copy_button.setFixedWidth(84)
        self.copy_button.clicked.connect(self.copy_email)
        email_row.addWidget(self.copy_button)
        body.addLayout(email_row)

        free = QLabel('Framelet 免费使用，打赏随心。谢谢你用它。')
        free.setObjectName('supportNote')
        free.setAlignment(Qt.AlignmentFlag.AlignCenter)
        free.setWordWrap(True)
        body.addWidget(free)

        self.copy_feedback = QTimer(self)
        self.copy_feedback.setSingleShot(True)
        self.copy_feedback.setInterval(1600)
        self.copy_feedback.timeout.connect(self.reset_copy_feedback)

    def copy_email(self):
        QApplication.clipboard().setText(self.EMAIL)
        self.copy_button.setText('已复制')
        self.copy_button.setIcon(lucide_icon('check',ACCENT_TEXT,14))
        self.copy_button.setAccessibleName('已复制作者邮箱')
        self.copy_feedback.start()

    def reset_copy_feedback(self):
        self.copy_feedback.stop()
        self.copy_button.setText('复制')
        self.copy_button.setIcon(lucide_icon('copy',ACCENT_TEXT,14))
        self.copy_button.setAccessibleName('复制作者邮箱')

    def show_at(self,anchor):
        screen = anchor.screen()
        bounds = screen.availableGeometry()
        self.confetti.stop()
        self.layout().setContentsMargins(self.SHADOW)
        self.qr.setFixedSize(self.QR_SIZE,self.QR_SIZE)
        self.layout().activate()
        natural = self.sizeHint().expandedTo(self.minimumSizeHint())
        overflow = max(0,natural.height()-bounds.height())
        qr_size = max(128,self.QR_SIZE-overflow)
        self.qr.setFixedSize(qr_size,qr_size)
        if self.qr_source.isNull():
            self.qr.setText('二维码暂不可用')
        else:
            ratio = screen.devicePixelRatio()
            pixels = round(qr_size*ratio)
            image = self.qr_source.scaled(pixels,pixels,Qt.AspectRatioMode.KeepAspectRatio)
            image.setDevicePixelRatio(ratio)
            self.qr.setPixmap(image)
        self.reset_copy_feedback()
        width = natural.width()
        height = natural.height()-self.QR_SIZE+qr_size
        corner = anchor.mapToGlobal(QPoint(anchor.width(),0))
        x = max(bounds.left(),min(corner.x()-width+self.SHADOW.right(),bounds.right()-width+1))
        above = corner.y()-height+self.SHADOW.top()
        below = corner.y()+anchor.height()-4
        y = below if above < bounds.top() else above
        y = max(bounds.top(),min(y,bounds.bottom()-height+1))
        card_bounds = QRect(x,y,width,height)
        animated = _animations_enabled()
        popup_bounds = card_bounds
        if animated and bounds.contains(card_bounds):
            popup_bounds = card_bounds.marginsAdded(self.CONFETTI_SPACE).intersected(bounds)
        padding = QMargins(
            card_bounds.left()-popup_bounds.left(),card_bounds.top()-popup_bounds.top(),
            popup_bounds.right()-card_bounds.right(),popup_bounds.bottom()-card_bounds.bottom(),
        )
        self.layout().setContentsMargins(self.SHADOW+padding)
        self.setGeometry(popup_bounds)
        self.show()
        self.layout().activate()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        if animated:
            self.confetti.setGeometry(self.rect())
            card = self.panel.geometry()
            self.confetti.start(QPointF(card.x()+card.width()/2,card.y()+min(90,card.height()*.18)))

    def mousePressEvent(self,event):
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.reject()
            event.accept()
        else:
            super().mousePressEvent(event)

    def hideEvent(self,event):
        self.confetti.stop()
        super().hideEvent(event)


class FloatBar(QWidget):
    sigPause = Signal(bool)
    sigStop = Signal()
    sigCancel = Signal()

    def __init__(self,anchor_rect_global,max_seconds=120):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setObjectName('bar')
        self.setStyleSheet(DARK)
        self.max_seconds,self.paused,self.stopping = max_seconds,False,False
        self._drag = None
        self.allow_drag = True
        row = QHBoxLayout(self)
        row.setContentsMargins(12,8,12,8)
        self.state_label = QLabel('● 录制中')
        self.time_label = QLabel('00:00.0')
        self.time_label.setMinimumWidth(120)
        self.btn_pause = button('暂停')
        self.btn_stop = button('完成录制',True)
        self.btn_cancel = button('放弃')
        for w in (self.state_label,self.time_label,self.btn_pause,self.btn_stop,self.btn_cancel): row.addWidget(w)
        self.btn_pause.clicked.connect(self.toggle_pause)
        self.btn_stop.clicked.connect(self.stop)
        self.btn_cancel.clicked.connect(self.cancel)
        self.btn_stop.setToolTip('停止并进入裁剪 · Ctrl+Shift+R')
        self.btn_pause.setToolTip('暂停 / 继续 · Ctrl+Shift+P')
        self.adjustSize()
        screen = QApplication.screenAt(anchor_rect_global.center()) or QApplication.primaryScreen()
        bound = screen.availableGeometry()
        x = anchor_rect_global.center().x()-self.width()//2
        y = anchor_rect_global.bottom()+10
        if y+self.height() > bound.bottom(): y = anchor_rect_global.top()-self.height()-10
        x = max(bound.left()+4,min(x,bound.right()-self.width()-4))
        y = max(bound.top()+4,min(y,bound.bottom()-self.height()-4))
        self.move(x,y)
        for label in (self.state_label,self.time_label):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def toggle_pause(self):
        if self.stopping: return
        self.paused = not self.paused
        self.state_label.setText('Ⅱ 已暂停' if self.paused else '● 录制中')
        self.btn_pause.setText('继续' if self.paused else '暂停')
        self.sigPause.emit(self.paused)

    def set_elapsed(self,elapsed):
        remain = max(0,int(self.max_seconds-elapsed))
        self.time_label.setText(timecode(elapsed)+(f' · 剩 {remain}s' if remain <= 10 else ''))

    def set_stopping(self):
        self.stopping = True
        self.state_label.setText('正在结束…')
        for b in (self.btn_pause,self.btn_stop,self.btn_cancel): b.setEnabled(False)

    def stop(self):
        if not self.stopping:
            self.set_stopping()
            self.sigStop.emit()

    def cancel(self):
        if self.stopping: return
        was_paused = self.paused
        if not was_paused: self.toggle_pause()
        result = QMessageBox.question(self,'放弃本次录制？','未导出的录制内容会被丢弃。',
                                      QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                                      QMessageBox.StandardButton.Cancel)
        if result == QMessageBox.StandardButton.Discard:
            self.set_stopping()
            self.sigCancel.emit()
        elif not was_paused:
            self.toggle_pause()

    def mousePressEvent(self,event):
        if self.allow_drag and event.button() == Qt.MouseButton.LeftButton:
            self._drag = event.globalPosition().toPoint()-self.pos()

    def mouseMoveEvent(self,event):
        if self._drag is not None:
            point = event.globalPosition().toPoint()-self._drag
            screen = QApplication.screenAt(event.globalPosition().toPoint()) or QApplication.primaryScreen()
            r = screen.availableGeometry()
            point.setX(max(r.left(),min(point.x(),r.right()-self.width()+1)))
            point.setY(max(r.top(),min(point.y(),r.bottom()-self.height()+1)))
            self.move(point)

    def mouseReleaseEvent(self,event):
        self._drag = None


class CountdownOverlay(QWidget):
    """A small native click-through HUD, never a frozen full-screen capture."""
    def __init__(self,region,cancel_shortcut='Ctrl+Shift+R'):
        super().__init__()
        self.remaining = 3
        self.cancel_shortcut = cancel_shortcut
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.resize(270,138)
        screen = QApplication.screenAt(region.center()) or QApplication.primaryScreen()
        bounds = screen.availableGeometry()
        x,y = region.center().x()-self.width()//2,region.center().y()-self.height()//2
        self.move(max(bounds.left(),min(x,bounds.right()-self.width()+1)),
                  max(bounds.top(),min(y,bounds.bottom()-self.height()+1)))

    def set_remaining(self,remaining):
        self.remaining = remaining
        self.update()

    def paintEvent(self,event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(30,36,45,232))
        p.drawRoundedRect(self.rect(),10,10)
        p.setPen(QColor('white'))
        p.setFont(QFont('Segoe UI',38,QFont.Weight.Bold))
        p.drawText(self.rect().adjusted(0,4,0,-59),Qt.AlignmentFlag.AlignCenter,str(self.remaining))
        p.setFont(QFont('Microsoft YaHei UI',10))
        p.drawText(self.rect().adjusted(0,75,0,-31),Qt.AlignmentFlag.AlignCenter,'可以直接点击、操作屏幕')
        p.drawText(self.rect().adjusted(0,106,0,-8),Qt.AlignmentFlag.AlignCenter,
                   self.cancel_shortcut+' / 托盘菜单取消')
        p.end()


class RecordingOutline(QWidget):
    """A click-through border strictly outside the selected capture region."""
    def __init__(self,region):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setGeometry(region.adjusted(-3,-3,3,3))

    def paintEvent(self,event):
        p = QPainter(self)
        p.setPen(QPen(QColor(SIGNAL_RED),2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(self.rect().adjusted(1,1,-2,-2))
        p.end()


class _ShadePanel(QWidget):
    """One click-through strip outside the capture rectangle."""
    def __init__(self,geometry):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowTransparentForInput |
                            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setGeometry(geometry)

    def paintEvent(self,event):
        p = QPainter(self)
        p.fillRect(self.rect(),QColor(12,17,24,105))
        p.end()


class RecordingMask:
    """Four separate strips: visible outside, physically absent over capture."""
    def __init__(self,capture_rect):
        screen = QApplication.screenAt(capture_rect.center()) or QApplication.primaryScreen()
        bounds = screen.geometry()
        capture = capture_rect.intersected(bounds)
        middle_top,middle_height = capture.top(),capture.height()
        candidates = [
            QRect(bounds.left(),bounds.top(),bounds.width(),capture.top()-bounds.top()),
            QRect(bounds.left(),capture.bottom()+1,bounds.width(),bounds.bottom()-capture.bottom()),
            QRect(bounds.left(),middle_top,capture.left()-bounds.left(),middle_height),
            QRect(capture.right()+1,middle_top,bounds.right()-capture.right(),middle_height),
        ]
        self.panels = [_ShadePanel(rect) for rect in candidates if rect.width() > 0 and rect.height() > 0]

    def show(self):
        for panel in self.panels: panel.show()

    def close(self):
        for panel in self.panels:
            panel.close()
            panel.deleteLater()
        self.panels.clear()


class FrameView(QWidget):
    def __init__(self,frames,parent=None):
        super().__init__(parent)
        self.frames,self.index,self.cache = frames,0,OrderedDict()
        self.setMinimumSize(240,120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)

    def set_frame(self,index):
        self.index = max(0,min(index,len(self.frames)-1))
        self.update()

    def paintEvent(self,event):
        key = (self.index,self.width(),self.height())
        if key not in self.cache:
            reader = QImageReader(str(self.frames[self.index]))
            reader.setScaledSize(reader.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio))
            self.cache[key] = reader.read()
            while len(self.cache) > 8: self.cache.popitem(last=False)
        img = self.cache[key]
        p = QPainter(self)
        p.fillRect(self.rect(),QColor(PREVIEW_MATTE))
        if not img.isNull():
            size = img.size().scaled(self.size(),Qt.AspectRatioMode.KeepAspectRatio)
            target = self.rect()
            target.setSize(size)
            target.moveCenter(self.rect().center())
            p.drawImage(target,img)
        p.end()


class PreviewDialog(QDialog):
    def __init__(self,frames_dir,fps,parent=None):
        super().__init__(parent)
        self.setObjectName('editor')
        self.frames_dir,self.fps = frames_dir,fps
        self.frames = sorted(Path(frames_dir).glob('f_*.png'))
        if not self.frames: raise ValueError('本次录制没有可用帧。')
        self.total,self.start,self.end,self.position = len(self.frames),0,len(self.frames),0
        self.worker,self.last_path,self.exported_range = None,'',None
        self.exported_kind,self.copied_range = None,None
        self.copy_cache = {}
        self.copy_feedback_timer = QTimer(self)
        self.copy_feedback_timer.setSingleShot(True)
        self.copy_feedback_timer.timeout.connect(self._reset_copy_feedback)
        self.setWindowTitle('Framelet · 裁剪与导出')
        self.setMinimumSize(620,510)
        screen = self.screen().availableGeometry()
        self.resize(min(1060,screen.width()-64),min(780,screen.height()-64))
        self.frame = WindowFrame(self,'裁剪与导出',maximize=True)
        stage = QFrame()
        stage.setObjectName('editorStage')
        stage.setCursor(Qt.CursorShape.ArrowCursor)
        stage_layout = QVBoxLayout(stage)
        stage_layout.setContentsMargins(16,8,16,8)
        stage_layout.setSpacing(8)
        self.frame.content.addWidget(stage,1)
        title = QLabel('录制预览')
        title.setObjectName('stageHeading')
        stage_layout.addWidget(title)
        self.view = FrameView(self.frames)
        stage_layout.addWidget(self.view,1)
        playback = QHBoxLayout()
        playback.setSpacing(8)
        self.clock = QLabel()
        self.clock.setObjectName('playbackClock')
        self.clock.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        playback.addWidget(self.clock,1)
        self.play_button = button('')
        self.play_button.setObjectName('playbackButton')
        self.play_button.setFixedSize(42,42)
        self.play_button.setIconSize(QSize(20,20))
        self.play_button.clicked.connect(self.toggle_play)
        playback.addWidget(self.play_button)
        size = QImageReader(str(self.frames[0])).size()
        meta = QLabel(f'{size.width()} × {size.height()} px · {fps} fps')
        meta.setObjectName('stageMeta')
        meta.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        meta.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Preferred)
        playback.addWidget(meta,1)
        stage_layout.addLayout(playback)

        tools = QFrame()
        tools.setObjectName('editorTools')
        tools.setCursor(Qt.CursorShape.ArrowCursor)
        root = QVBoxLayout(tools)
        root.setContentsMargins(16,12,16,12)
        root.setSpacing(7)
        self.frame.content.addWidget(tools)
        trim_header = QHBoxLayout()
        trim_title = QLabel('裁剪片段')
        trim_title.setObjectName('trimHeading')
        trim_header.addWidget(trim_title)
        tip = QLabel('拖动两端调整范围')
        tip.setObjectName('muted')
        trim_header.addWidget(tip)
        trim_header.addStretch()
        self.duration_label = QLabel()
        self.duration_label.setObjectName('trimDuration')
        trim_header.addWidget(self.duration_label)
        root.addLayout(trim_header)
        self.timeline = TrimTimeline(self.frames,fps)
        self.timeline.rangeChanged.connect(self.set_range)
        self.timeline.seek.connect(self.seek)
        root.addWidget(self.timeline)
        self.progress = QProgressBar()
        self.progress.setRange(0,0)
        self.progress.setTextVisible(False)
        self.progress.hide()
        root.addWidget(self.progress)
        self.status = QLabel('GIF 最长边 960 px · MP4 保留录制分辨率')
        self.status.setObjectName('muted')
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        status_row = QHBoxLayout()
        status_row.addWidget(self.status,1)
        self.cancel_button = button('取消导出')
        self.cancel_button.clicked.connect(self.cancel_export)
        self.cancel_button.hide()
        status_row.addWidget(self.cancel_button)
        root.addLayout(status_row)
        divider = QFrame()
        divider.setObjectName('settingsDivider')
        divider.setFixedHeight(1)
        root.addWidget(divider)
        footer = QHBoxLayout()
        footer.setSpacing(8)
        self.footer = footer
        self.close_button = button('关闭')
        self.close_button.clicked.connect(self.close)
        footer.addWidget(self.close_button)
        self.open_button = button('打开文件夹')
        self.open_button.setToolTip('打开导出文件夹')
        self.open_button.hide()
        self.open_button.clicked.connect(self.open_folder)
        footer.addWidget(self.open_button)
        footer.addStretch()
        self.format = StyledComboBox(prefer_above=True)
        self.format.setMinimumWidth(120)
        self.format.addItem('GIF 动图','gif')
        self.format.addItem('MP4 视频','mp4')
        self.format.setAccessibleName('导出格式')
        self.format.currentIndexChanged.connect(self._reset_copy_feedback)
        footer.addWidget(self.format)
        self.export_button = button('导出片段…')
        self.export_button.clicked.connect(self.export)
        footer.addWidget(self.export_button)
        self.support_button = SupportButton()
        footer.addWidget(self.support_button)
        self.copy_button = button('复制',True)
        self.copy_button.setAccessibleName('复制文件')
        self.copy_button.setMinimumWidth(84)
        self.copy_button.setToolTip('按当前裁剪和格式生成文件并复制，无需先导出')
        self.copy_button.clicked.connect(self.copy_export)
        footer.addWidget(self.copy_button)
        root.addLayout(footer)
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(max(1,round(1000/fps)))
        self.timer.timeout.connect(self.advance)
        self.space = QShortcut(QKeySequence('Space'),self)
        self.space.activated.connect(self.toggle_play)
        self.set_range(0,self.total)
        self.play_button.setFocus()

    def set_range(self,start,end):
        if self.worker: return
        self.pause()
        self._reset_copy_feedback()
        old_start,old_end = self.start,self.end
        self.start = max(0,min(start,self.total-1))
        self.end = max(self.start+1,min(end,self.total))
        self.timeline.set_range(self.start,self.end)
        self.duration_label.setText(f'保留 {(self.end-self.start)/self.fps:.2f} 秒')
        if self.start != old_start:
            position = self.start
        elif self.end != old_end:
            position = self.end-1
        else:
            position = min(self.end-1,max(self.start,self.position))
        self.show_frame(position)
        if self.last_path and self.exported_range != (self.start,self.end):
            self.status.setText('裁剪已调整，当前片段尚未导出。之前导出的文件不受影响。')
        elif self.copied_range and self.copied_range != (self.start,self.end):
            self.status.setText('裁剪已调整，点击“复制”可复制新片段。')

    def show_frame(self,index):
        self.position = index
        self.view.set_frame(index)
        self.timeline.position = index
        self.timeline.update()
        self.clock.setText(f'{timecode(index/self.fps)} / {timecode(self.total/self.fps)}')

    def seek(self,index):
        self.pause()
        self.show_frame(index)

    def pause(self):
        self.timer.stop()
        self._set_playback_icon(False)

    def _set_playback_icon(self,playing):
        name,label = ('pause','暂停播放') if playing else ('play','播放片段')
        self.play_button.setIcon(lucide_icon(name,LIGHT_INK,20,filled=True))
        self.play_button.setAccessibleName(label)
        self.play_button.setToolTip(f'{label}（空格）')

    def toggle_play(self):
        if self.worker: return
        if self.timer.isActive(): self.pause()
        else:
            if not self.start <= self.position < self.end-1: self.show_frame(self.start)
            self.timer.start()
            self._set_playback_icon(True)

    def advance(self):
        self.show_frame(self.start if self.position+1 >= self.end else self.position+1)

    def export(self):
        if self.worker: return
        self.pause()
        kind = self.format.currentData()
        filename = f"Framelet-{datetime.now():%Y%m%d-%H%M%S}.{kind}"
        path,_ = QFileDialog.getSaveFileName(self,'导出选中片段',filename,f'{kind.upper()} (*.{kind})')
        if not path: return
        if not path.lower().endswith('.'+kind):
            path += '.'+kind
            if Path(path).exists() and QMessageBox.question(self,'替换文件？',f'文件已存在，是否替换？\n{path}') != QMessageBox.StandardButton.Yes:
                return
        self._start_export(path,kind,'export')

    def _start_export(self,path,kind,operation):
        self.pause()
        self._reset_copy_feedback()
        self._export_range = (self.start,self.end)
        self._export_kind,self._operation = kind,operation
        self.worker = ExportWorker(self.frames_dir,self.fps,path,self.start,self.end,kind,self)
        self.worker.finished.connect(self._export_finished)
        self.cancel_button.setText('取消复制' if operation == 'copy' else '取消导出')
        self._busy(True)
        action = '正在生成待复制文件' if operation == 'copy' else '正在导出'
        if operation == 'copy': self.copy_button.setText('生成中…')
        self.status.setText(f'{action} {kind.upper()} · 保留 {(self.end-self.start)/self.fps:.2f} 秒，可随时取消…')
        self.worker.start()

    def _busy(self,busy):
        for w in (self.timeline,self.format,self.export_button,self.play_button,self.copy_button):
            w.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(True)

    def cancel_export(self):
        if self.worker:
            self.worker.cancel()
            self.cancel_button.setEnabled(False)
            self.status.setText('正在取消，原始录制不会丢失…')

    def _export_finished(self):
        worker,self.worker = self.worker,None
        self._busy(False)
        self._reset_copy_feedback()
        action = '复制' if self._operation == 'copy' else '导出'
        if worker.cancelled:
            self.status.setText(f'已取消{action}，可调整裁剪后重试。')
        elif worker.error:
            self.status.setText(f'{action}失败，录制已保留。请检查保存位置和磁盘空间后重试。')
            QMessageBox.warning(self,action+'失败',worker.error)
        elif self._operation == 'copy':
            key = (self._export_kind,*self._export_range)
            self.copy_cache[key] = worker.path
            self._copy_path(worker.path)
        else:
            self.last_path,self.exported_range = worker.path,self._export_range
            self.exported_kind = self._export_kind
            self.status.setText('已保存：'+worker.path+'\n可继续导出另一种格式。')
            self.open_button.show()
            self.copy_button.setEnabled(True)
        worker.deleteLater()

    def open_folder(self):
        if self.last_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.last_path).parent)))

    def copy_export(self):
        if self.worker: return
        self.pause()
        kind = self.format.currentData()
        key = (kind,self.start,self.end)
        path = self.copy_cache.get(key)
        if not path or not Path(path).is_file():
            path = (self.last_path if self.exported_range == (self.start,self.end)
                    and self.exported_kind == kind else None)
        if path and Path(path).is_file():
            self._copy_path(path)
            return
        try:
            path = clipboard_cache_path(kind)
        except Exception as exc:
            self.status.setText('无法创建复制文件，录制已保留。请检查临时目录空间和权限。')
            QMessageBox.warning(self,'复制失败',str(exc))
            return
        self._start_export(path,kind,'copy')

    def _reset_copy_feedback(self):
        self.copy_feedback_timer.stop()
        self.copy_button.setText('复制')

    def _copy_path(self,path):
        self._reset_copy_feedback()
        try:
            copy_file_to_clipboard(path)
            self.copied_range = (self.start,self.end)
            self.status.setText('已复制文件：'+path+'\n关闭窗口后仍可粘贴到资源管理器或支持文件粘贴的聊天窗口。')
            self.copy_button.setText('已复制 ✓')
            self.copy_feedback_timer.start(1400)
        except Exception as exc:
            self.status.setText('复制失败，文件和录制已保留。请再次点击“复制”重试。')
            QMessageBox.warning(self,'复制失败',str(exc))

    def can_close(self):
        if self.worker:
            self.status.setText('正在生成文件，请等待完成或先点击取消按钮。')
            return False
        if (self.start,self.end) not in (self.exported_range,self.copied_range):
            result = QMessageBox.question(self,'关闭裁剪窗口？','当前片段尚未导出或复制。关闭后将丢弃本次原始录制。',
                QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,QMessageBox.StandardButton.Cancel)
            return result == QMessageBox.StandardButton.Discard
        return True

    def closeEvent(self,event):
        if self.can_close():
            self.pause()
            event.accept()
            self.done(0)
        else: event.ignore()

    def reject(self):
        self.close()
