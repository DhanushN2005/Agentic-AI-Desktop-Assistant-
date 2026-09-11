# Enhanced version with NEXT-GEN GLASSMORPHISM UI improvements
import sys
import psutil
import time
import math
import os
import webbrowser
import subprocess
import threading
import random
from PyQt6.QtWidgets import (QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
                             QLabel, QFrame, QGraphicsDropShadowEffect, QSystemTrayIcon,
                             QMenu, QSlider, QComboBox, QLineEdit, QPushButton, QProgressBar,
                             QSizePolicy, QGridLayout, QTextBrowser, QDialog, QScrollArea, QTabWidget)
from PyQt6.QtCore import (Qt, QTimer, QPropertyAnimation, QEasingCurve, 
                           QRect, QRectF, pyqtProperty, QPoint, QPointF,
                           QParallelAnimationGroup, QSequentialAnimationGroup, QSize)
from PyQt6.QtGui import (QPainter, QColor, QRadialGradient, QLinearGradient, QBrush, QPen, 
                          QIcon, QPixmap, QFont, QFontDatabase, QPainterPath)
from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtNetwork import QUdpSocket, QHostAddress
# Silence system-level rendering warnings from Qt C++ core
import os
import sys
import ctypes
from ctypes import wintypes
sys.stderr = open(os.devnull, 'w')

class HotkeyListener(QThread):
    hotkey_signal = pyqtSignal()
    def run(self):
        user32 = ctypes.windll.user32
        # Register Ctrl+F (MOD_CONTROL=0x0002, VK_F=0x46)
        # Using ID 99 to avoid collisions
        if not user32.RegisterHotKey(None, 99, 0x0002, 0x46):
            return
        
        try:
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                if msg.message == 0x0312: # WM_HOTKEY
                    self.hotkey_signal.emit()
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            user32.UnregisterHotKey(None, 99)

class FlexieConfig:
    MODES = {
        "jarvis":       {"accent": "#00BFFF", "glow": 25, "speed": 2000, "bg_tint": (10, 20, 30, 220), "secondary": "#0080FF"},
        "cyberpunk":    {"accent": "#FF00FF", "glow": 30, "speed": 1500, "bg_tint": (30, 10, 30, 220), "secondary": "#00FFFF"},
        "matrix":       {"accent": "#00FF41", "glow": 20, "speed": 1800, "bg_tint": (5, 25, 5, 220),  "secondary": "#008F11"},
        "tron":         {"accent": "#00FFFF", "glow": 25, "speed": 2200, "bg_tint": (5, 5, 25, 220),  "secondary": "#0088FF"},
        "space":        {"accent": "#FFFFFF", "glow": 15, "speed": 3500, "bg_tint": (5, 5, 15, 230),  "secondary": "#A0A0FF"},
        "neon":         {"accent": "#FF3366", "glow": 35, "speed": 1200, "bg_tint": (25, 5, 15, 220), "secondary": "#FF9933"},
        "alert":        {"accent": "#FF3B30", "glow": 40, "speed": 500,  "bg_tint": (40, 5, 5, 230),  "secondary": "#FF6B6B"}
    }

class ModernSlider(QSlider):
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 4px;
                background: rgba(255,255,255,10);
                border-radius: 2px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00D2FF, stop:1 #007AFF);
                width: 14px;
                height: 14px;
                margin: -5px 0;
                border-radius: 7px;
                border: 2px solid rgba(255,255,255,0.8);
            }
            QSlider::handle:horizontal:hover {
                transform: scale(1.2);
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00E0FF, stop:1 #008AFF);
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00D2FF, stop:1 #007AFF);
                border-radius: 2px;
            }
        """)


class CustomProgressBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self.setTextVisible(False)
        self.setStyleSheet("""
            QProgressBar {
                border: none;
                background: rgba(255,255,255,10);
                border-radius: 3px;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00D2FF, stop:1 #007AFF);
                border-radius: 3px;
            }
        """)

class ApiKeysDialog(QDialog):
    """Glassmorphism settings dialog for all LLM provider API keys + model picker."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Flexie — AI Provider Keys & Models")
        self.setModal(True)
        self.setMinimumWidth(580)
        self.setMaximumWidth(660)
        self.setStyleSheet("""
            QDialog { background: rgba(10,15,25,245); border-radius: 16px; }
            QLabel { color: rgba(255,255,255,200); font-size: 11px; }
            QLabel#DialogTitle { color: #FFFFFF; font-size: 16px; font-weight: 800; letter-spacing: 2px; }
            QLabel#Help { color: rgba(0,210,255,180); font-size: 10px; }
            QLabel#Status { color: #00FF41; font-size: 11px; font-weight: 600; }
            QLineEdit { background: rgba(0,0,0,80); border: 1px solid rgba(255,255,255,15); border-radius: 8px; color: #FFFFFF; padding: 8px 10px; font-size: 11px; }
            QLineEdit:focus { border: 1px solid #00D2FF; }
            QComboBox { background: rgba(0,0,0,80); border: 1px solid rgba(255,255,255,15); border-radius: 8px; color: #FFFFFF; padding: 6px 10px; font-size: 11px; }
            QComboBox:hover { border: 1px solid #00D2FF; }
            QComboBox QAbstractItemView { background: rgba(15,20,35,250); color: #FFFFFF; selection-background-color: rgba(0,210,255,40); border: 1px solid rgba(255,255,255,15); }
            QPushButton { background: rgba(255,255,255,8); color: #FFFFFF; border-radius: 8px; padding: 8px 14px; font-weight: 600; border: 1px solid rgba(255,255,255,12); }
            QPushButton:hover { background: rgba(0,210,255,20); border: 1px solid rgba(0,210,255,50); }
            QPushButton#SaveBtn { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #0095FF, stop:1 #0055FF); border: none; padding: 10px; font-size: 13px; }
            QPushButton#SaveBtn:hover { background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #00A5FF, stop:1 #0065FF); }
        """)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(12)
        title = QLabel("🔑  AI PROVIDER KEYS  +  MODELS")
        title.setObjectName("DialogTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)
        subtitle = QLabel("Keys + model per provider. ACTIVE picks who answers. AUTO = fallback Groq → OpenAI → DeepSeek → Gemini → Claude → Ollama")
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet("color: rgba(255,255,255,120); font-size: 10px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(subtitle)
        # Active provider selector
        active_row = QHBoxLayout()
        active_row.addWidget(QLabel("⚡ Active Provider:"))
        self.active_combo = QComboBox()
        self.active_combo.addItems(["auto (fallback chain)", "groq", "openai", "deepseek", "gemini", "anthropic", "mistral", "ollama"])
        self.active_combo.setMinimumHeight(32)
        active_row.addWidget(self.active_combo, 1)
        outer.addLayout(active_row)
        # Search filter
        search_row = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("🔍 Filter providers (groq, openai, deepseek...)")
        self.search_edit.setMinimumHeight(30)
        self.search_edit.setStyleSheet("QLineEdit { background: rgba(255,255,255,8); border-radius: 8px; padding: 6px 12px; }")
        search_row.addWidget(self.search_edit, 1)
        self.search_clear = QPushButton("✕")
        self.search_clear.setFixedSize(28, 28)
        self.search_clear.clicked.connect(lambda: self.search_edit.clear())
        search_row.addWidget(self.search_clear)
        outer.addLayout(search_row)
        # Priority hint
        prio = QLabel("Priority: Groq(1) → OpenAI(2) → DeepSeek(3) → Gemini(4) → Claude(5) → Ollama(fallback)")
        prio.setStyleSheet("color: rgba(255,255,255,70); font-size: 9px;")
        prio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(prio)
        # Scroll area for providers
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; } QWidget#ScrollContent { background: transparent; }")
        scroll.setMaximumHeight(460)
        content = QFrame()
        content.setObjectName("ScrollContent")
        self.form_layout = QVBoxLayout(content)
        self.form_layout.setSpacing(14)
        self.form_layout.setContentsMargins(4, 4, 4, 4)
        self.fields = {}
        self.model_combos = {}
        self.provider_boxes = {}
        self.status_label = QLabel("")
        self.status_label.setObjectName("Status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.hide()
        try:
            from utils.config import SUPPORTED_PROVIDERS
            providers = list(SUPPORTED_PROVIDERS.items())
        except Exception:
            providers = []
        _icons = {"groq":"⚡","gemini":"✦","openai":"🤖","deepseek":"🧠","anthropic":"◆","mistral":"🌬️","cohere":"🌀","together":"🔗","ollama":"💻"}
        for pid, meta in providers:
            box = QFrame()
            box.setStyleSheet("QFrame { background: rgba(255,255,255,6); border: 1px solid rgba(255,255,255,10); border-radius: 10px; }")
            box_layout = QVBoxLayout(box)
            box_layout.setContentsMargins(10, 10, 10, 10)
            box_layout.setSpacing(6)
            header = QHBoxLayout()
            icon = _icons.get(pid, "●")
            prio_num = list(SUPPORTED_PROVIDERS.keys()).index(pid) + 1 if pid in SUPPORTED_PROVIDERS else 99
            lbl = QLabel(f"{icon}  {meta['label']}  (#{prio_num} • {meta['env']})")
            lbl.setStyleSheet("font-weight: 700; color: #FFFFFF; font-size: 11px; background: transparent; border: none;")
            header.addWidget(lbl)
            header.addStretch()
            # Live key status dot
            _dot = QLabel("●")
            _dot.setStyleSheet("color: rgba(255,255,255,40); font-size: 10px; background: transparent; border: none;")
            _dot.setObjectName(f"dot_{pid}")
            header.addWidget(_dot)
            help_lbl = QLabel(f"↗ {meta['help']}")
            help_lbl.setStyleSheet("color: rgba(0,210,255,90); font-size: 9px; background: transparent; border: none;")
            header.addWidget(help_lbl)
            box_layout.addLayout(header)
            # Key row
            key_row = QHBoxLayout()
            key_row.addWidget(QLabel("Key:"))
            edit = QLineEdit()
            edit.setEchoMode(QLineEdit.EchoMode.Password)
            edit.setPlaceholderText(meta['placeholder'] + " — leave empty to keep")
            edit.setMinimumHeight(32)
            key_row.addWidget(edit, 1)
            toggle = QPushButton("👁")
            toggle.setFixedSize(32, 32)
            toggle.setCheckable(True)
            def make_toggle(e=edit, b=toggle):
                def _t(checked):
                    e.setEchoMode(QLineEdit.EchoMode.Normal if checked else QLineEdit.EchoMode.Password)
                    b.setText("🙈" if checked else "👁")
                return _t
            toggle.toggled.connect(make_toggle())
            key_row.addWidget(toggle)
            box_layout.addLayout(key_row)
            # Model row
            model_row = QHBoxLayout()
            model_row.addWidget(QLabel("Model:"))
            combo = QComboBox()
            combo.setEditable(True)
            combo.setMinimumHeight(30)
            models = meta.get("models", [meta.get("default_model","")])
            for m in models:
                combo.addItem(m)
            combo.setPlaceholderText(meta.get("default_model",""))
            model_row.addWidget(combo, 1)
            box_layout.addLayout(model_row)
            self.form_layout.addWidget(box)
            self.fields[pid] = edit
            self.model_combos[pid] = combo
            self.provider_boxes[pid] = box
            # Live validation wiring
            def make_validate(p=pid, e=edit, d=_dot, meta=meta):
                def _v(txt):
                    prefix = meta.get("prefix","")
                    has = bool(txt.strip())
                    if not has:
                        # Show saved state
                        try: from utils.config import Config as _C; has_saved = bool(_C.get_api_key(p)); d.setStyleSheet("color: #00FF41; font-size: 10px; background: transparent; border: none;" if has_saved else "color: rgba(255,255,255,40); font-size: 10px; background: transparent; border: none;")
                        except: pass
                        e.setStyleSheet("background: rgba(0,0,0,80); border: 1px solid rgba(255,255,255,15); border-radius: 8px;")
                    elif prefix and not txt.strip().startswith(prefix):
                        d.setStyleSheet("color: #FFD700; font-size: 10px; background: transparent; border: none;")
                        e.setStyleSheet("background: rgba(255,215,0,10); border: 1px solid rgba(255,215,0,50); border-radius: 8px;")
                    else:
                        d.setStyleSheet("color: #00FF41; font-size: 10px; background: transparent; border: none;")
                        e.setStyleSheet("background: rgba(0,0,0,80); border: 1px solid rgba(0,255,65,40); border-radius: 8px;")
                return _v
            edit.textChanged.connect(make_validate())
        # Ollama section
        ollama_box = QFrame()
        ollama_box.setStyleSheet("QFrame { background: rgba(255,255,255,6); border: 1px solid rgba(255,255,255,10); border-radius: 10px; }")
        ollama_layout = QVBoxLayout(ollama_box)
        ollama_layout.setContentsMargins(10, 10, 10, 10)
        ollama_layout.setSpacing(6)
        ollama_header = QHBoxLayout()
        ollama_lbl = QLabel("Ollama (Local)")
        ollama_lbl.setStyleSheet("font-weight: 700; color: #FFFFFF; font-size: 11px; background: transparent; border: none;")
        ollama_header.addWidget(ollama_lbl)
        ollama_header.addStretch()
        ollama_help = QLabel("↗ ollama.com")
        ollama_help.setStyleSheet("color: rgba(0,210,255,90); font-size: 9px; background: transparent; border: none;")
        ollama_header.addWidget(ollama_help)
        ollama_layout.addLayout(ollama_header)
        ollama_url_row = QHBoxLayout()
        ollama_url_row.addWidget(QLabel("URL:"))
        self.ollama_edit = QLineEdit()
        self.ollama_edit.setPlaceholderText("http://localhost:11434/api/generate")
        self.ollama_edit.setMinimumHeight(30)
        ollama_url_row.addWidget(self.ollama_edit, 1)
        ollama_layout.addLayout(ollama_url_row)
        ollama_model_row = QHBoxLayout()
        ollama_model_row.addWidget(QLabel("Model:"))
        self.ollama_model_combo = QComboBox()
        self.ollama_model_combo.setEditable(True)
        self.ollama_model_combo.addItems(["tinyllama:latest", "llama3:latest", "llama3.1:latest", "mistral:latest", "gemma2:latest", "qwen2.5:latest", "phi3:latest"])
        self.ollama_model_combo.setMinimumHeight(30)
        ollama_model_row.addWidget(self.ollama_model_combo, 1)
        ollama_layout.addLayout(ollama_model_row)
        self.form_layout.addWidget(ollama_box)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        outer.addWidget(self.status_label)
        btn_row = QHBoxLayout()
        self.btn_test = QPushButton("🧪 Test")
        self.btn_save = QPushButton("💾 Save & Reload")
        self.btn_save.setObjectName("SaveBtn")
        self.btn_cancel = QPushButton("Cancel")
        btn_row.addWidget(self.btn_test)
        btn_row.addWidget(self.btn_save)
        btn_row.addWidget(self.btn_cancel)
        outer.addLayout(btn_row)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._save)
        self.btn_test.clicked.connect(self._test)
        # Search filter wiring
        def _filter(txt):
            q = txt.lower().strip()
            for pid, box in self.provider_boxes.items():
                show = not q or q in pid or q in box.findChild(QLabel).text().lower() if box.findChild(QLabel) else True
                # Simpler: check pid and label
                try:
                    from utils.config import SUPPORTED_PROVIDERS as _SP
                    meta = _SP[pid]
                    show = not q or q in pid or q in meta['label'].lower() or q in meta['env'].lower()
                except: pass
                box.setVisible(show)
        self.search_edit.textChanged.connect(_filter)
        self._load_existing()
        # Init dot colors
        try:
            from utils.config import Config as _C
            for pid, dot in [(p, self.findChild(QLabel, f"dot_{p}")) for p in self.fields]:
                if dot:
                    has = bool(_C.get_api_key(pid))
                    dot.setStyleSheet("color: #00FF41; font-size: 10px; background: transparent; border: none;" if has else "color: rgba(255,255,255,40); font-size: 10px; background: transparent; border: none;")
        except: pass

    def _load_existing(self):
        try:
            from utils.config import Config, SUPPORTED_PROVIDERS
            # Active provider
            active = getattr(Config, 'ACTIVE_PROVIDER', 'auto')
            idx = self.active_combo.findText(active, 0) if active != "auto" else 0
            # find auto entry
            for i in range(self.active_combo.count()):
                if self.active_combo.itemText(i).startswith("auto"):
                    if active == "auto": idx = i; break
                elif self.active_combo.itemText(i) == active:
                    idx = i; break
            self.active_combo.setCurrentIndex(max(0, idx))
            for pid in self.fields:
                meta = SUPPORTED_PROVIDERS[pid]
                raw = Config.get_api_key(pid)
                if raw:
                    self.fields[pid].setPlaceholderText(raw[:4] + "•" * max(4, len(raw)-8) + raw[-4:] + "  (saved)")
                self.fields[pid].setText("")
                # Model
                cur_model = Config.get_model(pid)
                combo = self.model_combos[pid]
                # Ensure cur_model is in combo
                if cur_model and combo.findText(cur_model) == -1:
                    combo.addItem(cur_model)
                combo.setCurrentText(cur_model or meta.get("default_model",""))
            from utils.config import Config as C
            self.ollama_edit.setText(C.OLLAMA_URL if C.OLLAMA_URL != "http://localhost:11434/api/generate" else "")
            self.ollama_edit.setPlaceholderText(C.OLLAMA_URL)
            self.ollama_model_combo.setCurrentText(C.OLLAMA_MODEL)
        except Exception:
            pass

    def _collect_updates(self) -> dict:
        updates = {}
        for pid, edit in self.fields.items():
            txt = edit.text().strip()
            if txt:
                from utils.config import SUPPORTED_PROVIDERS
                env = SUPPORTED_PROVIDERS[pid]["env"]
                updates[env] = txt
        # Models
        for pid, combo in self.model_combos.items():
            txt = combo.currentText().strip()
            if txt:
                from utils.config import SUPPORTED_PROVIDERS
                menv = SUPPORTED_PROVIDERS[pid]["model_env"]
                # Only save if changed from default or current
                from utils.config import Config
                cur = Config.get_model(pid)
                if txt != cur:
                    updates[menv] = txt
        ollama_txt = self.ollama_edit.text().strip()
        if ollama_txt:
            updates["OLLAMA_URL"] = ollama_txt
        om = self.ollama_model_combo.currentText().strip()
        if om:
            from utils.config import Config
            if om != Config.OLLAMA_MODEL:
                updates["OLLAMA_MODEL"] = om
        # Active provider
        active_txt = self.active_combo.currentText().strip()
        active_val = "auto" if active_txt.startswith("auto") else active_txt
        from utils.config import Config as C
        if active_val != getattr(C, 'ACTIVE_PROVIDER', 'auto'):
            updates["ACTIVE_PROVIDER"] = active_val
        return updates

    def _save(self):
        updates = self._collect_updates()
        if not updates:
            self._show_status("No changes to save.", "#FFD700")
            return
        try:
            from utils.config import Config
            ok = Config.set_many_keys(updates)
            if ok:
                try:
                    import socket
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.sendto(b"RELOAD_BRAIN", ("127.0.0.1", 9887))
                    s.close()
                except: pass
                self._show_status(f"Saved {len(updates)} change(s). Reloading brain…", "#00FF41")
                from PyQt6.QtCore import QTimer
                QTimer.singleShot(1200, self.accept)
            else:
                self._show_status("Failed to write .env — check permissions.", "#FF3B30")
        except Exception as e:
            self._show_status(f"Error: {e}", "#FF3B30")

    def _test(self):
        try:
            from utils.config import Config as C
            preview = []
            from utils.config import SUPPORTED_PROVIDERS
            for pid, meta in SUPPORTED_PROVIDERS.items():
                edit_txt = self.fields[pid].text().strip()
                has = bool(edit_txt or C.get_api_key(pid))
                icon = "✅" if has else "⚪"
                model = self.model_combos[pid].currentText().strip() or C.get_model(pid)
                preview.append(f"{icon} {meta['label']}:{model}")
            active = self.active_combo.currentText()
            msg = f"Active: {active} | " + " | ".join(preview[:4])
            self._show_status(msg, "#00D2FF")
        except Exception as e:
            self._show_status(f"Test error: {e}", "#FF3B30")

    def _show_status(self, msg: str, color: str):
        self.status_label.setText(msg)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: 600;")
        self.status_label.show()

class ControlPopup(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                            Qt.WindowType.WindowStaysOnTopHint | 
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMinimumWidth(340)
        self.setMaximumWidth(700) # Allow expansion for full text
        
        QFontDatabase.addApplicationFont(":/fonts/SegoeUI.ttf")
        
        self.container = QFrame(self)
        # Professional Minimalist Glassmorphism
        self.container.setStyleSheet("""
            QFrame#MainContainer {
                background: rgba(10, 15, 25, 235);
                border: 1px solid rgba(0, 210, 255, 45);
                border-radius: 18px;
            }
            QLabel { 
                color: rgba(255, 255, 255, 210); 
                font-family: 'Inter', 'Segoe UI', sans-serif; 
                font-size: 12px; 
            }
            QLabel#Title { 
                color: #FFFFFF; 
                font-size: 18px; 
                font-weight: 800; 
                background: transparent;
                letter-spacing: 3px;
            }
            QLabel#SectionHeader {
                color: rgba(0, 210, 255, 140);
                font-size: 9px;
                font-weight: 800;
                text-transform: uppercase;
                letter-spacing: 2.5px;
                margin-top: 8px;
                margin-bottom: 0px;
            }
            QPushButton {
                background: rgba(255, 255, 255, 8);
                color: #FFFFFF; 
                border-radius: 10px; 
                font-weight: 600; 
                padding: 10px;
                font-size: 12px;
                border: 1px solid rgba(255,255,255,12);
            }
            QPushButton:hover { 
                background: rgba(0, 210, 255, 25);
                border: 1px solid rgba(0, 210, 255, 60);
            }
            QPushButton#WakeButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0095FF, stop:1 #0055FF);
                border: none;
                padding: 12px;
                font-size: 13px;
                letter-spacing: 1px;
            }
            QPushButton#WakeButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00A5FF, stop:1 #0065FF);
            }
            QLineEdit { 
                background: rgba(0, 0, 0, 80); 
                border: 1px solid rgba(255, 255, 255, 15); 
                border-radius: 10px; 
                color: #FFFFFF; 
                padding: 10px 12px;
                font-size: 12px;
            }
            QLineEdit:focus {
                border: 1px solid #00D2FF;
                background: rgba(0, 210, 255, 5);
            }
            QComboBox { 
                background: rgba(0, 0, 0, 80); 
                color: white; 
                border-radius: 8px; 
                padding: 6px 10px; 
                border: 1px solid rgba(255,255,255,15);
                font-size: 11px;
            }
            QComboBox:hover { border: 1px solid #00D2FF; }
        """)
        self.container.setObjectName("MainContainer")
        
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(10, 10, 10, 10) # Shadow margins
        self.main_layout.addWidget(self.container)
        
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(22, 22, 22, 22)
        layout.setSpacing(12)
        
        # Header (Title + Waveform + Controls)
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0,0,0,5)
        
        title = QLabel("FLEXIE")
        title.setObjectName("Title")
        header_layout.addWidget(title)
        header_layout.addStretch(1) # Expand
        
        # New: Pin & Minimize Controls
        self.btn_pin = QPushButton("📌")
        self.btn_pin.setFixedSize(24, 24)
        self.btn_pin.setCheckable(True)
        self.btn_pin.setChecked(True)
        self.btn_pin.setStyleSheet("padding: 2px; font-size: 10px; background: transparent; border: none;")
        header_layout.addWidget(self.btn_pin)

        self.btn_min = QPushButton("─")
        self.btn_min.setFixedSize(24, 24)
        self.btn_min.setStyleSheet("padding: 2px; font-size: 14px; font-weight: bold; background: transparent; border: none;")
        header_layout.addWidget(self.btn_min)
        
        self.status_indicator = QFrame()
        self.status_indicator.setFixedSize(8, 8)
        self.status_indicator.setStyleSheet("background-color: #00FF41; border-radius: 4px;")
        header_layout.addWidget(self.status_indicator)
        
        self.header_container = QWidget() # WRAP HEADER IN WIDGET
        self.header_container.setLayout(header_layout)
        layout.addWidget(self.header_container)

        self.status_label = QLabel("STATUS: READY")
        self.status_label.setStyleSheet("color: #00D2FF; font-size: 10px; font-weight: 700; letter-spacing: 2px;")
        layout.addWidget(self.status_label)

        # — Active AI Provider Badge (live) —
        self.provider_badge = QFrame()
        self.provider_badge.setStyleSheet("background: rgba(0,210,255,10); border: 1px solid rgba(0,210,255,25); border-radius: 10px;")
        badge_layout = QHBoxLayout(self.provider_badge)
        badge_layout.setContentsMargins(10, 8, 10, 8)
        badge_layout.setSpacing(8)
        self.provider_dot = QLabel("●")
        self.provider_dot.setStyleSheet("color: #00FF41; font-size: 14px; background: transparent; border: none;")
        self.provider_label = QLabel("AUTO")
        self.provider_label.setStyleSheet("color: #FFFFFF; font-size: 11px; font-weight: 700; background: transparent; border: none;")
        self.provider_model_label = QLabel("—")
        self.provider_model_label.setStyleSheet("color: rgba(255,255,255,160); font-size: 10px; background: transparent; border: none;")
        self.provider_model_label.setWordWrap(True)
        badge_layout.addWidget(self.provider_dot)
        badge_layout.addWidget(self.provider_label)
        badge_layout.addWidget(self.provider_model_label, 1)
        self.btn_provider_refresh = QPushButton("↻")
        self.btn_provider_refresh.setFixedSize(26, 26)
        self.btn_provider_refresh.setStyleSheet("background: rgba(255,255,255,8); border-radius: 6px; font-size: 12px;")
        badge_layout.addWidget(self.btn_provider_refresh)
        layout.addWidget(self.provider_badge)
        # Provider dots row (all providers)
        self.provider_dots_row = QHBoxLayout()
        self.provider_dots_row.setSpacing(6)
        self.provider_dots_widgets = {}
        dots_container = QWidget()
        dots_container.setLayout(self.provider_dots_row)
        dots_container.setStyleSheet("background: transparent;")
        # Provider mini badges • + label
        try:
            from utils.config import SUPPORTED_PROVIDERS as _SP
            _provider_icons = {"groq":"⚡","gemini":"✦","openai":"●","deepseek":"◆","anthropic":"▲","mistral":"⬢","cohere":"⬣","together":"⬔","ollama":"◉"}
            for _pid in ["groq","openai","deepseek","gemini","anthropic","mistral","ollama"]:
                _meta = _SP.get(_pid, {"label": _pid})
                _lbl = QLabel(f"{_provider_icons.get(_pid,'●')} {_pid[:3]}")
                _lbl.setStyleSheet("color: rgba(255,255,255,90); font-size: 9px; background: rgba(255,255,255,6); border: 1px solid rgba(255,255,255,10); border-radius: 6px; padding: 2px 6px;")
                self.provider_dots_widgets[_pid] = _lbl
                self.provider_dots_row.addWidget(_lbl)
            self.provider_dots_row.addStretch()
        except: pass
        self.dots_container = dots_container
        layout.addWidget(dots_container)
        
        # System Metrics Panel
        self.metrics_frame = QFrame()
        self.metrics_frame.setStyleSheet("background: rgba(255,255,255,5); border-radius: 12px; border: 1px solid rgba(255,255,255,10);")
        metrics_layout = QVBoxLayout(self.metrics_frame)
        metrics_layout.setContentsMargins(14, 14, 14, 14)
        metrics_layout.setSpacing(10)
        
        # Helper to create a stat row
        def create_stat(name, val="0%"):
            row = QHBoxLayout()
            lbl = QLabel(name)
            lbl.setStyleSheet("font-size: 11px; color: rgba(255,255,255,180);")
            vlbl = QLabel(val)
            vlbl.setStyleSheet("font-size: 11px; font-weight: bold; color: #00D2FF;")
            vlbl.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(lbl)
            row.addWidget(vlbl)
            bar = CustomProgressBar()
            return row, vlbl, bar
            
        cpu_row, self.cpu_value, self.cpu_progress = create_stat("CPU")
        metrics_layout.addLayout(cpu_row); metrics_layout.addWidget(self.cpu_progress)
        
        ram_row, self.ram_value, self.ram_progress = create_stat("RAM")
        metrics_layout.addLayout(ram_row); metrics_layout.addWidget(self.ram_progress)
        
        batt_row, self.batt_value, self.batt_progress = create_stat("BATTERY")
        metrics_layout.addLayout(batt_row); metrics_layout.addWidget(self.batt_progress)
        
        layout.addWidget(self.metrics_frame)
        
        # Spotlight Input
        spotlight_layout = QHBoxLayout()
        self.spotlight = QLineEdit()
        self.spotlight.setPlaceholderText("Type a command or ask a question...")
        # Add embedded icon to spotlight
        self.spotlight.addAction(QIcon(":/icons/search.png"), QLineEdit.ActionPosition.LeadingPosition)
        spotlight_layout.addWidget(self.spotlight)
        layout.addLayout(spotlight_layout)

        # Copilot-style Result Area
        self.result_area = QTextBrowser()
        self.result_area.setOpenExternalLinks(True)
        self.result_area.setReadOnly(True)
        self.result_area.hide()
        self.result_area.setStyleSheet("""
            QTextBrowser {
                background: rgba(255, 255, 255, 10);
                border: 1px solid rgba(255, 255, 255, 15);
                border-left: 4px solid #00D2FF;
                padding: 15px;
                color: #FFFFFF;
                font-size: 13px;
                font-family: 'Segoe UI';
                border-radius: 8px;
                margin-top: 5px;
            }
        """)
        self.result_area.setMaximumHeight(400) # Maximum reach
        self.result_area.setFixedHeight(0) # Initially collapsed
        layout.addWidget(self.result_area)
        
        # Hardware section
        self.hardware_header = self._create_section("HARDWARE")
        layout.addWidget(self.hardware_header)
        
        def create_slider_row(icon_text, init_val, mini, maxi):
            row = QHBoxLayout()
            icon = QLabel(icon_text)
            icon.setStyleSheet("font-size: 14px; min-width: 24px;")
            slider = ModernSlider(Qt.Orientation.Horizontal)
            slider.setRange(mini, maxi)
            slider.setValue(init_val)
            row.addWidget(icon)
            row.addWidget(slider)
            return row, slider
            
        vol_row, self.vol_slider = create_slider_row("🔊", 50, 0, 100)
        bri_row, self.bri_slider = create_slider_row("☀️", 70, 0, 100)
        
        self.vol_container = QWidget(); self.vol_container.setLayout(vol_row)
        self.bri_container = QWidget(); self.bri_container.setLayout(bri_row)
        layout.addWidget(self.vol_container)
        layout.addWidget(self.bri_container)
        
        # AI Mode & Quick Actions
        self.ai_core_header = self._create_section("AI CORE")
        layout.addWidget(self.ai_core_header)
        
        mode_layout = QHBoxLayout()
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Jarvis", "Cyberpunk", "Matrix", "Tron", "Space", "Neon"])
        mode_layout.addWidget(QLabel("🧠"))
        mode_layout.addWidget(self.mode_combo, 1)
        self.mode_container = QWidget(); self.mode_container.setLayout(mode_layout)
        layout.addWidget(self.mode_container)

        # — Quick Model Switch (no dialog) —
        quick_ai_row = QHBoxLayout()
        quick_ai_row.setSpacing(6)
        quick_ai_row.addWidget(QLabel("🤖"))
        self.quick_provider_combo = QComboBox()
        self.quick_provider_combo.addItems(["auto", "groq", "openai", "deepseek", "gemini", "anthropic", "mistral", "ollama"])
        self.quick_provider_combo.setMinimumHeight(28)
        self.quick_provider_combo.setStyleSheet("QComboBox { font-size: 10px; padding: 4px 8px; }")
        quick_ai_row.addWidget(self.quick_provider_combo, 1)
        self.quick_model_combo = QComboBox()
        self.quick_model_combo.setEditable(True)
        self.quick_model_combo.setMinimumHeight(28)
        self.quick_model_combo.setStyleSheet("QComboBox { font-size: 10px; padding: 4px 8px; }")
        self.quick_model_combo.setPlaceholderText("model")
        quick_ai_row.addWidget(self.quick_model_combo, 1)
        self.btn_quick_apply = QPushButton("✔")
        self.btn_quick_apply.setFixedSize(28, 28)
        self.btn_quick_apply.setStyleSheet("background: rgba(0,255,65,15); color: #00FF41; border-radius: 6px; font-size: 12px; border: 1px solid rgba(0,255,65,30);")
        quick_ai_row.addWidget(self.btn_quick_apply)
        self.quick_ai_container = QWidget()
        self.quick_ai_container.setLayout(quick_ai_row)
        layout.addWidget(self.quick_ai_container)

        # Quick action grid
        quick_grid = QGridLayout()
        quick_grid.setSpacing(8)
        self.btn_dash = QPushButton("🌐 DASH")
        self.btn_mute = QPushButton("🔇 MUTE")
        self.btn_clip = QPushButton("📋 CLIP")
        self.btn_snap = QPushButton("📸 SNAP")
        self.btn_dash.setStyleSheet("background: rgba(0, 210, 255, 30); color: #00D2FF;")
        quick_grid.addWidget(self.btn_dash, 0, 0)
        quick_grid.addWidget(self.btn_mute, 0, 1)
        quick_grid.addWidget(self.btn_clip, 1, 0)
        quick_grid.addWidget(self.btn_snap, 1, 1)
        self.grid_container = QWidget(); self.grid_container.setLayout(quick_grid)
        layout.addWidget(self.grid_container)

        # AI Keys button
        self.btn_keys = QPushButton("🔑 AI KEYS")
        self.btn_keys.setStyleSheet("background: rgba(255,215,0,15); color: #FFD700; border: 1px solid rgba(255,215,0,30);")
        layout.addWidget(self.btn_keys)
        
        # Big Wake Button
        self.wake_btn = QPushButton("⚡ WAKE FLEXIE")
        self.wake_btn.setObjectName("WakeButton")
        layout.addWidget(self.wake_btn)

        # Version stamp
        self.ver_stamp = QLabel("FLEXIE 2.0 • HACKATHON BUILD")
        self.ver_stamp.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.ver_stamp.setStyleSheet("color: rgba(255,255,255,60); font-size: 9px; letter-spacing: 2px; margin-top: 5px;")
        layout.addWidget(self.ver_stamp)
        
        self._init_provider_quick_switch()
        self.refresh_provider_badge()
        self.container.adjustSize()
        self.setFixedHeight(self.container.sizeHint().height() + 20)

    def _init_provider_quick_switch(self):
        """Wire quick provider/model switch logic."""
        try:
            from utils.config import SUPPORTED_PROVIDERS as _SP
            def _on_provider_changed(text):
                pid = text.strip().lower() if text else "auto"
                combo = self.quick_model_combo
                combo.clear()
                if pid == "auto":
                    combo.addItems(["auto"])
                    combo.setCurrentText("auto")
                    combo.setEnabled(False)
                else:
                    models = _SP.get(pid, {}).get("models", [])
                    if models:
                        combo.addItems(models)
                    else:
                        combo.addItems(["tinyllama:latest","llama3:latest","mistral:latest"])
                    # Set current model
                    try:
                        from utils.config import Config as _C
                        cur = _C.get_model(pid) if pid != "ollama" else _C.OLLAMA_MODEL
                        if cur and combo.findText(cur) == -1:
                            combo.addItem(cur)
                        combo.setCurrentText(cur)
                    except: pass
                    combo.setEnabled(True)
            self.quick_provider_combo.currentTextChanged.connect(_on_provider_changed)
            # Init with current active
            try:
                from utils.config import Config as _C
                active = getattr(_C, 'ACTIVE_PROVIDER', 'auto')
                idx = self.quick_provider_combo.findText(active)
                if idx >= 0: self.quick_provider_combo.setCurrentIndex(idx)
                else: _on_provider_changed(active)
            except: pass
        except: pass

    def refresh_provider_badge(self):
        """Update badge + dots from Config. Called on show and every _update_stats."""
        try:
            from utils.config import Config as _C, SUPPORTED_PROVIDERS as _SP
            active = getattr(_C, 'ACTIVE_PROVIDER', 'auto')
            # Resolve display model
            if active == "auto":
                # Show first available provider's model
                model_disp = "fallback chain"
                dot_color = "#00D2FF"
                # Check if any key exists
                any_key = any(_C.get_api_key(pid) for pid in _SP)
                if not any_key: dot_color = "#FF3B30"
            else:
                model_disp = _C.get_model(active) if active != "ollama" else _C.OLLAMA_MODEL
                has_key = bool(_C.get_api_key(active)) if active != "ollama" else True
                dot_color = "#00FF41" if has_key else "#FF3B30"
            self.provider_label.setText(active.upper())
            self.provider_model_label.setText(model_disp or "—")
            self.provider_dot.setStyleSheet(f"color: {dot_color}; font-size: 14px; background: transparent; border: none;")
            # Update dots row
            _icons = {"groq":"⚡","gemini":"✦","openai":"●","deepseek":"◆","anthropic":"▲","mistral":"⬢","ollama":"◉"}
            for pid, lbl in self.provider_dots_widgets.items():
                has = bool(_C.get_api_key(pid)) if pid != "ollama" else True
                is_active = (active == pid) or (active == "auto" and pid == "groq")
                bg = "rgba(0,255,65,15)" if has else "rgba(255,255,255,6)"
                border = "rgba(0,255,65,40)" if is_active else "rgba(255,255,255,10)"
                color = "#00FF41" if has else "rgba(255,255,255,90)"
                lbl.setStyleSheet(f"color: {color}; font-size: 9px; background: {bg}; border: 1px solid {border}; border-radius: 6px; padding: 2px 6px;")
                # Highlight active with bold
                if is_active:
                    lbl.setStyleSheet(lbl.styleSheet() + " font-weight: 700;")
        except Exception as e:
            pass
        # Update quick combo current model display
        try:
            from utils.config import Config as _C
            if hasattr(self, 'quick_provider_combo'):
                # don't override if user is interacting
                pass
        except: pass
    
    def set_minimal_mode(self, minimal=True):
        """Toggles between full dashboard and minimal search popup."""
        self.header_container.setVisible(not minimal) # HIDE HEADER TOO
        self.metrics_frame.setVisible(not minimal)
        self.status_label.setVisible(not minimal)
        if hasattr(self, 'provider_badge'):
            self.provider_badge.setVisible(not minimal)
        if hasattr(self, 'dots_container'):
            self.dots_container.setVisible(not minimal)
        self.hardware_header.setVisible(not minimal)
        self.vol_container.setVisible(not minimal)
        self.bri_container.setVisible(not minimal)
        self.ai_core_header.setVisible(not minimal)
        self.mode_container.setVisible(not minimal)
        if hasattr(self, 'quick_ai_container'):
            self.quick_ai_container.setVisible(not minimal)
        self.grid_container.setVisible(not minimal)
        if hasattr(self, 'btn_keys'):
            self.btn_keys.setVisible(not minimal)
        self.wake_btn.setVisible(not minimal)
        self.ver_stamp.setVisible(not minimal)
        
        # Adjust layout spacing
        self.container.layout().setSpacing(8 if minimal else 12) # Slightly more space
        self.container.layout().setContentsMargins(20, 20, 20, 20) # Restore breathing room
        
        # Resize window for the new content
        self.container.adjustSize()
        self.setFixedHeight(self.container.sizeHint().height() + 20)

        # Ultra-smooth glass shadow
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(80)
        shadow.setOffset(0, 25)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.container.setGraphicsEffect(shadow)

        self.anim_group = QParallelAnimationGroup(self)
        self.pos_anim = QPropertyAnimation(self, b"pos")
        self.op_anim = QPropertyAnimation(self, b"windowOpacity")
        self.anim_group.addAnimation(self.pos_anim)
        self.anim_group.addAnimation(self.op_anim)
        self.pos_anim.setDuration(400)
        self.op_anim.setDuration(350)
        self.pos_anim.setEasingCurve(QEasingCurve.Type.OutQuart)

    def _create_section(self, text):
        lbl = QLabel(text)
        lbl.setObjectName("SectionHeader")
        return lbl

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_start)
            event.accept()

    def toggle_pin(self, pinned):
        flags = self.windowFlags()
        if pinned:
            flags |= Qt.WindowType.WindowStaysOnTopHint
        else:
            flags &= ~Qt.WindowType.WindowStaysOnTopHint
        self.setWindowFlags(flags)
        self.show() # Reset flags requires re-showing

    def show_animated(self, target_pos):
        self.setWindowOpacity(0.0)
        self.show()
        start_pos = QPoint(target_pos.x() + 40, target_pos.y() + 20)
        self.pos_anim.setStartValue(start_pos)
        self.pos_anim.setEndValue(target_pos)
        self.op_anim.setStartValue(0.0)
        self.op_anim.setEndValue(1.0)
        self.anim_group.start()

    def hide_animated(self):
        try: self.op_anim.finished.disconnect(self.hide)
        except: pass
        self.op_anim.setDuration(250)
        self.op_anim.setEndValue(0.0)
        self.op_anim.finished.connect(self.hide)
        self.op_anim.start()
        
    def paintEvent(self, event):
        # PERFORMANCE: Skip heavy grid rendering if CPU is pinned
        if hasattr(self, "_cpu_load") and self._cpu_load > 90:
            return
            
        # Draw some subtle tech grid lines behind the glass container
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.container.geometry()
        
        # Grid overlay on the frame
        painter.setClipRect(rect)
        painter.setPen(QPen(QColor(255,255,255,4), 1))
        for x in range(rect.left(), rect.right(), 20):
            painter.drawLine(x, rect.top(), x, rect.bottom())
        for y in range(rect.top(), rect.bottom(), 20):
            painter.drawLine(rect.left(), y, rect.right(), y)

class Particle:
    """A single floating micro-particle with fading trail and state-reactive behavior."""
    def __init__(self, cx, cy, radius):
        self.angle    = random.uniform(0, math.pi * 2)
        self.distance = random.uniform(radius * 0.6, radius * 1.6)
        self.base_speed  = random.uniform(0.008, 0.04)
        self.speed    = self.base_speed
        self.size     = random.uniform(1.2, 3.2)
        self.life     = random.uniform(0.6, 1.0)
        self.decay    = random.uniform(0.008, 0.022)
        self.history  = []   # trail points

    def update(self, state, cx, cy):
        t = time.time()
        # State-reactive speed and orbit behaviour
        if state == "PROCESSING":
            self.speed = min(self.base_speed * 4.0, self.speed + 0.002)   # accelerate
            self.distance += math.sin(t * 3 + self.angle) * 0.4
        elif state == "SPEAKING":
            self.speed = self.base_speed * 2.0
            self.distance += math.sin(t * 12 + self.angle) * 1.5  # burst outward
        elif state == "LISTENING":
            self.speed = self.base_speed * 1.2
            self.distance = max(30, self.distance - 0.3)           # draw inward
        else:
            self.speed = self.base_speed
            self.distance += math.sin(t * 1.5 + self.angle) * 0.3

        self.distance = max(20, min(self.distance, 160))
        self.angle   += self.speed
        self.life    -= self.decay

        x = cx + math.cos(self.angle) * self.distance
        y = cy + math.sin(self.angle) * self.distance
        self.history.append(QPointF(x, y))
        if len(self.history) > 8:
            self.history.pop(0)
        return x, y


class EnhancedFlexieOrb(QWidget):
    # ── animatable properties ────────────────────────────────────────────────
    @pyqtProperty(float)
    def scale_factor(self): return self._scale
    @scale_factor.setter
    def scale_factor(self, v): self._scale = v; self.update()

    @pyqtProperty(float)
    def view_scale(self): return self._view_scale
    @view_scale.setter
    def view_scale(self, v): self._view_scale = v; self.update()

    @pyqtProperty(float)
    def eye_openness(self): return self._eye_openness
    @eye_openness.setter
    def eye_openness(self, v): self._eye_openness = v; self.update()

    @pyqtProperty(float)
    def glow_intensity(self): return self._glow_intensity
    @glow_intensity.setter
    def glow_intensity(self, v): self._glow_intensity = v; self.update()

    @pyqtProperty(float)
    def wake_burst(self): return self._wake_burst
    @wake_burst.setter
    def wake_burst(self, v): self._wake_burst = v; self.update()

    # colour interpolation target (0-1 blend toward new state colour)
    @pyqtProperty(float)
    def color_blend(self): return self._color_blend
    @color_blend.setter
    def color_blend(self, v): self._color_blend = v; self.update()

    # ── state colour palette ─────────────────────────────────────────────────
    STATE_COLORS = {
        "IDLE":       ("#00FF41", "#008F11"),   # Neon Green
        "SLEEP":      ("#00CC33", "#005511"),   # Dim Neon Green
        "MINIMIZED":  ("#00CC33", "#005511"),
        "WAKE":       ("#00FF41", "#00AA22"),
        "LISTENING":  ("#39FF14", "#00CC44"),   # Bright Green
        "PROCESSING": ("#FFD700", "#FF8C00"),   # Amber/Gold
        "SPEAKING":   ("#00FFFF", "#0088FF"),   # Cyan/Blue
        "SUCCESS":    ("#CC44FF", "#8800FF"),   # Purple
        "WARNING":    ("#FF8C00", "#FF4400"),   # Orange
        "ALERT":      ("#FF3B30", "#FF0000"),   # Red
        "ERROR":      ("#FF3B30", "#FF0000"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(300, 300)
        self.state = "SLEEP"
        self.mode  = "jarvis"

        # core animation state
        self._scale         = 1.0
        self._view_scale    = 0.40
        self._eye_openness  = 0.0
        self._glow_intensity= 0.0
        self._rot           = 0.0
        self._eye_blink     = 0.0
        self._pulse         = 0.0
        self._wake_burst    = 0.0
        self._scan_line     = 0.0
        self._color_blend   = 0.0
        self._frame_count   = 0

        # colour transition
        self._accent_from   = QColor("#00FF41")
        self._accent_to     = QColor("#00FF41")
        self._secondary_from= QColor("#008F11")
        self._secondary_to  = QColor("#008F11")

        # eye scan (PROCESSING) – automated left→right→up→down cycle
        self._scan_phase    = 0   # 0=→, 1=←, 2=↑, 3=↓
        self._scan_t        = 0.0
        self._scan_eye_dx   = 0.0
        self._scan_eye_dy   = 0.0

        # radar sweep (LISTENING)
        self._radar_angle   = 0.0

        # mouth pulse (SPEAKING)
        self._mouth_open    = 0.0

        # energy core pulse
        self._core_pulse    = 0.0

        self.setMouseTracking(True)
        self._mouse_pos = QPointF(150.0, 150.0)
        self.particles  = []

        # ── breathing animation ─────────────────────────────────────────────
        self.breath = QPropertyAnimation(self, b"scale_factor")
        self.breath.setDuration(4000)
        self.breath.setStartValue(0.97)
        self.breath.setEndValue(1.03)
        self.breath.setEasingCurve(QEasingCurve.Type.InOutSine)
        self.breath.setLoopCount(-1)
        self.breath.start()

        # ── view / eye animations ───────────────────────────────────────────
        self.view_anim = QPropertyAnimation(self, b"view_scale")
        self.view_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.eye_anim = QPropertyAnimation(self, b"eye_openness")
        self.eye_anim.setEasingCurve(QEasingCurve.Type.OutBack)

        # ── colour transition animation ─────────────────────────────────────
        self.color_anim = QPropertyAnimation(self, b"color_blend")
        self.color_anim.setDuration(600)
        self.color_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)

        # ── wake burst ──────────────────────────────────────────────────────
        self.burst_anim = QPropertyAnimation(self, b"wake_burst")
        self.burst_anim.setDuration(900)
        self.burst_anim.setStartValue(1.0)
        self.burst_anim.setEndValue(0.0)
        self.burst_anim.setEasingCurve(QEasingCurve.Type.OutQuad)

        # ── wake sequence ───────────────────────────────────────────────────
        self.wake_seq = QSequentialAnimationGroup(self)
        _su = QPropertyAnimation(self, b"view_scale")
        _su.setDuration(500); _su.setStartValue(0.40); _su.setEndValue(1.0)
        _su.setEasingCurve(QEasingCurve.Type.OutBack)
        _eo = QPropertyAnimation(self, b"eye_openness")
        _eo.setDuration(600); _eo.setStartValue(0.0); _eo.setEndValue(1.0)
        _eo.setEasingCurve(QEasingCurve.Type.OutElastic)
        self.wake_seq.addAnimation(_su)
        self.wake_seq.addAnimation(_eo)

        # ── main render timer (~60 fps) ─────────────────────────────────────
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_anim)
        self.timer.start(16)

    # ── mouse events – pass through so window stays draggable ───────────────
    def mouseMoveEvent(self, event):
        self._mouse_pos = event.position(); event.ignore()
    def mousePressEvent(self, event):   event.ignore()
    def mouseReleaseEvent(self, event): event.ignore()
    def leaveEvent(self, event):
        self._mouse_pos = QPointF(150.0, 150.0); event.ignore()

    # ── helpers ─────────────────────────────────────────────────────────────
    def _lerp_color(self, c1, c2, t):
        t = max(0.0, min(1.0, t))
        return QColor(
            int(c1.red()   + (c2.red()   - c1.red())   * t),
            int(c1.green() + (c2.green() - c1.green()) * t),
            int(c1.blue()  + (c2.blue()  - c1.blue())  * t),
        )

    def _get_face_path(self, center, offset, w, h):
        path = QPainterPath()
        path.addRoundedRect(
            QRectF(center.x() + offset.x() - w/2,
                   center.y() + offset.y() - h/2, w, h),
            35 * self._view_scale, 35 * self._view_scale)
        return path

    # ── animation update ─────────────────────────────────────────────────────
    def _update_anim(self):
        self._frame_count += 1
        cpu = psutil.cpu_percent()
        if cpu > 90 and self._frame_count % 4 != 0: return
        if cpu > 70 and self._frame_count % 2 != 0: return
        if not self.isVisible(): return

        t = time.time()
        v  = self._view_scale
        st = self.state

        # ring rotation speed per state
        rot_speeds = {"PROCESSING": 6.0, "LISTENING": 2.5,
                      "SPEAKING": 3.5, "SLEEP": 0.5, "MINIMIZED": 0.3}
        self._rot = (self._rot + rot_speeds.get(st, 1.2)) % 360

        # scan line (PROCESSING)
        self._scan_line = (t * 130) % 300

        # radar sweep angle (LISTENING)
        if st == "LISTENING":
            self._radar_angle = (self._radar_angle + 2.5) % 360

        # pulse & glow
        if st == "LISTENING":
            self._pulse = abs(math.sin(t * 6)) * 22
            self._glow_intensity = 0.75 + 0.25 * abs(math.sin(t * 8))
        elif st == "SPEAKING":
            self._pulse = abs(math.sin(t * 10)) * 18
            self._glow_intensity = 0.85 + 0.15 * abs(math.sin(t * 12))
            self._mouth_open = abs(math.sin(t * 9))
        elif st == "PROCESSING":
            self._pulse = abs(math.sin(t * 14)) * 30
            self._glow_intensity = 0.6 + 0.4 * abs(math.sin(t * 5))
        elif st in ("SLEEP", "MINIMIZED"):
            self._pulse = 0; self._glow_intensity = 0.06 * abs(math.sin(t * 0.7))
        else:
            self._pulse = 0; self._glow_intensity = 0.28 + 0.1 * math.sin(t * 1.8)

        # energy core pulse
        core_speeds = {"PROCESSING": 8.0, "SPEAKING": 11.0,
                       "LISTENING": 5.0, "SLEEP": 0.6}
        self._core_pulse = 0.4 + 0.6 * abs(math.sin(t * core_speeds.get(st, 1.5)))

        # eye scanning (PROCESSING: automated L→R→U→D cycle)
        if st == "PROCESSING":
            self._scan_t += 0.02
            cycle = self._scan_t % (math.pi * 4)
            quad  = int(cycle / math.pi) % 4
            phase = (cycle % math.pi) / math.pi   # 0→1 within each quadrant
            if quad == 0:  # left → right
                self._scan_eye_dx = math.sin(phase * math.pi) * 8
                self._scan_eye_dy = 0
            elif quad == 1:  # right → left
                self._scan_eye_dx = -math.sin(phase * math.pi) * 8
                self._scan_eye_dy = 0
            elif quad == 2:  # up → down
                self._scan_eye_dx = 0
                self._scan_eye_dy = -math.sin(phase * math.pi) * 6
            else:  # down → up
                self._scan_eye_dx = 0
                self._scan_eye_dy = math.sin(phase * math.pi) * 6
        else:
            self._scan_eye_dx = 0; self._scan_eye_dy = 0

        # eye blink (SPEAKING)
        if st == "SPEAKING":
            self._eye_blink = abs(math.sin(t * 12)) * 8
        else:
            self._eye_blink = 0

        # spawn particles
        max_p = {"SLEEP": 10, "MINIMIZED": 6, "PROCESSING": 60,
                 "SPEAKING": 50, "LISTENING": 35}
        cap = max_p.get(st, 25)
        if random.random() < (0.15 if st in ("SLEEP","MINIMIZED") else 0.55):
            if len(self.particles) < cap:
                self.particles.append(Particle(0, 0, 80))

        # expire dead particles
        self.particles = [p for p in self.particles if p.life > 0]

        try: self.update()
        except: pass

    # ── state change ─────────────────────────────────────────────────────────
    def set_state(self, state):
        new_st = state.upper()

        # start colour transition
        acc_hex, sec_hex = self.STATE_COLORS.get(new_st, self.STATE_COLORS["IDLE"])
        self._accent_from   = self._lerp_color(self._accent_from,   self._accent_to,   self._color_blend)
        self._secondary_from= self._lerp_color(self._secondary_from,self._secondary_to,self._color_blend)
        self._accent_to     = QColor(acc_hex)
        self._secondary_to  = QColor(sec_hex)
        self.color_anim.stop()
        self._color_blend = 0.0
        self.color_anim.setStartValue(0.0)
        self.color_anim.setEndValue(1.0)
        self.color_anim.start()

        self.state = new_st
        is_active = new_st in ("WAKE","LISTENING","SPEAKING","PROCESSING")

        if new_st == "WAKE":
            self.wake_seq.stop()
            self._view_scale = 0.40; self._eye_openness = 0.0
            self.wake_seq.start()
            self.burst_anim.stop(); self._wake_burst = 1.0; self.burst_anim.start()
            self.state = "LISTENING"
        elif is_active:
            self.view_anim.stop(); self.view_anim.setDuration(400)
            self.view_anim.setEndValue(1.0); self.view_anim.start()
            self.eye_anim.stop(); self.eye_anim.setDuration(350)
            self.eye_anim.setEndValue(1.0); self.eye_anim.start()
        else:
            dur_v = 1500 if new_st == "SLEEP" else 800
            end_v = 0.40 if new_st == "SLEEP" else 0.30
            self.view_anim.stop(); self.view_anim.setDuration(dur_v)
            self.view_anim.setEndValue(end_v); self.view_anim.start()
            self.eye_anim.stop(); self.eye_anim.setDuration(1000 if new_st == "SLEEP" else 500)
            self.eye_anim.setEndValue(0.0); self.eye_anim.start()

        # breath speed
        dur_b = {"LISTENING":600,"SPEAKING":800,"PROCESSING":350,
                 "SLEEP":5000,"MINIMIZED":3500}.get(self.state, 2500)
        self.breath.stop(); self.breath.setDuration(dur_b); self.breath.start()

    # ── paint ────────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        center  = QPointF(150.0, 150.0)
        t       = time.time()
        v       = self._view_scale
        scale   = max(0.1, self._scale * v)
        st      = self.state
        is_sleep= st in ("SLEEP","MINIMIZED")

        # ── interpolated accent colour ───────────────────────────────────────
        accent   = self._lerp_color(self._accent_from,    self._accent_to,    self._color_blend)
        secondary= self._lerp_color(self._secondary_from, self._secondary_to, self._color_blend)

        # ── PARALLAX OFFSETS (max 8px) ───────────────────────────────────────
        mx = (self._mouse_pos.x() - center.x()) / 150.0 * 8.0
        my = (self._mouse_pos.y() - center.y()) / 150.0 * 8.0

        def layer(fx, fy=None):
            """Return QPointF offset for a depth layer (0-1 factor)."""
            if fy is None: fy = fx
            return QPointF(center.x() + mx * fx, center.y() + my * fy)

        bg_c     = layer(0.10)   # neural background
        ring_c   = layer(0.30)   # outer rings / visualiser
        part_c   = layer(0.50)   # particles
        face_c   = layer(0.70)   # face body + core
        eye_c    = layer(1.00)   # eyes
        ar       = accent.red(); ag = accent.green(); ab = accent.blue()

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 0 – Neural background (clipped to face shape)
        # ═══════════════════════════════════════════════════════════════════
        if v > 0.3:
            clip = self._get_face_path(bg_c, QPointF(0,0), 110*scale, 95*scale)
            painter.setClipPath(clip)
            painter.setPen(QPen(QColor(ar, ag, ab, int(30*v)), 1))
            for i in range(10):
                nx1 = bg_c.x() + math.sin(t*0.7 + i*0.9) * 50*scale
                ny1 = bg_c.y() + math.cos(t*0.6 + i*1.1) * 45*scale
                nx2 = bg_c.x() + math.sin(t*0.9 - i*0.7) * 50*scale
                ny2 = bg_c.y() + math.cos(t*0.8 + i*0.8) * 45*scale
                painter.drawLine(QPointF(nx1, ny1), QPointF(nx2, ny2))
            painter.setClipping(False)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 0.5 – Wake burst ring
        # ═══════════════════════════════════════════════════════════════════
        if self._wake_burst > 0.01:
            br = 80 + 130 * (1.0 - self._wake_burst)
            ba = int(255 * self._wake_burst)
            bg = QRadialGradient(center, br)
            bg.setColorAt(0,   QColor(ar, ag, ab, 0))
            bg.setColorAt(0.55,QColor(ar, ag, ab, ba))
            bg.setColorAt(1,   QColor(ar, ag, ab, 0))
            painter.setBrush(bg); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(center, br, br)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 1 – Volumetric ambient glow
        # ═══════════════════════════════════════════════════════════════════
        if self._glow_intensity > 0.01 and v > 0.25:
            glow_r = (140 + self._pulse) * scale
            ga     = int(110 * self._glow_intensity * v)
            gg = QRadialGradient(ring_c, glow_r)
            gg.setColorAt(0,   QColor(ar, ag, ab, ga))
            gg.setColorAt(0.45,QColor(secondary.red(), secondary.green(), secondary.blue(), int(ga*0.55)))
            gg.setColorAt(1,   Qt.GlobalColor.transparent)
            painter.setBrush(gg); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(ring_c, glow_r, glow_r)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 2 – Circular audio spectrum (30% parallax)
        # ═══════════════════════════════════════════════════════════════════
        if v > 0.5 and st in ("LISTENING","SPEAKING","PROCESSING"):
            num_bars = 52
            vis_r    = 108 * scale
            for i in range(num_bars):
                rad_a = math.radians((i / num_bars) * 360 + self._rot * 0.4)
                if st == "PROCESSING":
                    val = math.sin(t * 6 + i * 0.55) * 0.5 + 0.5
                elif st == "SPEAKING":
                    val = abs(math.sin(t * 8 + i * 0.3)) * random.uniform(0.5, 1.0)
                else:  # LISTENING
                    val = abs(math.sin(t * 4 + i * 0.4)) * random.uniform(0.1, 0.5)
                blen = (8 + 22 * val) * scale
                p1 = QPointF(ring_c.x() + math.cos(rad_a) * vis_r,
                             ring_c.y() + math.sin(rad_a) * vis_r)
                p2 = QPointF(ring_c.x() + math.cos(rad_a) * (vis_r + blen),
                             ring_c.y() + math.sin(rad_a) * (vis_r + blen))
                bc = QColor(ar, ag, ab, int(210 * val * v))
                painter.setPen(QPen(bc, 2.2*scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawLine(p1, p2)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 3 – Holographic rings (30% parallax)
        # ═══════════════════════════════════════════════════════════════════
        if v > 0.45:
            ri = int(self._rot)

            # outer dashed orbit ring
            painter.setPen(QPen(QColor(ar, ag, ab, int(55*v)), 1.0*scale, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(ring_c, 97*scale, 97*scale)

            if st == "PROCESSING":
                # Three stacked rotating arcs at different speeds
                for idx, (span_deg, alpha, ring_r, speed_mult) in enumerate([
                        (140, 230, 97, 1.0), (90, 170, 88, -1.5), (55, 110, 78, 2.2)]):
                    rc = QPointF(ring_c.x(), ring_c.y())
                    rr = ring_r * scale
                    ar2 = QRectF(rc.x()-rr, rc.y()-rr, rr*2, rr*2)
                    start = int((ri * speed_mult * 16) % (360*16))
                    clr = QColor(ar, ag, ab, alpha)
                    pen_w = (4.0 - idx * 0.8) * scale
                    painter.setPen(QPen(clr, pen_w, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    painter.drawArc(ar2.toRect(), start, span_deg*16)
            else:
                # Two breathing arcs
                rr = 97 * scale
                ar2 = QRectF(ring_c.x()-rr, ring_c.y()-rr, rr*2, rr*2)
                off = int(22 * math.sin(t * 4))
                clr = QColor(ar, ag, ab, 185)
                painter.setPen(QPen(clr, 3.2*scale, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                painter.drawArc(ar2.toRect(), (ri + off) * 16, 80*16)
                painter.drawArc(ar2.toRect(), (ri + 180 + off) * 16, 80*16)

            # LISTENING – radar sweep
            if st == "LISTENING":
                sweep_r = 112 * scale
                sweep_end = QPointF(
                    ring_c.x() + math.cos(math.radians(self._radar_angle)) * sweep_r,
                    ring_c.y() + math.sin(math.radians(self._radar_angle)) * sweep_r)
                sweep_grad = QLinearGradient(ring_c, sweep_end)
                sweep_grad.setColorAt(0, QColor(ar, ag, ab, 0))
                sweep_grad.setColorAt(1, QColor(ar, ag, ab, 160))
                painter.setPen(QPen(QBrush(sweep_grad), 2.0*scale))
                painter.drawLine(ring_c, sweep_end)
                # radar fill arc
                rfill = QRadialGradient(ring_c, sweep_r)
                rfill.setColorAt(0,   QColor(ar, ag, ab, 18))
                rfill.setColorAt(1,   QColor(ar, ag, ab, 0))
                painter.setBrush(rfill); painter.setPen(Qt.PenStyle.NoPen)
                painter.drawPie(QRectF(ring_c.x()-sweep_r, ring_c.y()-sweep_r,
                                       sweep_r*2, sweep_r*2),
                                int((self._radar_angle - 30) * 16), 30*16)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 4 – Particles with fading trails (50% parallax)
        # ═══════════════════════════════════════════════════════════════════
        if v > 0.4:
            for p in self.particles:
                px, py = p.update(st, part_c.x(), part_c.y())
                if len(p.history) > 1:
                    for k in range(len(p.history)-1):
                        seg_alpha = int(max(0, p.life) * 90 * (k / len(p.history)))
                        trail_c = QColor(ar, ag, ab, seg_alpha)
                        painter.setPen(QPen(trail_c, p.size * 0.5 * scale))
                        painter.drawLine(p.history[k], p.history[k+1])
                dot_c = QColor(ar, ag, ab, int(255 * max(0, p.life) * v))
                painter.setBrush(dot_c); painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(px, py), p.size*scale, p.size*scale)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 5 – Face body + energy core (70% parallax)
        # ═══════════════════════════════════════════════════════════════════
        face_w = 102 * scale; face_h = 87 * scale
        face_rect = QRectF(face_c.x() - face_w/2, face_c.y() - face_h/2, face_w, face_h)

        # energy core (behind face body)
        core_r = face_w * 0.55 * self._core_pulse
        cg = QRadialGradient(face_c, core_r)
        cg.setColorAt(0, QColor(ar, ag, ab, int(80 * self._glow_intensity * self._core_pulse)))
        cg.setColorAt(0.4, QColor(ar, ag, ab, int(30 * self._core_pulse * v)))
        cg.setColorAt(1, Qt.GlobalColor.transparent)
        painter.setBrush(cg); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(face_c, core_r*1.4, core_r*1.4)

        # face body gradient
        bg_tint_c = QColor(8, 18, 8, int(210 * v))   # deep dark green-tinted bg
        bg2 = QRadialGradient(face_c, face_w)
        bg2.setColorAt(0,   QColor(bg_tint_c.red(), bg_tint_c.green(), bg_tint_c.blue(), int(210*v)))
        bg2.setColorAt(0.65,QColor(secondary.red(), secondary.green(), secondary.blue(), int(60*v)))
        bg2.setColorAt(1,   QColor(2, 8, 2, int(180*v)))
        painter.setBrush(bg2)
        border_a = int(130*v + self._pulse * 0.9)
        painter.setPen(QPen(QColor(ar, ag, ab, border_a), 2.5*scale))
        painter.drawRoundedRect(face_rect, 35*v, 35*v)

        # SPEAKING – mouth pulse bar at bottom of face
        if st == "SPEAKING" and v > 0.5:
            mouth_y  = face_c.y() + face_h * 0.3
            mouth_w  = face_w * 0.5 * (0.5 + self._mouth_open * 0.5)
            mouth_h  = max(2.0, 6 * scale * self._mouth_open)
            mc = QColor(ar, ag, ab, int(200 * self._mouth_open * v))
            painter.setBrush(mc); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(
                QRectF(face_c.x() - mouth_w/2, mouth_y - mouth_h/2, mouth_w, mouth_h),
                3, 3)

        # PROCESSING – scan line inside face
        if st == "PROCESSING" and v > 0.35:
            painter.setClipPath(self._get_face_path(face_c, QPointF(0,0), face_w, face_h))
            scan_a = int(50 * v)
            scan_y = face_c.y() - face_h/2 + (self._scan_line % face_h)
            painter.setPen(QPen(QColor(ar, ag, ab, scan_a), 2.5))
            painter.drawLine(QPointF(face_c.x() - face_w/2, scan_y),
                             QPointF(face_c.x() + face_w/2, scan_y))
            flg = QRadialGradient(QPointF(face_c.x(), scan_y), face_w*0.75)
            flg.setColorAt(0, QColor(ar, ag, ab, int(70*v)))
            flg.setColorAt(1, Qt.GlobalColor.transparent)
            painter.setBrush(flg); painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QPointF(face_c.x(), scan_y), face_w*0.55, 5)
            painter.setClipping(False)

        # ── Glass reflection (top-left sheen) ───────────────────────────────
        hl = QPainterPath()
        hl.addRoundedRect(QRectF(face_rect.x(), face_rect.y(),
                                  face_rect.width(), face_rect.height()*0.38),
                           35*v, 35*v)
        hl_g = QLinearGradient(face_rect.topLeft(),
                                QPointF(face_rect.left(), face_rect.center().y()))
        hl_g.setColorAt(0, QColor(255, 255, 255, int(70*v)))
        hl_g.setColorAt(1, QColor(255, 255, 255, 0))
        painter.setBrush(hl_g); painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPath(hl)

        # moving holographic sheen (diagonal shimmer)
        sheen_phase = (t * 0.5) % 2.0 - 1.0
        sheen_x = face_rect.left() + face_rect.width() * (0.5 + sheen_phase * 0.6)
        sheen_g = QLinearGradient(QPointF(sheen_x - 30, face_rect.top()),
                                   QPointF(sheen_x + 30, face_rect.bottom()))
        sheen_g.setColorAt(0, QColor(255,255,255, 0))
        sheen_g.setColorAt(0.5, QColor(255,255,255, int(28*v)))
        sheen_g.setColorAt(1, QColor(255,255,255, 0))
        painter.setBrush(sheen_g); painter.setPen(Qt.PenStyle.NoPen)
        painter.setClipPath(self._get_face_path(face_c, QPointF(0,0), face_w, face_h))
        painter.drawRect(face_rect)
        painter.setClipping(False)

        # ═══════════════════════════════════════════════════════════════════
        # LAYER 6 – Eyes (100% parallax)
        # ═══════════════════════════════════════════════════════════════════
        eye_gap = 30 * scale
        eye_cx_l = eye_c.x() - eye_gap
        eye_cx_r = eye_c.x() + eye_gap
        eye_cy   = eye_c.y() - 8 * scale
        eye_w    = 26 * scale

        if is_sleep or self._eye_openness < 0.05:
            # sleeping slit
            slit_h = max(1.5, 2.0 * scale)
            painter.setBrush(QColor(ar, ag, ab, int(110*v)))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRoundedRect(QRectF(eye_cx_l-eye_w/2, eye_cy-slit_h/2, eye_w, slit_h), 2, 2)
            painter.drawRoundedRect(QRectF(eye_cx_r-eye_w/2, eye_cy-slit_h/2, eye_w, slit_h), 2, 2)
        else:
            eye_h = max(3.0, (12 + self._eye_blink) * self._eye_openness) * scale

            # PROCESSING scan override; else follow mouse
            if st == "PROCESSING":
                p_dx = self._scan_eye_dx * scale
                p_dy = self._scan_eye_dy * scale
            else:
                p_dx = (self._mouse_pos.x() - center.x()) / 150.0 * (eye_w * 0.18)
                p_dy = (self._mouse_pos.y() - center.y()) / 150.0 * (eye_h * 0.18)

            for ecx in (eye_cx_l, eye_cx_r):
                # eye glow halo
                eg = QRadialGradient(QPointF(ecx, eye_cy), 30*scale)
                eg.setColorAt(0,   QColor(ar, ag, ab, int(230 * self._eye_openness)))
                eg.setColorAt(0.5, QColor(ar, ag, ab, int(90  * self._eye_openness)))
                eg.setColorAt(1,   Qt.GlobalColor.transparent)
                painter.setBrush(eg); painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(QPointF(ecx, eye_cy), 30*scale, 20*scale)

                # eye body
                painter.setBrush(accent)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRoundedRect(
                    QRectF(ecx-eye_w/2, eye_cy-eye_h/2, eye_w, eye_h), 6, 6)

                # PROCESSING – iris spinner
                if st == "PROCESSING":
                    painter.setPen(QPen(QColor(255,255,255,160), 1.5))
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    ir = eye_h * 0.38
                    painter.drawArc(
                        QRectF(ecx-ir, eye_cy-ir, ir*2, ir*2),
                        int(self._rot*16), 100*16)
                    painter.drawArc(
                        QRectF(ecx-ir, eye_cy-ir, ir*2, ir*2),
                        int(self._rot*16 + 180*16), 100*16)

                # pupil highlight (tracks mouse / scan)
                hw = eye_w * 0.24; hh = eye_h * 0.32
                painter.setBrush(QColor(255, 255, 255, int(230 * self._eye_openness)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawEllipse(
                    QPointF(ecx + eye_w*0.14 + p_dx, eye_cy - eye_h*0.14 + p_dy),
                    hw, hh)

class FlexieUI(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | 
                           Qt.WindowType.WindowStaysOnTopHint | 
                           Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        
        self.orb = EnhancedFlexieOrb()
        self.layout.addWidget(self.orb)
        self.setFixedSize(300, 300)
        
        self.drag_pos = QPoint()
        self._last_activity = time.time()
        
        self.udp_sock = QUdpSocket(self)
        self.udp_sock.bind(QHostAddress.SpecialAddress.LocalHost, 9886)
        self.udp_sock.readyRead.connect(self._process_udp)
        
        self.panel = ControlPopup()
        self._connect_signals()
        
        # Center on screen
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.center() - self.rect().center())
        
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(self._handle_idle)
        self.idle_timer.start(10000)
        
        self.stats_timer = QTimer(self)
        self.stats_timer.timeout.connect(self._update_stats)
        self.stats_timer.start(2000)
        
        self._setup_tray()
        
        # Start global hotkey listener
        self.hotkey_thread = HotkeyListener(self)
        self.hotkey_thread.hotkey_signal.connect(self._handle_hotkey)
        self.hotkey_thread.start()
        
        self.show()

    def _handle_hotkey(self):
        """Called when Ctrl+F is pressed globally."""
        if self.panel.isVisible():
            self.panel.hide_animated()
        else:
            self.panel.set_minimal_mode(True) # MINIMAL MODE ON HOTKEY
            self.panel.result_area.hide() 
            self.panel.result_area.setFixedHeight(0) # Collapse result area
            self._reflow_ui()
            self.panel.show_animated(self.pos() + QPoint(290, -100))
            self.panel.spotlight.setFocus()
        self._set_activity()

    def _connect_signals(self):
        self.panel.wake_btn.clicked.connect(self._wake)
        self.panel.btn_dash.clicked.connect(self._open_dashboard)
        self.panel.btn_mute.clicked.connect(lambda: self._send_udp("SET_VOLUME:0" if "MUTE" in self.panel.btn_mute.text() else "SET_VOLUME:50"))
        self.panel.btn_snap.clicked.connect(lambda: self._send_udp("vision_capture"))
        self.panel.btn_clip.clicked.connect(self._scan_clipboard)
        if hasattr(self.panel, 'btn_keys'):
            self.panel.btn_keys.clicked.connect(self._open_keys_dialog)
        if hasattr(self.panel, 'btn_provider_refresh'):
            self.panel.btn_provider_refresh.clicked.connect(self._refresh_provider_badge)
        if hasattr(self.panel, 'btn_quick_apply'):
            self.panel.btn_quick_apply.clicked.connect(self._apply_quick_switch)
        self.panel.btn_min.clicked.connect(lambda: self.panel.set_minimal_mode(True))
        self.panel.btn_pin.toggled.connect(self.panel.toggle_pin)
        self.panel.spotlight.returnPressed.connect(self._send_spotlight)
        self.panel.mode_combo.currentTextChanged.connect(self._change_mode)
        self.panel.vol_slider.valueChanged.connect(self._set_volume)
        self.panel.bri_slider.valueChanged.connect(self._set_brightness)

    def _setup_tray(self):
        self.tray = QSystemTrayIcon(self)
        px = QPixmap(32, 32)
        px.fill(Qt.GlobalColor.transparent)
        p = QPainter(px)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        gradient = QRadialGradient(16, 16, 16)
        gradient.setColorAt(0, QColor("#00D2FF"))
        gradient.setColorAt(1, QColor("#0040FF"))
        p.setBrush(gradient)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(4, 4, 24, 24)
        p.setPen(QPen(QColor(255, 255, 255, 200), 2))
        p.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        p.drawText(QRect(4, 4, 24, 24), Qt.AlignmentFlag.AlignCenter, "F")
        p.end()
        self.tray.setIcon(QIcon(px))
        
        menu = QMenu()
        show_action = menu.addAction("Show Controls")
        show_action.triggered.connect(lambda: self.panel.show_animated(self.pos() + QPoint(290, -100)))
        menu.addSeparator()
        menu.addAction("Wake Flexie").triggered.connect(self._wake)
        menu.addSeparator()
        menu.addAction("Exit").triggered.connect(QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _send_udp(self, msg: str):
        self.udp_sock.writeDatagram(msg.encode('utf-8'), QHostAddress.SpecialAddress.LocalHost, 9887)

    def _wake(self):
        self._send_udp("wake up")
        self._set_activity()
        self.orb.set_state("WAKE")

    def _open_dashboard(self):
        bridge_path = os.path.join(os.path.dirname(__file__), "web_ui_bridge.py")
        dashboard_url = "http://localhost:7860/web_ui.html"
        def _start():
            try:
                import socket
                s = socket.create_connection(("127.0.0.1", 8765), timeout=0.5)
                s.close(); webbrowser.open(dashboard_url)
            except Exception:
                subprocess.Popen([sys.executable, bridge_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.5); webbrowser.open(dashboard_url)
        threading.Thread(target=_start, daemon=True).start()
        self.panel.btn_dash.setText("⏳ LOADING...")
        QTimer.singleShot(2500, lambda: self.panel.btn_dash.setText("🌐 DASHBOARD"))

    def _send_spotlight(self):
        txt = self.panel.spotlight.text()
        if txt:
            self._send_udp(f"DEEP_SEARCH:{txt[1:].strip()}" if txt.startswith("?") else txt)
            self.panel.spotlight.clear()
            self.orb.set_state("PROCESSING")
            self._set_activity()

    def _refresh_provider_badge(self):
        self.panel.refresh_provider_badge()
        self.panel.status_label.setText("STATUS: PROVIDER REFRESHED")
        QTimer.singleShot(1500, lambda: self.panel.status_label.setText(f"STATUS: {self.orb.state}"))

    def _apply_quick_switch(self):
        prov = self.panel.quick_provider_combo.currentText().strip().lower()
        model = self.panel.quick_model_combo.currentText().strip()
        # Active provider
        if prov:
            active_val = prov if prov != "auto (fallback chain)" else "auto"
            if active_val.startswith("auto"): active_val = "auto"
            self._send_udp(f"SET_ACTIVE_PROVIDER:{active_val}")
        # Model for that provider
        if prov and prov != "auto" and model and model != "auto":
            self._send_udp(f"SET_MODEL:{prov}:{model}")
        self._send_udp("RELOAD_BRAIN")
        self.panel.status_label.setText(f"SWITCHING → {prov}:{model}")
        QTimer.singleShot(1200, self._refresh_provider_badge)

    def _open_keys_dialog(self):
        dlg = ApiKeysDialog(self)
        dlg.exec()
        # Refresh status after dialog closes
        self.panel.refresh_provider_badge()
        self.panel.status_label.setText("STATUS: KEYS UPDATED")

    def _set_volume(self, val): 
        self._send_udp(f"SET_VOLUME:{val}")
        if val == 0: self.panel.btn_mute.setText("🔊 UNMUTE")
        else: self.panel.btn_mute.setText("🔇 MUTE")

    def _set_brightness(self, val): self._send_udp(f"SET_BRIGHTNESS:{val}")

    def _change_mode(self, mode):
        self.orb.mode = mode.lower()
        cfg = FlexieConfig.MODES.get(self.orb.mode, FlexieConfig.MODES["jarvis"])
        accent = cfg["accent"]
        self.panel.status_indicator.setStyleSheet(f"background-color: {accent}; border-radius: 6px;")
        self.panel.status_label.setText(f"SWITCHING TO {mode.upper()}")
        self._send_udp(f"mode:{mode}")
        self.orb.set_state(self.orb.state)

    def _process_udp(self):
        while self.udp_sock.hasPendingDatagrams():
            data, _, _ = self.udp_sock.readDatagram(1024)
            if not data: continue
            msg = data.decode('utf-8')
            if ":" in msg:
                tag, val = msg.split(":", 1)
                if tag == "STATE":
                    self.orb.set_state(val)
                    self.panel.status_label.setText(f"STATUS: {val.upper()}")
                    _sc = EnhancedFlexieOrb.STATE_COLORS
                    _acc, _ = _sc.get(val.upper(), _sc.get("IDLE", ("#00D2FF", "")))
                    accent = _acc
                    self.panel.status_indicator.setStyleSheet(f"background-color: {accent}; border-radius: 6px;")
                elif tag == "MODE":
                    self.orb.mode = val
                    self.panel.mode_combo.setCurrentText(val.capitalize())
                elif tag == "QUIT":
                    QApplication.quit()
                elif tag == "SAY":
                    # Use setMarkdown for proper code block and formatting support
                    self.panel.result_area.setMarkdown(val)
                    self.panel.result_area.show()
                    # Pulse the orb to indicate info received
                    self.orb.set_state("SPEAKING")
                    
                    # Force UI REFLOW (CRITICAL FOR MINIMAL MODE)
                    QTimer.singleShot(50, lambda: self._reflow_ui()) 
                    
                    self._set_activity()
                    QTimer.singleShot(2000, lambda: self.orb.set_state("IDLE"))

    def _reflow_ui(self):
        """Forces the glass container to recalculate its dimensions based on content."""
        if not self.panel: return
        
        # 1. Adjust the result area to its document content (adaptive width AND height)
        if self.panel.result_area.isVisible():
            doc = self.panel.result_area.document()
            # Calculate required height and ideal width
            doc.setTextWidth(550) # Max internal text width
            ideal_w = int(doc.idealWidth()) + 50
            h = int(doc.size().height()) + 30
            
            self.panel.result_area.setFixedHeight(min(500, max(50, h)))
            self.panel.result_area.setMinimumWidth(min(600, max(300, ideal_w)))
        else:
            self.panel.result_area.setFixedHeight(0)

        # 2. Reflow standard widgets
        self.panel.container.adjustSize()
        hint = self.panel.container.sizeHint()
        
        # 3. Smooth resize the panel horizontally and vertically
        self.panel.setFixedHeight(hint.height() + 25)
        self.panel.setFixedWidth(max(340, hint.width() + 20))

    def _update_stats(self):
        if self.panel.isVisible():
            try:
                cpu = psutil.cpu_percent()
                ram = psutil.virtual_memory().percent
                batt = psutil.sensors_battery().percent if psutil.sensors_battery() else 100
                
                self.panel.cpu_value.setText(f"{cpu}%")
                self.panel.cpu_progress.setValue(int(cpu))
                self.panel.cpu_progress.setStyleSheet(f"QProgressBar::chunk {{ background: {'#FF3B30' if cpu > 80 else '#FFD700' if cpu > 60 else '#00D2FF'}; }}")
                
                self.panel.ram_value.setText(f"{ram}%")
                self.panel.ram_progress.setValue(int(ram))
                self.panel.ram_progress.setStyleSheet(f"QProgressBar::chunk {{ background: {'#FF3B30' if ram > 80 else '#FFD700' if ram > 60 else '#00D2FF'}; }}")
                
                self.panel.batt_value.setText(f"{batt}%")
                self.panel.batt_progress.setValue(int(batt))
                self.panel.batt_progress.setStyleSheet(f"QProgressBar::chunk {{ background: {'#FF3B30' if batt < 20 else '#FFD700' if batt < 50 else '#00FF41'}; }}")
                # Refresh provider badge every ~6s
                if int(time.time()) % 3 == 0:
                    self.panel.refresh_provider_badge()
            except: pass

    def _scan_clipboard(self):
        """Action for the CLIP button."""
        clipboard = QApplication.clipboard()
        text = clipboard.text()
        if text:
            # Show in spotlight for user to see, then trigger
            self.panel.result_area.hide()
            self.panel.result_area.setFixedHeight(0)
            self._reflow_ui()
            self.panel.spotlight.setText(text)
            self._send_spotlight()
        else:
            self.panel.status_label.setText("CLIPBOARD EMPTY")

    def _set_activity(self):
        self._last_activity = time.time()
        if self.orb.state in ["SLEEP", "MINIMIZED"]:
            self.orb.set_state("IDLE")

    def _handle_idle(self):
        idle = time.time() - self._last_activity
        if self.orb.state in ["LISTENING", "PROCESSING", "SPEAKING"]: return
        if idle > 60: self.orb.set_state("MINIMIZED")
        elif idle > 25: self.orb.set_state("SLEEP")

    def mousePressEvent(self, event):
        self._set_activity()
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.pos()
        elif event.button() == Qt.MouseButton.RightButton:
            if self.panel.isVisible(): self.panel.hide_animated()
            else: 
                self.panel.set_minimal_mode(False) # FULL MODE ON ORB CLICK
                self.panel.show_animated(self.pos() + QPoint(290, -100))
                self._reflow_ui()
        event.accept()

    def mouseMoveEvent(self, event):
        self._set_activity()
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_pos)
            if self.panel.isVisible(): self.panel.move(self.pos() + QPoint(290, -100))
        event.accept()

    def enterEvent(self, event):
        self._set_activity()
        super().enterEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QFont("Segoe UI", 9))
    ui = FlexieUI()
    sys.exit(app.exec())