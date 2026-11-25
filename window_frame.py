"""Framelet's caption controls and frameless window interaction."""

from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
from theme import LIGHT_INK


class CaptionButton(QPushButton):
    def __init__(self, glyph, label):
        super().__init__()
        self.glyph = glyph
        self.setObjectName('captionClose' if glyph == 'close' else 'captionButton')
        self.setFixedSize(34, 30)
        self.setAutoDefault(False)
        self.setToolTip(label)
        self.setAccessibleName(label)

    def event(self, event):
        if (event.type() == QEvent.Type.ShortcutOverride and event.key() == Qt.Key.Key_Space
                and event.modifiers() == Qt.KeyboardModifier.NoModifier):
            event.accept()
            return True
        return super().event(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        pen = QPen(QColor(LIGHT_INK), 1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        if self.glyph == 'close':
            painter.drawLine(-4, -4, 4, 4)
            painter.drawLine(-4, 4, 4, -4)
        elif self.glyph == 'minimize':
            painter.drawLine(-5, 1, 5, 1)
        elif self.glyph == 'restore':
            painter.drawLine(-2, -6, 6, -6)
            painter.drawLine(6, -6, 6, 2)
            painter.drawRect(QRectF(-5, -3, 8, 8))
        else:
            painter.drawRect(QRectF(-5, -5, 10, 10))
        painter.end()


class WindowTitleBar(QFrame):
    def __init__(self, window, section, maximize):
        super().__init__()
        self.host = window
        self.drag_start = None
        self.drag_offset = None
        self.setObjectName('windowTitleBar')
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self.setFixedHeight(46)
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 0, 8, 0)
        row.setSpacing(3)

        icon = window.windowIcon()
        if icon.isNull():
            icon = QIcon(str(Path(__file__).with_name('Framelet.png')))
        logo = QLabel()
        logo.setPixmap(icon.pixmap(QSize(22, 22), window.devicePixelRatioF()))
        logo.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(logo)
        row.addSpacing(7)
        for text, name in (('Framelet', 'captionBrand'), (section, 'captionSection')):
            label = QLabel(text)
            label.setObjectName(name)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            row.addWidget(label)
            row.addSpacing(10)
        row.addStretch()

        self.minimize_button = CaptionButton('minimize', '最小化')
        self.minimize_button.clicked.connect(window.showMinimized)
        row.addWidget(self.minimize_button)
        self.maximize_button = None
        if maximize:
            self.maximize_button = CaptionButton('maximize', '最大化')
            self.maximize_button.clicked.connect(self.toggle_maximized)
            row.addWidget(self.maximize_button)
        self.close_button = CaptionButton('close', '关闭窗口')
        self.close_button.clicked.connect(window.close)
        row.addWidget(self.close_button)

    def toggle_maximized(self):
        if self.host.isMaximized():
            self.host.showNormal()
        else:
            self.host.showMaximized()

    def sync_state(self):
        if self.maximize_button is not None:
            maximized = self.host.isMaximized()
            label = '还原' if maximized else '最大化'
            self.maximize_button.glyph = 'restore' if maximized else 'maximize'
            self.maximize_button.setToolTip(label)
            self.maximize_button.setAccessibleName(label)
            self.maximize_button.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = event.globalPosition().toPoint()
            self.drag_offset = self.drag_start - self.host.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_offset is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return
        position = event.globalPosition().toPoint()
        if self.drag_start is not None:
            if (position - self.drag_start).manhattanLength() < QApplication.startDragDistance():
                return
            self.drag_start = None
            handle = self.host.windowHandle()
            if (handle and handle.startSystemMove()) or self.host.isMaximized():
                self.drag_offset = None
                return
        self.host.move(position - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_start = None
        self.drag_offset = None

    def mouseDoubleClickEvent(self, event):
        if self.maximize_button is not None and event.button() == Qt.MouseButton.LeftButton:
            self.drag_start = None
            self.drag_offset = None
            self.toggle_maximized()
            event.accept()


class WindowFrame(QFrame):
    EDGE = 5

    def __init__(self, window, section, *, maximize=False):
        super().__init__(window)
        self.host = window
        self.resize_start = None
        self.setObjectName('windowFrame')
        self.setMouseTracking(True)
        self.host.setWindowFlag(Qt.WindowType.FramelessWindowHint)
        self.host.setWindowFlag(Qt.WindowType.WindowMinimizeButtonHint)
        if maximize:
            self.host.setWindowFlag(Qt.WindowType.WindowMaximizeButtonHint)
        outer = QVBoxLayout(window)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self)
        self.content = QVBoxLayout(self)
        self.content.setSpacing(0)
        self.title_bar = WindowTitleBar(window, section, maximize)
        self.content.addWidget(self.title_bar)
        self._sync_state()
        self.host.installEventFilter(self)

    def _sync_state(self):
        edge = 0 if self.host.isMaximized() else self.EDGE
        self.content.setContentsMargins(edge, edge, edge, edge)
        self.title_bar.sync_state()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.WindowStateChange and watched is getattr(self, 'host', None):
            self._sync_state()
        return super().eventFilter(watched, event)

    def _edges_at(self, point):
        edges = Qt.Edge(0)
        if not self.host.isMaximized():
            if point.x() < self.EDGE:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - self.EDGE:
                edges |= Qt.Edge.RightEdge
            if point.y() < self.EDGE:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - self.EDGE:
                edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event):
        edges = self._edges_at(event.position())
        if event.button() == Qt.MouseButton.LeftButton and edges:
            handle = self.host.windowHandle()
            if not (handle and handle.startSystemResize(edges)):
                self.resize_start = edges, event.globalPosition().toPoint(), self.host.geometry()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.resize_start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            edges, start, original = self.resize_start
            delta = event.globalPosition().toPoint() - start
            rect = QRect(original)
            minimum = self.host.minimumSize().expandedTo(self.host.minimumSizeHint())
            if edges & Qt.Edge.LeftEdge:
                rect.setLeft(min(original.left() + delta.x(), rect.right() - minimum.width() + 1))
            if edges & Qt.Edge.RightEdge:
                rect.setRight(max(original.right() + delta.x(), rect.left() + minimum.width() - 1))
            if edges & Qt.Edge.TopEdge:
                rect.setTop(min(original.top() + delta.y(), rect.bottom() - minimum.height() + 1))
            if edges & Qt.Edge.BottomEdge:
                rect.setBottom(max(original.bottom() + delta.y(), rect.top() + minimum.height() - 1))
            self.host.setGeometry(rect)
            return
        edges = self._edges_at(event.position())
        cursors = {
            Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
            Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
            Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
            Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
            Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
        }
        self.setCursor(cursors.get(edges, Qt.CursorShape.ArrowCursor))

    def mouseReleaseEvent(self, event):
        self.resize_start = None

    def leaveEvent(self, event):
        self.unsetCursor()
        super().leaveEvent(event)
