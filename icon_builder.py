"""Build a Windows ICO from Framelet's PNG using only the runtime Qt dependency."""
import struct
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, Qt
from PySide6.QtGui import QImage


def make_ico(source, destination):
    image = QImage(str(source))
    if image.isNull():
        raise RuntimeError(f'无法读取图标：{source}')
    image = image.scaled(256,256,Qt.AspectRatioMode.KeepAspectRatio,
                         Qt.TransformationMode.SmoothTransformation)
    canvas = QImage(256,256,QImage.Format.Format_ARGB32)
    canvas.fill(Qt.GlobalColor.transparent)
    from PySide6.QtGui import QPainter
    painter = QPainter(canvas)
    painter.drawImage((256-image.width())//2,(256-image.height())//2,image)
    painter.end()
    data = QByteArray()
    buffer = QBuffer(data)
    if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not canvas.save(buffer,'PNG'):
        raise RuntimeError('无法生成图标 PNG 数据。')
    payload = bytes(data)
    # ICO header + one PNG-compressed 256 px image (0 means 256 in ICO fields).
    header = struct.pack('<HHHBBBBHHII',0,1,1,0,0,0,0,1,32,len(payload),22)
    Path(destination).write_bytes(header+payload)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('用法：python icon_builder.py 输入.png 输出.ico')
    make_ico(sys.argv[1],sys.argv[2])
