"""A frame-indexed, two-handle trim timeline; end is exclusive."""
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QImage
from PySide6.QtWidgets import QWidget
from theme import ACCENT, FOCUS, INK, LIGHT_INK, MUTED


def timecode(seconds):
    minutes, seconds = divmod(max(0,seconds),60)
    return f'{int(minutes):02d}:{seconds:04.1f}'


class TrimTimeline(QWidget):
    rangeChanged = Signal(int,int)
    seek = Signal(int)

    def __init__(self,frames,fps,parent=None):
        super().__init__(parent)
        self.total,self.fps = len(frames),fps
        self.start,self.end,self.position = 0,self.total,0
        self.drag = None
        self.setMinimumHeight(100)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName('裁剪时间轴；拖动两端裁剪，左右键逐帧定位')
        self.setToolTip('拖动两端裁剪；点击中间预览；左右键逐帧定位')
        self.thumbs = []
        for i in range(min(10,self.total)):
            index = round(i*(self.total-1)/max(1,min(10,self.total)-1))
            self.thumbs.append(QImage(str(frames[index])).scaled(
                192,96,Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def frame_x(self,index):
        return 14+index/max(1,self.total)*(self.width()-28)

    def frame_at(self,x):
        return max(0,min(self.total,round((x-14)/max(1,self.width()-28)*self.total)))

    def set_range(self,start,end):
        self.start = max(0,min(int(start),self.total-1))
        self.end = max(self.start+1,min(int(end),self.total))
        self.update()

    def paintEvent(self,event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        track = QRectF(14,14,self.width()-28,54)
        clip = QPainterPath()
        clip.addRoundedRect(track,5,5)
        p.save()
        p.setClipPath(clip)
        p.fillRect(track,QColor(INK))
        width = track.width()/max(1,len(self.thumbs))
        for i,img in enumerate(self.thumbs):
            cell = QRectF(14+i*width,14,width,54)
            if not img.isNull():
                size = cell.size().scaled(QSizeF(img.size()),Qt.AspectRatioMode.KeepAspectRatio)
                source = QRectF(QPointF(),size)
                source.moveCenter(QRectF(img.rect()).center())
                p.drawImage(cell,img,source)
            if i:
                p.setPen(QColor(33,27,26,132))
                p.drawLine(cell.topLeft(),cell.bottomLeft())
        a,b = self.frame_x(self.start),self.frame_x(self.end)
        shade = QColor(INK)
        shade.setAlpha(154)
        p.fillRect(QRectF(14,14,max(0,a-14),54),shade)
        p.fillRect(QRectF(b,14,max(0,self.width()-14-b),54),shade)
        p.restore()
        p.setPen(QPen(QColor(ACCENT),2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(QRectF(a,14,max(1,b-a),54),4,4)
        for x in (a,b):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(x-6,11,12,60),4,4)
            p.setPen(QPen(QColor(LIGHT_INK),1))
            for offset in (-1.5,1.5):
                p.drawLine(int(x+offset),36,int(x+offset),46)
        x = self.frame_x(self.position+.5)
        p.setPen(QPen(QColor(INK),3))
        p.drawLine(int(x),10,int(x),72)
        p.setPen(QPen(QColor(LIGHT_INK),1))
        p.drawLine(int(x),10,int(x),72)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(14,77,110,20),Qt.AlignmentFlag.AlignLeft,timecode(0))
        p.drawText(QRectF(self.width()-124,77,110,20),Qt.AlignmentFlag.AlignRight,timecode(self.total/self.fps))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(FOCUS),1,Qt.PenStyle.DotLine))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1,1,-1,-1),6,6)
        p.end()

    def mousePressEvent(self,event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self.setFocus()
        x = event.position().x()
        da,db = abs(x-self.frame_x(self.start)),abs(x-self.frame_x(self.end))
        self.drag = ('start' if da <= db else 'end') if min(da,db) <= 12 else 'seek'
        self._move(x)

    def _move(self,x):
        frame = self.frame_at(x)
        if self.drag == 'start':
            self.start = min(frame,self.end-1)
            self.rangeChanged.emit(self.start,self.end)
        elif self.drag == 'end':
            self.end = max(frame,self.start+1)
            self.rangeChanged.emit(self.start,self.end)
        else:
            self.seek.emit(min(self.total-1,frame))
        self.update()

    def mouseMoveEvent(self,event):
        if self.drag:
            self._move(event.position().x())

    def mouseReleaseEvent(self,event):
        self.drag = None

    def keyPressEvent(self,event):
        if event.key() in (Qt.Key.Key_Left,Qt.Key.Key_Right):
            step = 1 if event.key() == Qt.Key.Key_Right else -1
            self.seek.emit(max(0,min(self.total-1,self.position+step)))
        else:
            super().keyPressEvent(event)
