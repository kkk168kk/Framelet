"""Framelet's signal-red actions and graphite and paper surfaces."""
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QPushButton
from lucide_icons import lucide_icon

INK = '#19171B'
MUTED = '#51515A'
SURFACE = '#FFFEFE'
WORKSPACE = '#F7F6F8'
BORDER = '#DAD7DD'
CONTROL = '#F0EFF2'
CONTROL_HOVER = '#E9E7ED'
CONTROL_PRESSED = '#E2DFE6'
CONTROL_BORDER_HOVER = '#ADA8B3'
DISABLED_INK = '#63616D'

CHROME = '#1B191D'
STAGE = '#242127'
PREVIEW_MATTE = '#131216'
DARK_CONTROL = '#332F37'
DARK_HOVER = '#403B45'
DARK_PRESSED = '#2A262D'
DARK_BORDER = '#504A55'
LIGHT_INK = '#FFF9FA'
LIGHT_MUTED = '#D9D3DB'

ACCENT = '#C81D36'
ACCENT_HOVER = '#AD162E'
ACCENT_PRESSED = '#951225'
ACCENT_TEXT = '#AE1730'
ACCENT_WASH = '#FDEDF0'
ACCENT_HOVER_WASH = '#FADEE5'
ACCENT_PRESSED_WASH = '#F6CDD8'
ACCENT_BORDER = '#EFC2CB'
SIGNAL_RED = '#FF677D'
FOCUS = '#99152D'

STYLE = f'''
QWidget {{ font-family: 'Microsoft YaHei UI'; font-size: 13px; color: {INK}; }}
QDialog {{ background: {WORKSPACE}; }}
QFrame#windowFrame, QFrame#windowTitleBar {{ background: {CHROME}; }}
QLabel#captionBrand {{ color: {LIGHT_INK}; font-family: 'Segoe UI'; font-weight: 700; font-size: 15px; }}
QLabel#captionSection {{ color: {LIGHT_MUTED}; padding-left: 10px; border-left: 1px solid {DARK_BORDER}; }}
QPushButton#captionButton, QPushButton#captionClose {{
    background: transparent; border: 1px solid transparent; border-radius: 6px; padding: 0; min-height: 0;
}}
QPushButton#captionButton:hover {{ background: {DARK_HOVER}; }}
QPushButton#captionButton:pressed {{ background: {DARK_PRESSED}; }}
QPushButton#captionClose:hover {{ background: {ACCENT}; }}
QPushButton#captionClose:pressed {{ background: {ACCENT_PRESSED}; }}
QPushButton#captionButton:focus, QPushButton#captionClose:focus {{ border-color: {SIGNAL_RED}; padding: 0; }}
QWidget#homeContent, QFrame#editorTools {{ background: {WORKSPACE}; }}
QFrame#editorStage {{ background: {STAGE}; }}
QLabel#stageHeading {{ color: {LIGHT_INK}; font-weight: 600; }}
QLabel#stageMeta, QLabel#playbackClock {{ color: {LIGHT_MUTED}; font-family: 'Segoe UI'; font-size: 13px; }}
QLabel#trimHeading {{ font-size: 14px; font-weight: 700; }}
QLabel#trimDuration {{ color: {ACCENT_TEXT}; font-weight: 600; }}
QLabel#muted, QLabel#settingsSubtitle {{ color: {MUTED}; }}
QLabel#settingsTitle {{ font-size: 26px; font-weight: 700; }}
QLabel#settingsHeading {{ font-size: 14px; font-weight: 600; }}
QFrame#settingsPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px; }}
QFrame#settingsDivider {{ background: {BORDER}; border: none; }}

QPushButton {{
    background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 8px 16px; min-height: 20px;
}}
QPushButton:hover {{ background: {CONTROL_HOVER}; border-color: {CONTROL_BORDER_HOVER}; }}
QPushButton:pressed {{ background: {CONTROL_PRESSED}; }}
QPushButton:focus {{ border: 2px solid {FOCUS}; padding: 7px 15px; }}
QPushButton[primary="true"] {{
    background: {ACCENT}; color: {LIGHT_INK}; border: 1px solid {ACCENT}; font-weight: 700;
}}
QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QPushButton[primary="true"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QPushButton[primary="true"]:focus {{ border: 2px solid {INK}; }}
QPushButton:disabled, QPushButton[primary="true"]:disabled {{
    color: {DISABLED_INK}; background: {CONTROL_HOVER}; border-color: {BORDER};
}}

QPushButton#startRecording {{ border-radius: 10px; padding: 0; min-height: 72px; }}
QWidget#startSymbol {{ background: {ACCENT_PRESSED}; border-radius: 8px; }}
QLabel#startTitle {{ color: {LIGHT_INK}; font-size: 17px; font-weight: 700; }}
QLabel#startDetail {{ color: #FFF0F3; font-size: 12px; }}
QLabel#startKey {{
    color: {ACCENT_TEXT}; background: {LIGHT_INK}; border: 1px solid {LIGHT_INK};
    border-radius: 6px; padding: 3px 9px; font-family: 'Segoe UI'; font-weight: 600;
}}

QComboBox#styledCombo, QWidget#home QKeySequenceEdit QLineEdit {{
    background: {CONTROL}; color: {INK}; border: 1px solid {BORDER}; border-radius: 9px;
    padding: 6px 10px; min-height: 20px; selection-background-color: {ACCENT_HOVER_WASH};
    selection-color: {INK};
}}
QComboBox#styledCombo {{ padding-right: 30px; }}
QComboBox#styledCombo:hover, QWidget#home QKeySequenceEdit QLineEdit:hover {{
    background: {CONTROL_HOVER}; border-color: {CONTROL_BORDER_HOVER};
}}
QComboBox#styledCombo:focus, QWidget#home QKeySequenceEdit QLineEdit:focus {{
    border-color: {FOCUS}; background: {SURFACE};
}}
QComboBox#styledCombo:disabled {{ color: {DISABLED_INK}; background: {CONTROL_HOVER}; }}
QComboBox#styledCombo::drop-down {{ border: none; width: 26px; }}
QComboBox#styledCombo::down-arrow {{ image: none; }}
QToolButton#shortcutClear {{ border: none; border-radius: 4px; background: transparent; padding: 0; }}
QToolButton#shortcutClear:hover {{ background: {CONTROL_PRESSED}; }}
QLabel#homeNote {{ color: {MUTED}; font-size: 12px; }}

QPushButton#supportButton {{
    background: {ACCENT_WASH}; border: 1px solid {ACCENT_BORDER}; border-radius: 9px;
    padding: 0; min-height: 36px;
}}
QPushButton#supportButton:hover {{ background: {ACCENT_HOVER_WASH}; }}
QPushButton#supportButton:pressed {{ background: {ACCENT_PRESSED_WASH}; }}
QPushButton#supportButton:focus {{ border: 2px solid {FOCUS}; }}

QPushButton#playbackButton {{
    background: {DARK_CONTROL}; border: 1px solid {DARK_BORDER}; border-radius: 8px;
    padding: 0; min-height: 38px;
}}
QPushButton#playbackButton:hover {{ background: {DARK_HOVER}; }}
QPushButton#playbackButton:pressed {{ background: {DARK_PRESSED}; }}
QPushButton#playbackButton:focus {{ border: 2px solid {SIGNAL_RED}; }}
QPushButton#playbackButton:disabled {{ background: {DARK_PRESSED}; border-color: {DARK_PRESSED}; }}

QDialog#supportPopup {{ background: transparent; }}
QFrame#supportPanel {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 15px; }}
QFrame#supportHeading {{ background: {ACCENT_WASH}; border-radius: 10px; }}
QFrame#supportQrCard {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 10px; }}
QLabel#supportTitle {{ font-size: 18px; font-weight: 700; }}
QLabel#supportNote {{ color: {MUTED}; font-size: 12px; }}
QPushButton#supportClose {{
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    padding: 0; min-height: 26px;
}}
QPushButton#supportClose:hover {{ background: {ACCENT_HOVER_WASH}; }}
QPushButton#supportClose:pressed {{ background: {ACCENT_PRESSED_WASH}; }}
QPushButton#supportClose:focus {{ border: 2px solid {FOCUS}; }}
QPushButton#supportCopy {{
    background: {CONTROL}; color: {ACCENT_TEXT}; padding: 4px;
}}
QPushButton#supportCopy:hover {{ background: {ACCENT_WASH}; }}
QPushButton#supportCopy:pressed {{ background: {ACCENT_HOVER_WASH}; }}
QPushButton#supportCopy:focus {{ border: 2px solid {FOCUS}; padding: 3px; }}

QProgressBar {{ background: {CONTROL_PRESSED}; border: none; border-radius: 4px; height: 8px; text-align: center; }}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 4px; }}
QToolTip {{ color: {LIGHT_INK}; background: {INK}; border: none; border-radius: 6px; padding: 6px 10px; }}
'''

DARK = f'''
QWidget#bar {{ background: {STAGE}; border: 1px solid {DARK_BORDER}; border-radius: 10px; }}
QWidget#bar QLabel {{ color: {LIGHT_INK}; }}
QWidget#bar QPushButton {{
    color: {LIGHT_INK}; background: {DARK_CONTROL}; border: 1px solid {DARK_BORDER};
    border-radius: 7px; padding: 6px 12px;
}}
QWidget#bar QPushButton:hover {{ background: {DARK_HOVER}; }}
QWidget#bar QPushButton:pressed {{ background: {DARK_PRESSED}; }}
QWidget#bar QPushButton[primary="true"] {{ background: {ACCENT}; border-color: {ACCENT}; }}
QWidget#bar QPushButton[primary="true"]:hover {{ background: {ACCENT_HOVER}; border-color: {ACCENT_HOVER}; }}
QWidget#bar QPushButton[primary="true"]:pressed {{ background: {ACCENT_PRESSED}; border-color: {ACCENT_PRESSED}; }}
QWidget#bar QPushButton:focus, QWidget#bar QPushButton[primary="true"]:focus {{ border-color: {SIGNAL_RED}; }}
QWidget#bar QPushButton:disabled, QWidget#bar QPushButton[primary="true"]:disabled {{
    color: {LIGHT_MUTED}; background: {DARK_PRESSED}; border-color: {DARK_BORDER};
}}
'''


def button(text, primary=False, *, icon=None, icon_color=MUTED, icon_size=18):
    w = QPushButton(text)
    w.setProperty('primary', primary)
    w.setCursor(Qt.CursorShape.PointingHandCursor)
    w.setAccessibleName(text)
    w.setAutoDefault(False)
    if icon:
        w.setIcon(lucide_icon(icon,icon_color,icon_size))
        w.setIconSize(QSize(icon_size,icon_size))
    return w
