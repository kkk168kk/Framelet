"""Bounded disk-backed capture; worker owns MSS and always finishes cleanly.

Capture and encoding are separated: the capture thread only grabs frames and
composites the cursor, while a small pool of writer threads handles the slow
PNG encoding. Writers convert to RGB888 and use a lower PNG compression level
(~2.8x faster than ARGB32 default), and the pool scales with frame size, so
even large regions keep up at 24/30fps instead of stuttering on duplicated
frames.
"""
import os
import queue
import tempfile
import threading
import time
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage
import mss
from cursor_capture import compose_cursor

_MAX_BACKLOG_BYTES = 240*1024*1024


def _writer_count(frame_bytes):
    if frame_bytes > 12*1024*1024: return 4
    if frame_bytes > 6*1024*1024: return 3
    return 2


class Recorder(QThread):
    sigElapsed = Signal(float)

    def __init__(self,region,fps=24,max_seconds=120,parent=None):
        super().__init__(parent)
        self.region,self.fps,self.max_seconds = dict(region),fps,max_seconds
        self.frames_dir, self.error = '', ''
        self.frame_count, self.saved = 0, False
        self._stop_event, self._pause_event = threading.Event(),threading.Event()
        self._save = True
        frame_bytes = max(1,self.region['width']*self.region['height']*4)
        backlog = max(self.fps*2, 8)
        self._queue = queue.Queue(maxsize=min(backlog,max(8,_MAX_BACKLOG_BYTES//frame_bytes)))
        self._n_writers = _writer_count(frame_bytes)
        self._writer_error = None

    def set_paused(self,paused):
        if paused: self._pause_event.set()
        else: self._pause_event.clear()

    def stop(self,save=True):
        self._save = save
        self._stop_event.set()

    def _writer_loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            first, count, pixels, width, height = item
            try:
                # Alpha is always opaque for desktop capture; RGB888 encodes
                # about twice as fast and quality=75 halves the PNG work again.
                img = QImage(pixels,width,height,QImage.Format.Format_ARGB32
                             ).convertToFormat(QImage.Format.Format_RGB888)
                path = os.path.join(self.frames_dir,f'f_{first:05d}.png')
                if not img.save(path,'PNG',75):
                    raise OSError('无法写入录制帧，请检查临时磁盘空间。')
                # Duplicate missed frame slots instead of silently speeding up
                # the video. Hard links make duplicates nearly free.
                for offset in range(1,count):
                    duplicate = os.path.join(self.frames_dir,f'f_{first+offset:05d}.png')
                    try:
                        os.link(path,duplicate)
                    except OSError:
                        if not img.save(duplicate):
                            raise OSError('临时磁盘空间不足。')
            except Exception as exc:
                if self._writer_error is None:
                    self._writer_error = str(exc)

    def run(self):
        writers = []
        try:
            self.frames_dir = tempfile.mkdtemp(prefix='framelet-recording-')
            writers = [threading.Thread(target=self._writer_loop,daemon=True)
                       for _ in range(self._n_writers)]
            for writer in writers: writer.start()
            interval = 1/self.fps
            elapsed = 0.0
            last = time.monotonic()
            # Single worker-local MSS instance; no capture on the UI thread.
            with mss.mss() as sct:
                while not self._stop_event.is_set() and self.frame_count < self.max_seconds*self.fps:
                    if self._pause_event.is_set():
                        self._stop_event.wait(.03)
                        last = time.monotonic()
                        continue
                    if self._writer_error:
                        raise OSError(self._writer_error)
                    now = time.monotonic()
                    elapsed += now-last
                    last = now
                    shot = sct.grab(self.region)
                    pixels = compose_cursor(bytes(shot.raw),shot.width,shot.height,self.region)
                    # The current frame also fills every slot missed since the
                    # previous capture, so long encodes never skew the timeline.
                    target = min(int(elapsed*self.fps)+1,self.max_seconds*self.fps)
                    slots = max(1,target-self.frame_count)
                    self._queue.put((self.frame_count+1,slots,pixels,shot.width,shot.height))
                    self.frame_count += slots
                    self.sigElapsed.emit(self.frame_count/self.fps)
                    self._stop_event.wait(max(0,interval-(time.monotonic()-now)))
        except Exception as exc:
            self.error = str(exc)
        finally:
            for _ in writers: self._queue.put(None)
            for writer in writers: writer.join()
            if self._writer_error and not self.error:
                self.error = self._writer_error
            # Preserve partial recordings for export when capture fails mid-session.
            self.saved = self._save and self.frame_count > 0
