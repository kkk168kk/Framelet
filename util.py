"""Frame-exact, cancellable FFmpeg export with atomic destination replacement."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import imageio_ffmpeg
from PySide6.QtCore import QThread
import threading


def clipboard_cache_path(kind):
    """Keep copied media outside recording cleanup, including after app exit."""
    if kind not in ('gif','mp4'):
        raise ValueError('不支持的复制格式。')
    directory = Path(tempfile.gettempdir())/'Framelet-clipboard'
    directory.mkdir(parents=True,exist_ok=True)
    return str(directory/f'Framelet-{uuid4().hex}.{kind}')


def copy_file_to_clipboard(path):
    """Copy an exported file as a native file object, not merely its path text."""
    path = str(Path(path).resolve())
    if not os.path.isfile(path):
        raise FileNotFoundError('导出文件不存在，请重新导出。')
    if sys.platform == 'win32':
        import struct
        import win32clipboard
        import win32con
        payload = (path+'\0\0').encode('utf-16-le')
        data = struct.pack('<IiiII',20,0,0,0,1)+payload
        last_error = None
        for _ in range(5):
            try:
                win32clipboard.OpenClipboard()
                try:
                    win32clipboard.EmptyClipboard()
                    win32clipboard.SetClipboardData(win32con.CF_HDROP,data)
                finally:
                    win32clipboard.CloseClipboard()
                return True
            except Exception as exc:
                last_error = exc
                time.sleep(.04)
        raise RuntimeError('剪贴板正被其他应用占用，请稍后重试。') from last_error
    from PySide6.QtCore import QMimeData,QUrl
    from PySide6.QtWidgets import QApplication
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(path)])
    QApplication.clipboard().setMimeData(mime)
    return True


def export_clip(frames_dir, fps, out_path, start, end, kind, cancel=None):
    """Export [start,end) frame indices. Never modify the source recording."""
    frames_dir = Path(frames_dir)
    count = len(list(frames_dir.glob('f_*.png')))
    if kind not in ('gif','mp4') or fps <= 0 or not 0 <= start < end <= count:
        raise ValueError('裁剪区间无效，请至少保留一帧。')
    destination = Path(out_path).resolve()
    if destination.is_relative_to(frames_dir.resolve()):
        raise ValueError('请选择录制临时目录之外的保存位置。')
    fd, scratch = tempfile.mkstemp(prefix='.framelet-',suffix='.'+kind,dir=destination.parent)
    os.close(fd)
    proc = None
    try:
        cmd = [imageio_ffmpeg.get_ffmpeg_exe(),'-hide_banner','-loglevel','error','-y',
               '-framerate',str(fps),'-start_number',str(start+1),
               '-i',str(frames_dir/'f_%05d.png')]
        trim = f'trim=end_frame={end-start},setpts=PTS-STARTPTS'
        if kind == 'gif':
            # Limit both dimensions, including portrait recordings; never upscale.
            # stats_mode=full weighs every pixel equally — stats_mode=diff lets
            # changing video hog the palette and crushes static UI grays to white.
            # sierra2_4a diffuses quantization error smoothly without the
            # crosshatch pattern bayer leaves on gradients.
            scale = "scale=w='min(960,iw)':h='min(960,ih)':force_original_aspect_ratio=decrease:flags=lanczos"
            vf = (trim+','+scale+',split[a][b];[a]palettegen=stats_mode=full[p];'
                  '[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle')
            cmd += ['-filter_complex',vf,'-loop','0']
        else:
            cmd += ['-vf',trim+',pad=ceil(iw/2)*2:ceil(ih/2)*2',
                    '-c:v','libx264','-preset','veryfast','-crf','23',
                    '-pix_fmt','yuv420p','-r',str(fps),'-fps_mode','cfr',
                    '-movflags','+faststart']
        cmd += ['-frames:v',str(end-start),scratch]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        with tempfile.TemporaryFile() as errors:
            proc = subprocess.Popen(cmd,stdout=subprocess.DEVNULL,stderr=errors,creationflags=flags)
            started = time.monotonic()
            while proc.poll() is None:
                if cancel is not None and cancel.is_set():
                    raise InterruptedError('已取消导出，录制仍然保留。')
                if time.monotonic()-started > 300:
                    raise TimeoutError('导出超过 5 分钟，请缩短片段后重试。')
                time.sleep(.05)
            if proc.returncode:
                errors.seek(0)
                detail = errors.read().decode('utf-8',errors='replace')[-1600:]
                raise RuntimeError('编码失败：'+detail)
        if cancel is not None and cancel.is_set():
            raise InterruptedError('已取消导出，录制仍然保留。')
        if os.path.getsize(scratch) == 0:
            raise RuntimeError('编码器未生成有效文件。')
        os.replace(scratch,destination)
        return str(destination)
    finally:
        if proc is not None and proc.poll() is None:
            proc.kill()
            proc.wait()
        if os.path.exists(scratch):
            os.unlink(scratch)


class ExportWorker(QThread):
    def __init__(self,frames_dir,fps,path,start,end,kind,parent=None):
        super().__init__(parent)
        self.args = (frames_dir,fps,path,start,end,kind)
        self.cancel_event = threading.Event()
        self.path, self.error, self.cancelled = '', '', False

    def run(self):
        try:
            self.path = export_clip(*self.args,cancel=self.cancel_event)
        except InterruptedError:
            self.cancelled = True
        except Exception as exc:
            self.error = str(exc)

    def cancel(self):
        self.cancel_event.set()
