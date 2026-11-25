"""Live per-monitor selection: transparent overlay over the live desktop."""
from PySide6.QtCore import Qt, QRect, QPoint, QRectF, Signal, QTimer
from PySide6.QtGui import QPainter, QColor, QPen, QFont
from PySide6.QtWidgets import QWidget, QHBoxLayout, QLabel
from capture_geometry import physical_region
from theme import DARK, SIGNAL_RED, button


class SnipOverlay(QWidget):
    sigAbort = Signal()
    sigCountdownStart = Signal(object, object)
    sigSelected = Signal(object)

    MAGNIFY_ZOOM = 8
    MAGNIFY_CELLS = 15

    def __init__(self, screen, monitor, background=None, detector=None):
        super().__init__()
        self.screen_info, self.monitor = screen, monitor
        self.background, self.detector = background, detector
        self.cursor_pos = None
        self.detected = QRect()
        # Detect only after the cursor settles; keeps hover highlighting smooth.
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(80)
        self._hover_timer.timeout.connect(self._detect_settled)
        if detector is not None and hasattr(detector,'detected'):
            detector.detected.connect(self._on_detected)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setGeometry(screen.geometry())
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.sel = QRect()
        self.state, self.mode, self.handle = 'select', None, ''
        self.origin, self.original = QPoint(), QRect()
        self.bar = QWidget(self)
        self.bar.setObjectName('bar')
        self.bar.setStyleSheet(DARK)
        row = QHBoxLayout(self.bar)
        row.setContentsMargins(10, 8, 10, 8)
        self.size_label = QLabel()
        row.addWidget(self.size_label)
        for text, callback, primary in [('开始录制  ↵', self.begin, True),
                                        ('取消  Esc', self.abort, False)]:
            b = button(text, primary)
            b.clicked.connect(callback)
            row.addWidget(b)
        self.bar.hide()
        self.setWindowTitle('Framelet · 选择录制区域')

    def reset(self):
        self.state, self.mode = 'select', None
        self.sel = QRect()
        self.detected = QRect()
        self._hover_timer.stop()
        self.bar.hide()
        self.update()

    def abort(self):
        self.sigAbort.emit()

    def _physical_at(self, pos):
        sx = self.monitor['width']/max(1,self.width())
        sy = self.monitor['height']/max(1,self.height())
        return (self.monitor['left']+round(pos.x()*sx),
                self.monitor['top']+round(pos.y()*sy))

    def _apply_detected(self, rect):
        local = QRect()
        if rect:
            l,t,r,b = rect
            sx = self.monitor['width']/max(1,self.width())
            sy = self.monitor['height']/max(1,self.height())
            local = QRect(round((l-self.monitor['left'])/sx),round((t-self.monitor['top'])/sy),
                          round((r-l)/sx),round((b-t)/sy)).intersected(self.rect())
            # A monitor-sized hit is the desktop itself, not a useful element.
            if local == self.rect():
                local = QRect()
        if local != self.detected:
            self.detected = local
            self.update()

    def _detect_settled(self):
        pos = self.cursor_pos
        if pos is None or not self.detector or self.state != 'select' or self.mode is not None:
            return
        x,y = self._physical_at(pos)
        if hasattr(self.detector,'request'):
            self.detector.request(self,x,y)
            return
        self._detect_at(pos)

    def _on_detected(self, requester, rect):
        if requester is not self:
            return
        if self.state != 'select' or self.mode is not None:
            return
        self._apply_detected(rect)

    def _detect_at(self, pos):
        if not self.detector or self.state != 'select' or self.mode is not None:
            return
        x,y = self._physical_at(pos)
        if hasattr(self.detector,'request'):
            self.detector.request(self,x,y)
            return
        try:
            rect = self.detector.rect_at(x,y)
        except Exception:
            rect = None
        self._apply_detected(rect)

    def begin(self):
        if self.state != 'ready':
            return
        self.state = 'done'
        self.bar.hide()
        region = physical_region(self.sel, self.size(), self.monitor)
        self.sigCountdownStart.emit(region, self.sel.translated(self.geometry().topLeft()))

    def handles(self):
        r, c = self.sel, self.sel.center()
        return {'tl':r.topLeft(), 't':QPoint(c.x(),r.top()), 'tr':r.topRight(),
                'r':QPoint(r.right(),c.y()), 'br':r.bottomRight(),
                'b':QPoint(c.x(),r.bottom()), 'bl':r.bottomLeft(), 'l':QPoint(r.left(),c.y())}

    def hit(self, pos):
        if self.state == 'ready':
            for name, p in self.handles().items():
                if abs(p.x()-pos.x()) <= 8 and abs(p.y()-pos.y()) <= 8:
                    return name
        return ''

    def mousePressEvent(self, event):
        self._hover_timer.stop()
        if event.button() == Qt.MouseButton.RightButton:
            self.abort()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.state == 'done':
            return
        pos = event.position().toPoint()
        self.origin, self.original = pos, QRect(self.sel)
        # Snipaste-style: a click inside the detected element adopts it, while
        # a real drag still starts a free-form selection.
        if (self.state == 'select' and self.detected.isValid()
                and self.detected.contains(pos)):
            self.mode = 'maybe-adopt'
            self.update()
            return
        self.handle = self.hit(pos)
        if self.handle:
            self.mode = 'resize'
        elif self.state == 'ready' and self.sel.contains(pos):
            self.mode = 'move'
        else:
            self.sigSelected.emit(self)
            self.state, self.mode, self.sel = 'select', 'new', QRect(pos,pos)
            self.detected = QRect()
        self.bar.hide()
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        pos.setX(max(0,min(self.width()-1,pos.x())))
        pos.setY(max(0,min(self.height()-1,pos.y())))
        self.cursor_pos = pos
        if self.mode == 'maybe-adopt':
            if (pos-self.origin).manhattanLength() <= 4:
                self.update()
                return
            self.sigSelected.emit(self)
            self.mode = 'new'
            self.sel = QRect(self.origin,pos)
            self.detected = QRect()
        if self.mode == 'new':
            self.sel = QRect(self.origin,pos).normalized()
        elif self.mode == 'move':
            r = self.original.translated(pos-self.origin)
            r.moveLeft(max(0,min(self.width()-r.width(),r.x())))
            r.moveTop(max(0,min(self.height()-r.height(),r.y())))
            self.sel = r
        elif self.mode == 'resize':
            r = QRect(self.original)
            if 'l' in self.handle: r.setLeft(min(pos.x(),r.right()-15))
            if 'r' in self.handle: r.setRight(max(pos.x(),r.left()+15))
            if 't' in self.handle: r.setTop(min(pos.y(),r.bottom()-15))
            if 'b' in self.handle: r.setBottom(max(pos.y(),r.top()+15))
            self.sel = r.intersected(self.rect())
        else:
            if self.state == 'select' and self.detector:
                self._hover_timer.start()
            h = self.hit(pos)
            cursor = (Qt.CursorShape.SizeFDiagCursor if h in ('tl','br') else
                      Qt.CursorShape.SizeBDiagCursor if h in ('tr','bl') else
                      Qt.CursorShape.SizeVerCursor if h in ('t','b') else
                      Qt.CursorShape.SizeHorCursor if h in ('l','r') else
                      Qt.CursorShape.SizeAllCursor if self.sel.contains(pos) else
                      Qt.CursorShape.CrossCursor)
            self.setCursor(cursor)
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.mode:
            return
        if self.mode == 'maybe-adopt':
            self.mode = None
            self.sel = QRect(self.detected)
            self.detected = QRect()
            self.sigSelected.emit(self)
            if self.sel.width() >= 16 and self.sel.height() >= 16:
                self.state = 'ready'
                self._place_bar()
            else:
                self.reset()
            self.update()
            return
        self.mode = None
        if self.sel.width() >= 16 and self.sel.height() >= 16:
            self.state = 'ready'
            self._place_bar()
        else:
            self.reset()
        self.update()

    def _place_bar(self):
        r = physical_region(self.sel,self.size(),self.monitor)
        self.size_label.setText(f"{r['width']} × {r['height']} px")
        self.bar.adjustSize()
        x = self.sel.right()+1-self.bar.width()
        x = max(8,min(x,self.width()-self.bar.width()-8))
        y = self.sel.bottom()+12
        if y+self.bar.height() > self.height()-8:
            y = self.sel.top()-self.bar.height()-12
        self.bar.move(x,max(8,min(y,self.height()-self.bar.height()-8)))
        self.bar.show()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.abort()
        elif event.key() in (Qt.Key.Key_Return,Qt.Key.Key_Enter):
            self.begin()
        elif event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right,Qt.Key.Key_Up,Qt.Key.Key_Down) and self.state == 'ready':
            step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
            delta = {Qt.Key.Key_Left:(-step,0),Qt.Key.Key_Right:(step,0),
                     Qt.Key.Key_Up:(0,-step),Qt.Key.Key_Down:(0,step)}[event.key()]
            r = self.sel.translated(*delta)
            r.moveLeft(max(0,min(self.width()-r.width(),r.x())))
            r.moveTop(max(0,min(self.height()-r.height(),r.y())))
            self.sel = r
            self._place_bar()
            self.update()

    def paintEvent(self, event):
        # Do not paint a screenshot. This keeps whatever is behind the selection
        # overlay live while the user chooses a region.
        p = QPainter(self)
        p.fillRect(self.rect(),QColor(12,17,24,105))
        # Selected (or auto-detected) area stays a transparent window into the
        # live desktop. NOTE: the hole must keep alpha=1 — fully transparent
        # pixels of a layered window are click-through on Windows, which would
        # drop presses inside the detected region onto the app below.
        highlight = self.sel if self.sel.isValid() else self.detected
        if highlight.isValid():
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
            p.fillRect(highlight,QColor(0,0,0,1))
            p.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        if self.sel.isValid():
            p.setPen(QPen(QColor(SIGNAL_RED),2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.sel.adjusted(0,0,-1,-1))
            if self.state == 'ready':
                p.setBrush(QColor('white'))
                for point in self.handles().values():
                    p.drawRect(QRect(point.x()-4,point.y()-4,8,8))
        elif self.detected.isValid():
            p.setPen(QPen(QColor(SIGNAL_RED),1))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.detected.adjusted(0,0,-1,-1))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRect(max(8,(self.width()-660)//2),22,min(660,self.width()-16),42)
        p.setPen(QPen(QColor(69,77,90,180),1))
        p.setBrush(QColor(32,36,45,235))
        p.drawRoundedRect(box,21,21)
        p.setPen(QColor('#EEF1F5'))
        p.setFont(QFont('Microsoft YaHei UI',11))
        p.drawText(box,Qt.AlignmentFlag.AlignCenter,'Framelet · 拖动框选录制区域 · 单击高亮处选中 · 每次录制一块屏幕 · Esc 取消')
        self._paint_magnifier(p)
        p.end()

    def _paint_magnifier(self, p):
        """Snipaste-style pixel loupe: magnified snapshot around the cursor.

        Visible during the whole selection phase, including while dragging —
        that is when pixel precision matters most.
        """
        if (self.background is None or self.cursor_pos is None
                or self.state == 'done'):
            return
        zoom,cells = self.MAGNIFY_ZOOM,self.MAGNIFY_CELLS
        size = zoom*cells
        sx = self.background.width()/max(1,self.width())
        sy = self.background.height()/max(1,self.height())
        cx,cy = self.cursor_pos.x()*sx,self.cursor_pos.y()*sy
        x,y = self.cursor_pos.x()+18,self.cursor_pos.y()+18
        if x+size+6 > self.width(): x = self.cursor_pos.x()-size-24
        if y+size+32 > self.height(): y = self.cursor_pos.y()-size-50
        x = max(4,min(x,self.width()-size-6))
        y = max(4,min(y,self.height()-size-32))
        half = cells//2
        p.setPen(QPen(QColor('#4B5360'),1))
        p.setBrush(QColor('#252A32'))
        p.drawRoundedRect(QRectF(x-2,y-2,size+4,size+30),6,6)
        p.drawImage(QRectF(x,y,size,size),self.background,
                    QRectF(cx-half,cy-half,cells,cells))
        p.setPen(QPen(QColor(255,255,255,36),1))
        for i in range(1,cells):
            p.drawLine(x+i*zoom,y,x+i*zoom,y+size)
            p.drawLine(x,y+i*zoom,x+size,y+i*zoom)
        center = half*zoom
        p.setPen(QPen(QColor(SIGNAL_RED),1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRect(x+center,y+center,zoom,zoom))
        px = max(0,min(int(round(cx)),self.background.width()-1))
        py = max(0,min(int(round(cy)),self.background.height()-1))
        color = self.background.pixelColor(px,py).name()
        p.setPen(QColor('white'))
        p.setFont(QFont('Microsoft YaHei UI',9))
        info = f"{self.monitor['left']+px}, {self.monitor['top']+py}  {color}"
        p.drawText(QRect(x,y+size+5,size,18),Qt.AlignmentFlag.AlignCenter,info)
