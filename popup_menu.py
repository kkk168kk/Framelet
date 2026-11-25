"""Shared presentation for Framelet menus, with QMenu handling input and actions."""
from PySide6.QtCore import QMargins, QRect, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QMenu

from lucide_icons import lucide_icon
from theme import ACCENT_HOVER_WASH, ACCENT_TEXT, ACCENT_WASH, BORDER, DISABLED_INK, INK, SURFACE


class PopupMenu(QMenu):
    SHADOW = QMargins(6, 5, 6, 7)
    ICON_SIZE = 16
    ICON_GAP = 8
    ROW_INSET = 9

    def __init__(self, parent=None, *, choices=False):
        super().__init__(parent)
        self.choices = choices
        self.check = lucide_icon('check', ACCENT_TEXT, self.ICON_SIZE) if choices else None
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        # Let QMenu use its own row sizing and hit testing inside the panel.
        icon_space = self.ICON_SIZE + self.ICON_GAP
        text_inset = self.ROW_INSET * 2 + icon_space
        self.setStyleSheet(f'''
            QMenu {{
                padding: {self.SHADOW.top() + 5}px {self.SHADOW.right() + 5}px
                         {self.SHADOW.bottom() + 5}px {self.SHADOW.left() + 5}px;
                border: none;
            }}
            QMenu::item {{ padding: 8px {text_inset}px 8px 0; }}
            QMenu::separator {{ height: 7px; }}
        ''')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(event.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        panel = QRectF(self.rect().marginsRemoved(self.SHADOW)).adjusted(.5, .5, -.5, -.5)
        radius = 11
        painter.setPen(Qt.PenStyle.NoPen)
        for spread in (4, 3, 2, 1, 0):
            shadow = panel.adjusted(-spread, -spread, spread, spread).translated(0, 2)
            painter.setBrush(QColor(28, 32, 37, 8 if spread > 1 else 13))
            painter.drawRoundedRect(shadow, radius + spread, radius + spread)
        painter.setBrush(QColor(SURFACE))
        painter.setPen(QPen(QColor(BORDER), 1))
        painter.drawRoundedRect(panel, radius, radius)

        for action in self.actions():
            if not action.isVisible():
                continue
            row = self.actionGeometry(action)
            if action.isSeparator():
                painter.setPen(QColor(BORDER))
                painter.drawLine(row.left() + self.ROW_INSET, row.center().y(),
                                 row.right() - self.ROW_INSET, row.center().y())
                continue
            self._paint_row(painter, row, action)
        painter.end()

    def _paint_row(self, painter, row, action):
        enabled = action.isEnabled()
        active = enabled and self.activeAction() is action
        checked = self.choices and action.isChecked()
        if active or checked:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(ACCENT_HOVER_WASH if active else ACCENT_WASH))
            painter.drawRoundedRect(QRectF(row).adjusted(0, 1, 0, -1), 7, 7)

        text_rect = row.adjusted(self.ROW_INSET, 0, -self.ROW_INSET, 0)
        icon_y = row.y() + (row.height() - self.ICON_SIZE) // 2
        icon_mode = QIcon.Mode.Normal if enabled else QIcon.Mode.Disabled
        if self.choices:
            if checked:
                icon_x = text_rect.right() - self.ICON_SIZE + 1
                self.check.paint(painter, QRect(icon_x, icon_y, self.ICON_SIZE, self.ICON_SIZE),
                                 mode=icon_mode)
            text_rect.adjust(0, 0, -self.ICON_SIZE - self.ICON_GAP, 0)
        else:
            action.icon().paint(painter, QRect(text_rect.x(), icon_y, self.ICON_SIZE, self.ICON_SIZE),
                                mode=icon_mode)
            text_rect.adjust(self.ICON_SIZE + self.ICON_GAP, 0, 0, 0)

        color = DISABLED_INK if not enabled else ACCENT_TEXT if active or checked else INK
        painter.setPen(QColor(color))
        painter.setFont(self.font())
        label = painter.fontMetrics().elidedText(action.text(), Qt.TextElideMode.ElideRight,
                                                 text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
