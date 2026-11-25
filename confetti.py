"""Short, click-through confetti layer for the author support popup."""

from dataclasses import dataclass
from math import expm1, log
from random import choice, uniform

from PySide6.QtCore import QElapsedTimer, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget


COLORS = tuple(QColor(color) for color in (
    '#FF2E17', '#FFB400', '#00C9A7', '#2E7BFF',
    '#9B4DFF', '#FF4F9A', '#79D70F', '#FF6A00',
))
SHAPES = (
    ((0, -.5), (.5, 0), (0, .5), (-.5, 0)),
    ((-.28, -.5), (.5, -.5), (.28, .5), (-.5, .5)),
    ((-.32, -.5), (.32, -.5), (.5, .5), (-.5, .5)),
    ((-.5, -.5), (.5, -.5), (.5, .5), (-.5, .5)),
)
GRAVITY = 1900
DRAG = -60 * log(.992)


@dataclass(frozen=True)
class ConfettiPiece:
    shape: QPolygonF
    color: QColor
    vx: float
    vy: float
    angle: float
    spin: float
    lifetime: float


class ConfettiLayer(QWidget):
    def __init__(self,parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()
        self.pieces = []
        self.origin = QPointF()
        self.clock = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    def start(self,origin):
        self.origin = origin
        self.pieces = []
        for index in range(110):
            width = uniform(6,13)
            height = width*uniform(.6,1.4)
            shape = QPolygonF([QPointF(x*width,y*height) for x,y in choice(SHAPES)])
            direction = -1 if index % 2 == 0 else 1
            self.pieces.append(ConfettiPiece(
                shape,choice(COLORS),direction*uniform(60,490)+uniform(-40,40),
                -uniform(520,1010),uniform(0,360),uniform(-450,450),uniform(1.5,2.4),
            ))
        self.duration = max(piece.lifetime for piece in self.pieces)
        self.clock.start()
        self.show()
        self.timer.start()

    def stop(self):
        self.timer.stop()
        self.pieces.clear()
        self.hide()

    def _tick(self):
        if self.clock.elapsed()/1000 >= self.duration:
            self.stop()
        else:
            self.update()

    def paintEvent(self,event):
        if not self.pieces:
            return
        age = self.clock.elapsed()/1000
        # Integrate horizontal drag continuously so travel is independent of the refresh rate.
        travel = -expm1(-DRAG*age)/DRAG
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        for piece in self.pieces:
            if age >= piece.lifetime:
                continue
            painter.save()
            painter.translate(self.origin.x()+piece.vx*travel,
                              self.origin.y()+age*(piece.vy+GRAVITY*age/2))
            painter.rotate(piece.angle+age*piece.spin)
            painter.setOpacity(min(1.0,(piece.lifetime-age)/(.3*piece.lifetime)))
            painter.setBrush(piece.color)
            painter.drawPolygon(piece.shape)
            painter.restore()
        painter.end()
