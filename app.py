import sys
import time
import math
import random
from datetime import datetime
from PyQt5.QtCore import Qt, QTimer, QPoint, QRectF, pyqtSignal, QThread
from PyQt5.QtGui import QColor, QPainter, QPen, QBrush, QFont
from omnia_core import get_ai_response, speak
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QLineEdit,
    QFrame,
    QSizePolicy,
    QDialog,
)

try:
    import speech_recognition as sr
except ImportError:
    sr = None


class SpeechRecognizeWorker(QThread):
    text_recognized = pyqtSignal(str)

    def run(self):
        if not sr:
            self.text_recognized.emit(
                "[ERROR] Modul speech_recognition belum terinstal."
            )
            return

        try:
            recognizer = sr.Recognizer()
            with sr.Microphone() as source:
                recognizer.adjust_for_ambient_noise(source, duration=0.3)
                try:
                    audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                    text = recognizer.recognize_google(audio, language="id-ID")
                    self.text_recognized.emit(text)
                except sr.WaitTimeoutError:
                    self.text_recognized.emit("")
                except sr.UnknownValueError:
                    self.text_recognized.emit("[ERROR] Suara tidak dikenali.")
                except Exception as e:
                    self.text_recognized.emit(f"[ERROR] {str(e)}")
        except Exception as e:
            # Menangkap error fatal perangkat mikrofon agar GUI tidak tertutup paksa
            self.text_recognized.emit(f"[ERROR] Mikrofon tidak terdeteksi: {str(e)}")


class ChatPopupDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_window = parent
        self.setWindowTitle("OMNIA // RUANG CHAT LUAS")
        self.resize(780, 580)
        self.setStyleSheet("background-color: #041b2e; color: #a8eaff;")

        layout = QVBoxLayout(self)

        # Area teks chat yang besar
        self.big_chat_display = QTextEdit()
        self.big_chat_display.setReadOnly(True)
        self.big_chat_display.setStyleSheet("""
            background-color: #020b14; 
            color: #a8eaff; 
            border: 1px solid #0875a6; 
            border-radius: 5px; 
            font-size: 13px; 
            padding: 10px;
        """)

        # [PERUBAHAN]: Menarik riwayat teks yang sudah ada di panel utama agar tampil juga saat dialog dibuka
        initial_history = ""
        if self.parent_window and hasattr(self.parent_window, "chat_display"):
            initial_history = self.parent_window.chat_display.toPlainText()

        if initial_history:
            self.big_chat_display.setPlainText(initial_history)
        else:
            self.big_chat_display.setPlainText(
                "OMNIA\nSelamat datang di Ruang Chat Luas. Riwayat percakapan Anda akan tampil lebih leluasa di sini.\n"
            )

        layout.addWidget(self.big_chat_display, 1)

        # Baris input teks & tombol kirim
        input_layout = QHBoxLayout()
        self.big_input_field = QLineEdit()
        self.big_input_field.setPlaceholderText("Ketik pesan di sini...")
        self.big_input_field.setStyleSheet("""
            background-color: #020b14; 
            color: #a8eaff; 
            border: 1px solid #0875a6; 
            border-radius: 5px; 
            padding: 8px;
        """)

        self.big_input_field.returnPressed.connect(self.send_message)

        self.big_btn_send = QPushButton("KIRIM")
        self.big_btn_send.setStyleSheet("""
            background-color: #0875a6; 
            color: #ffffff; 
            border-radius: 5px; 
            font-weight: bold; 
            padding: 8px 15px;
        """)
        self.big_btn_send.clicked.connect(self.send_message)

        input_layout.addWidget(self.big_input_field, 1)
        input_layout.addWidget(self.big_btn_send)
        layout.addLayout(input_layout)

    def send_message(self):
        text = self.big_input_field.text().strip()
        if not text:
            return

        # Tampilkan pesan user ke layar chat luas
        self.big_chat_display.append(f"\nUSER > {text}")

        # Sinkronisasi pesan user ke kolom conversation utama
        if self.parent_window and hasattr(self.parent_window, "chat_display"):
            self.parent_window.chat_display.append(f"USER > {text}")

        self.big_input_field.clear()

        try:
            response_text = get_ai_response(text)
            self.big_chat_display.append(f"OMNIA > {response_text}\n")

            try:
                from omnia_core import speak

                QTimer.singleShot(100, lambda: speak(response_text))
            except Exception:
                pass

            # Sinkronisasi respons AI ke kolom conversation utama
            if self.parent_window and hasattr(self.parent_window, "chat_display"):
                self.parent_window.chat_display.append(f"OMNIA > {response_text}\n")

        except Exception as e:
            err_msg = f"[SYSTEM ERROR] Gagal memanggil core: {str(e)}\n"
            self.big_chat_display.append(err_msg)

            if self.parent_window and hasattr(self.parent_window, "chat_display"):
                self.parent_window.chat_display.append(err_msg)

        # Otomatis gulir ke bawah (auto-scroll) ke pesan terbaru
        self.big_chat_display.verticalScrollBar().setValue(
            self.big_chat_display.verticalScrollBar().maximum()
        )

    # [PERUBAHAN UTAMA]: Fungsi bantu untuk menerima kiriman teks dari jendela utama (Conversation)
    def append_external_message(self, message):
        self.big_chat_display.append(message)
        # Auto-scroll agar selalu melihat pesan terbaru
        self.big_chat_display.verticalScrollBar().setValue(
            self.big_chat_display.verticalScrollBar().maximum()
        )


# ============================================================
# OMNIA CORE WORKER (Menghubungkan GUI dengan OmniaAutonomousCognitiveCore)
# ============================================================
class GroqWorker(QThread):
    finished = pyqtSignal(str)

    def __init__(self, query, parent=None):
        super().__init__(parent)
        self.query = query

    def run(self):
        try:
            # Mengimpor inti pusat dan fungsi pemformatan dari omnia_core.py yang baru
            from omnia_core import (
                OmniaAutonomousCognitiveCore,
                format_response_to_plain_text,
                speak,
            )
            from datetime import datetime

            # Menginisialisasi kelas inti Omnia Core yang sudah mencakup 8 modul otonom
            core = OmniaAutonomousCognitiveCore()
            client = core.client  # Menggunakan client OpenAI/Groq dari core

            extra_context = f"\n[CURRENT SYSTEM TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}]\n"

            correction_keywords = [
                "salah",
                "yang benar",
                "ingat ini",
                "ralat",
                "seharusnya",
            ]
            if any(kw in self.query.lower() for kw in correction_keywords):
                if hasattr(core, "record_omnia_learning"):
                    core.record_omnia_learning(
                        topic="User Correction",
                        original_response="Koreksi langsung",
                        correction_note=self.query,
                    )
                extra_context += "\n[SYSTEM NOTE: Pengguna memberikan koreksi baru yang telah dicatat ke memori pembelajaran permanen.]\n"

            casual_greetings = [
                "halo",
                "hi",
                "hai",
                "selamat pagi",
                "selamat siang",
                "pagi",
                "terima kasih",
                "thanks",
            ]
            is_casual = (
                self.query.lower().strip() in casual_greetings
                or len(self.query.split()) <= 2
            )

            factual_indicators = [
                "apa",
                "siapa",
                "dimana",
                "kapan",
                "mengapa",
                "bagaimana",
                "berapa",
                "cari",
                "cek",
                "info",
                "data",
                "update",
                "terbaru",
                "harga",
                "nilai",
                "jadwal",
            ]
            if not is_casual and any(
                ind in self.query.lower() for ind in factual_indicators
            ):
                if hasattr(core, "search_web"):
                    search_results = core.search_web(self.query)
                    extra_context += f"\n[LIVE WEB SEARCH RESULTS]:\n{search_results}\n"

            long_term_summary = core.memory.get("long_term_summary")
            if long_term_summary:
                extra_context += (
                    f"\n[LONG-TERM MEMORY & PREFERENCES]:\n{long_term_summary}\n"
                )

            custom_corrections = core.memory.get("custom_corrections")
            if custom_corrections:
                recent_corrections = "\n".join(
                    [f"- {c['correction']}" for c in custom_corrections[-3:]]
                )
                extra_context += (
                    f"\n[LEARNED CORRECTIONS FROM USER]:\n{recent_corrections}\n"
                )

            if any(k in self.query.lower() for k in ["ide", "inovasi", "solusi"]):
                if hasattr(core, "innovation_engine"):
                    generated_idea = core.innovation_engine(self.query)
                    extra_context += f"\nINNOVATION ENGINE INSIGHT: {generated_idea}\n"

            if hasattr(core, "learner") and hasattr(
                core.learner, "get_learned_context"
            ):
                learned_history = core.learner.get_learned_context()
                if learned_history:
                    extra_context += f"\n{learned_history}\n"

            chat_history = core.memory.get("chat_history") or []
            messages = [
                {
                    "role": "system",
                    "content": (
                        "Anda adalah asisten AI otonom yang akurat, faktual, dan responsif. "
                        "Gunakan memori jangka panjang, catatan koreksi pengguna, dan hasil pencarian web LIVE WEB SEARCH RESULTS jika tersedia untuk memberikan jawaban terbaik. "
                        "Gunakan waktu sistem saat ini untuk konteks temporal jika diperlukan. "
                        "DILARANG menggunakan simbol dekoratif seperti asteris (*), pagar (#), garis bawah, atau tabel markdown. "
                        "Gunakan teks polos sepenuhnya dengan format rata kiri."
                    )
                    + extra_context,
                }
            ]

            for h in chat_history[-6:]:
                messages.append({"role": h["role"], "content": h["content"]})

            messages.append({"role": "user", "content": self.query})

            completion = client.chat.completions.create(
                model="openai/gpt-oss-20b",
                messages=messages,
                temperature=0.3,
                max_tokens=600,
                top_p=1,
                stream=False,
            )

            raw_response = completion.choices[0].message.content
            formatted_response = format_response_to_plain_text(raw_response)

            chat_history.append({"role": "user", "content": self.query})
            chat_history.append({"role": "assistant", "content": formatted_response})
            core.memory.set("chat_history", chat_history)

            if hasattr(core, "update_long_term_summary"):
                core.update_long_term_summary(client)

            speak(formatted_response)

            self.finished.emit(formatted_response)
        except Exception as e:
            self.finished.emit(f"Kesalahan Koneksi Kernel Groq: {str(e)}")


# ============================================================
# AUDIO WAVEFORM WIDGET
# ============================================================
class AudioWaveformWidget(QWidget):
    def __init__(self, height=30, parent=None):
        super().__init__(parent)
        self.setFixedHeight(height)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update)
        self.timer.start(80)
        self.bars = [random.randint(4, 24) for _ in range(24)]

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()
        bar_width = max(2, width // len(self.bars) - 3)

        for i, h in enumerate(self.bars):
            self.bars[i] = max(3, min(height - 4, h + random.randint(-3, 3)))
            x = i * (bar_width + 3) + 4
            y = (height - self.bars[i]) // 2
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(0, 217, 255, 180)))
            painter.drawRoundedRect(x, y, bar_width, self.bars[i], 2, 2)


# ============================================================
# REACTOR WIDGET (ARC REACTOR HUD ANIMATION)
# ============================================================
class ReactorWidget(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.rotate_reactor)
        self.timer.start(30)
        self.setMinimumSize(160, 160)

    def rotate_reactor(self):
        self.angle = (self.angle + 2) % 360
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        width = self.width()
        height = self.height()
        cx, cy = width / 2, height / 2
        radius = min(cx, cy) - 15

        painter.setPen(QPen(QColor(0, 150, 200, 100), 1, Qt.DashLine))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))

        painter.save()
        painter.translate(cx, cy)
        painter.rotate(self.angle)
        painter.setPen(QPen(QColor(0, 220, 255, 200), 2))
        for i in range(4):
            painter.drawArc(
                QRectF(-radius * 0.75, -radius * 0.75, radius * 1.5, radius * 1.5),
                i * 90 * 16,
                45 * 16,
            )
        painter.restore()

        painter.setPen(QPen(QColor(0, 255, 200, 150), 1.5))
        painter.drawEllipse(
            QRectF(cx - radius * 0.5, cy - radius * 0.5, radius, radius)
        )

        font = QFont("Arial", max(18, int(radius * 0.16)), QFont.Bold)
        painter.setFont(font)
        painter.setPen(QColor(255, 255, 255))
        painter.drawText(
            int(cx - radius * 0.8),
            int(cy - radius * 0.22),
            int(radius * 1.6),
            int(radius * 0.35),
            Qt.AlignCenter,
            "OMNIA",
        )

        font2 = QFont("Arial", max(8, int(radius * 0.07)), QFont.Bold)
        painter.setFont(font2)
        painter.setPen(QColor(0, 230, 255))
        painter.drawText(
            int(cx - radius * 0.8),
            int(cy + radius * 0.05),
            int(radius * 1.6),
            int(radius * 0.3),
            Qt.AlignCenter,
            "AI ASSISTANT",
        )


# ============================================================
# MICROPHONE BUTTON
# ============================================================
class MicButton(QPushButton):
    def __init__(self, parent=None):
        super().__init__("●", parent)
        self.listening = False
        self.setObjectName("micButton")
        self.setToolTip("Aktifkan / nonaktifkan mikrofon")
        self.clicked.connect(self.toggle_listening)

    def toggle_listening(self):
        self.listening = not self.listening
        self.setProperty("listening", str(self.listening).lower())
        self.style().unpolish(self)
        self.style().polish(self)
        self.setText("◉" if self.listening else "●")
        if hasattr(self.window(), "set_voice_state"):
            self.window().set_voice_state(self.listening)


# ============================================================
# MAIN OMNIA GUI
# ============================================================
class OmniaGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.full_response_text = ""
        self.current_char_index = 0
        self.old_pos = QPoint()
        self.voice_active = False

        self.initUI()
        self.initTimers()

    def initUI(self):
        self.setWindowTitle("OMNIA // JARVIS NEURAL HUD")
        self.setGeometry(100, 80, 1100, 650)
        self.setMinimumSize(900, 580)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #020811;
                color: #bceeff;
                font-family: "Segoe UI", "Consolas";
            }
            QFrame#panel {
                background: rgba(3, 13, 25, 245);
                border: 1px solid #07547a;
                border-radius: 7px;
            }
            QLabel {
                color: #bdefff;
            }
            QPushButton {
                background: rgba(4, 27, 45, 220);
                color: #a8eaff;
                border: 1px solid #0875a6;
                border-radius: 5px;
                padding: 7px 10px;
                font-size: 11px;
                font-weight: 700;                
            }
            QPushButton:hover {
                background: rgba(0, 112, 168, 150);
                border: 1px solid #26dfff;
                color: white;
            }
            QPushButton:pressed {
                background: rgba(0, 170, 220, 170);
            }
            QPushButton.action {
                text-align: left;
                padding-left: 8px;
                padding-right: 4px;
                min-height: 30px;
                font-size: 8.5px;
            }
            QPushButton.tab {
                min-height: 31px;
                border-color: #0a4562;
                background: #031421;
                font-size: 10px;
                padding: 5px 3px;
            }

            }
            QPushButton.tab:checked {
                background: #063957;
                border: 1px solid #00d9ff;
                color: #ffffff;
            }
            QPushButton.shortcut {
                min-height: 42px;
                font-size: 10px;
            }
            QPushButton#micButton {
                min-width: 72px;
                min-height: 34px;
                max-width: 72px;
                max-height: 34px;
                border-radius: 5px;
                border: 1px solid #0875a6;
                background: rgba(4, 27, 45, 220);
                color: #a8eaff;
                font-size: 11px;
                font-weight: 700;
            }
            QPushButton#micButton[listening="true"] {
                border: 3px solid #a55cff;
                background: #201044;
                color: white;
            }
            QLineEdit {
                background: #010b15;
                color: #bceeff;
                border: 1px solid #0879a9;
                border-radius: 6px;
                padding: 10px 13px;
                font-size: 13px;
                selection-background-color: #075d86;
            }
            QTextEdit {
                background: #010a13;
                color: #9de9ff;
                border: 1px solid #064b6a;
                border-radius: 5px;
                padding: 8px;
                font-size: 12px;
            }
        """)

        root = QWidget()
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(14, 10, 14, 10)
        main.setSpacing(8)

        # TOP BAR
        top = QHBoxLayout()
        top.setSpacing(12)

        logo = QLabel("◉  OMNIA")
        logo.setStyleSheet(
            "color: #19cfff; font-size: 29px; font-weight: 900; letter-spacing: 2px;"
        )
        top.addWidget(logo)

        version = QLabel("OMNIA v1.0.0\nSYSTEM ONLINE  ●")
        version.setStyleSheet("color: #00e0ff; font-size: 10px; font-weight: 700;")
        top.addWidget(version)

        top.addStretch()

        self.date_label = QLabel()
        self.date_label.setAlignment(Qt.AlignCenter)
        self.date_label.setStyleSheet(
            "color: #8ceaff; font-size: 11px; font-weight: 700;"
        )
        top.addWidget(self.date_label)

        self.clock_label = QLabel("00:00:00")
        self.clock_label.setStyleSheet(
            "color: #1bcfff; font-size: 27px; font-weight: 900;"
        )
        top.addWidget(self.clock_label)

        stats = QLabel("CPU  23%     RAM  42%     NETWORK  112.4 Mbps")
        stats.setStyleSheet("color: #75ddff; font-size: 10px; font-weight: 700;")
        top.addWidget(stats)

        user = QLabel("USER\nOMNIA OPERATOR\n● ADMIN MODE")
        user.setStyleSheet("color: #6ce7ff; font-size: 9px; font-weight: 700;")
        top.addWidget(user)

        self.btn_min = QPushButton("—")
        self.btn_min.setFixedSize(31, 27)
        self.btn_min.clicked.connect(self.showMinimized)
        top.addWidget(self.btn_min)

        self.btn_close = QPushButton("×")
        self.btn_close.setFixedSize(31, 27)
        self.btn_close.clicked.connect(self.close)
        top.addWidget(self.btn_close)

        main.addLayout(top)

        # BODY (3 COLUMNS)
        body = QHBoxLayout()
        body.setSpacing(9)
        main.addLayout(body, 1)

        # LEFT COLUMN
        left = QVBoxLayout()
        left.setSpacing(8)
        body.addLayout(left, 1)

        self.left_system = self.panel("SYSTEM STATUS")
        ls = QVBoxLayout(self.left_system)
        self.add_panel_header(ls, "SYSTEM STATUS")
        self.cpu_lbl = self.add_metric_row(ls, "CPU USAGE", "23%")
        self.ram_lbl = self.add_metric_row(ls, "RAM USAGE", "42%")
        self.disk_lbl = self.add_metric_row(ls, "DISK USAGE", "58%")
        self.net_lbl = self.add_metric_row(ls, "NETWORK", "112.4 Mbps")
        self.uptime_lbl = self.add_metric_row(ls, "UPTIME", "02h 47m 33s")
        left.addWidget(self.left_system, 2)

        capabilities_panel = self.panel("CAPABILITIES")
        cl = QVBoxLayout(capabilities_panel)
        self.add_panel_header(cl, "CAPABILITIES")
        capabilities = [
            "◈  AI INTELLIGENCE",
            "◎  WEB RESEARCH",
            "♬  VOICE SYSTEM",
            "⌘  AUTOMATION",
            "▣  MEMORY SYSTEM",
            "□  FILE MANAGER",
            "◉  CODE EXECUTOR",
            "⚙  SYSTEM CONTROL",
        ]
        for item in capabilities:
            row = QHBoxLayout()
            label = QLabel(item)
            label.setStyleSheet("color: #8bdfff; font-size: 10px; font-weight: 700;")
            active = QLabel("ACTIVE")
            active.setStyleSheet("color: #00f59d; font-size: 9px; font-weight: 900;")
            row.addWidget(label)
            row.addStretch()
            row.addWidget(active)
            cl.addLayout(row)
        left.addWidget(capabilities_panel, 2)

        quick = self.panel("QUICK ACTIONS")
        ql = QGridLayout(quick)
        self.add_panel_header(ql, "QUICK ACTIONS", 0, 0, 1, 2)
        quick_buttons = [
            ("CLEAR CHAT", self.clear_chat),
            ("SAVE MEMORY", lambda: self.log_system_action("Memory tersimpan.")),
            ("TAKE NOTE", lambda: self.log_system_action("Mode catatan aktif.")),
            ("OPEN FILES", lambda: self.log_system_action("File Manager dibuka.")),
            ("SCREENSHOT", lambda: self.log_system_action("Snapshot HUD dibuat.")),
            ("MINI MODE", lambda: self.showMinimized()),
        ]
        for i, (text, fn) in enumerate(quick_buttons):
            button = QPushButton(text)
            button.setObjectName("shortcut")
            button.clicked.connect(fn)
            ql.addWidget(button, 1 + i // 2, i % 2)
        left.addWidget(quick, 2)

        # CENTER COLUMN
        center = QVBoxLayout()
        center.setSpacing(8)
        body.addLayout(center, 3)

        reactor_frame = self.panel("CORE")
        rf = QVBoxLayout(reactor_frame)
        rf.setContentsMargins(6, 5, 6, 5)

        core_top = QHBoxLayout()
        core_top.addWidget(
            self.action_button("◌  AI CHAT", lambda: self.input_field.setFocus())
        )
        core_top.addWidget(
            self.action_button(
                "◎  WEB SEARCH", lambda: self.log_system_action("Web Research siap.")
            )
        )
        core_top.addWidget(self.action_button("♬  VOICE MODE", self.toggle_mic))
        core_top.addStretch()
        core_top.addWidget(
            self.action_button(
                "⚙  AUTOMATION", lambda: self.log_system_action("Automation siap.")
            )
        )
        core_top.addWidget(
            self.action_button(
                "□  FILE MANAGER", lambda: self.log_system_action("File Manager siap.")
            )
        )
        rf.addLayout(core_top)

        reactor_row = QHBoxLayout()
        left_actions = QVBoxLayout()
        for text in ["◉  VOICE MODE", "◎  MEMORY", "⌁  SYSTEM INFO"]:
            left_actions.addWidget(
                self.action_button(
                    text, lambda _, t=text: self.log_system_action(t + " dipilih.")
                )
            )
        left_actions.addStretch()

        right_actions = QVBoxLayout()
        for text in ["⚙  AUTOMATION", "□  FILE MANAGER", "☷  SETTINGS"]:
            right_actions.addWidget(
                self.action_button(
                    text, lambda _, t=text: self.log_system_action(t + " dipilih.")
                )
            )
        right_actions.addStretch()

        reactor_row.addLayout(left_actions, 1)
        reactor_container = QVBoxLayout()
        reactor_container.addStretch(15)
        self.reactor = ReactorWidget()
        reactor_container.addWidget(self.reactor, alignment=Qt.AlignCenter)
        reactor_container.addStretch(1)
        reactor_row.addLayout(reactor_container, 4)
        reactor_row.addLayout(right_actions, 1)
        rf.addLayout(reactor_row, 1)

        ready = QLabel("  ●  SYSTEM READY  ")
        ready.setAlignment(Qt.AlignCenter)
        ready.setStyleSheet(
            "color: #00ffae; background: #03251e; border: 1px solid #00c993; border-radius: 8px; padding: 8px; font-size: 12px; font-weight: 900;"
        )
        rf.addWidget(ready)
        center.addWidget(reactor_frame, 4)

        tabs = QHBoxLayout()
        tab_names = [
            "CHAT",
            "AJARI OMNIA",
            "CODE",
            "SEARCH",
            "AUTOMATION",
            "MEMORY",
            "TERMINAL",
        ]
        for i, text in enumerate(tab_names):
            button = QPushButton(text)
            button.setProperty("class", "tab")
            button.setCheckable(True)
            if i == 0:
                button.setChecked(True)

            if text == "CHAT":
                button.clicked.connect(self.show_chat_popup)
            elif text == "AJARI OMNIA":
                button.clicked.connect(self.show_chat_popup)
            else:
                button.clicked.connect(
                    lambda _, t=text: self.log_system_action(f"Panel {t} aktif.")
                )

            tabs.addWidget(button)
        center.addLayout(tabs)

        conversation = self.panel("CONVERSATION")
        cv = QVBoxLayout(conversation)
        self.add_panel_header(cv, "CONVERSATION")

        self.chat_display = QTextEdit()
        self.chat_display.setReadOnly(True)
        self.chat_display.setPlainText(
            "OMNIA\nHalo. Saya OMNIA, AI assistant Anda.\nSaya siap membantu Anda hari ini.\n"
        )
        cv.addWidget(self.chat_display, 1)

        input_row = QHBoxLayout()
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Ketik perintah Anda di sini...")
        self.input_field.returnPressed.connect(self.handle_user_input)

        self.btn_send = QPushButton("➤")
        self.btn_send.setFixedSize(54, 43)
        self.btn_send.clicked.connect(self.handle_user_input)

        input_row.addWidget(self.input_field, 1)
        input_row.addWidget(self.btn_send)
        cv.addLayout(input_row)
        center.addWidget(conversation, 3)

        voice_row = QHBoxLayout()
        for label_text in ["LISTEN", "THINK", "SPEAK"]:
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #5fdfff; font-size: 10px; font-weight: 800;")
            voice_row.addWidget(lbl)
        voice_row.addStretch()

        mic_container = QVBoxLayout()
        mic_container.addStretch(10)  # Angka dorongan dari atas
        self.mic_button = MicButton()
        mic_container.addWidget(self.mic_button, alignment=Qt.AlignCenter)
        mic_container.addStretch(1)
        voice_row.addLayout(mic_container)

        voice_controls = [
            ("STOP", lambda: self.log_system_action("Voice output dihentikan.")),
            ("PAUSE", lambda: self.log_system_action("Voice output dijeda.")),
            ("CLEAR", self.clear_chat),
        ]
        for text, fn in voice_controls:
            button = QPushButton(text)
            button.setFixedWidth(72)
            button.clicked.connect(fn)
            voice_row.addWidget(button)
        center.addLayout(voice_row)

        # RIGHT COLUMN
        right = QVBoxLayout()
        right.setSpacing(8)
        body.addLayout(right, 1)

        intelligence = self.panel("INTELLIGENCE")
        il = QVBoxLayout(intelligence)
        self.add_panel_header(il, "INTELLIGENCE")

        brain = QLabel(
            "╭────────────╮\n│   ◉ ◉ ◉    │\n│  NEURAL AI  │\n│    CORE    │\n╰────────────╯"
        )
        brain.setAlignment(Qt.AlignCenter)
        brain.setStyleSheet("color: #1ad7ff; font-size: 16px; font-weight: 900;")
        il.addWidget(brain)

        intelligence_data = [
            ("AI MODEL", "gpt-oss-20b"),
            ("PROVIDER", "Groq Cloud API"),
            ("STATUS", "CONNECTED"),
        ]
        for key, value in intelligence_data:
            row = QHBoxLayout()
            label = QLabel(key)
            label.setStyleSheet("color: #00bce8; font-size: 10px; font-weight: 800;")
            value_label = QLabel(value)
            value_label.setStyleSheet(
                "color: #b9efff; font-size: 10px; font-weight: 800;"
                if key != "STATUS"
                else "color: #00ff9d; font-size: 10px; font-weight: 900;"
            )
            row.addWidget(label)
            row.addStretch()
            row.addWidget(value_label)
            il.addLayout(row)
        right.addWidget(intelligence, 2)

        activity = self.panel("RECENT ACTIVITY")
        al = QVBoxLayout(activity)
        self.add_panel_header(al, "RECENT ACTIVITY")
        self.activity_label = QLabel(
            "09:22:31   Web Search\n"
            "09:21:15   File Access\n"
            "09:19:42   AI Conversation\n"
            "09:18:03   System Check\n"
            "09:16:55   Memory Save"
        )
        self.activity_label.setStyleSheet("color: #75cce8; font-size: 9px;")
        al.addWidget(self.activity_label)
        right.addWidget(activity, 2)

        voice = self.panel("VOICE STATUS")
        vl = QVBoxLayout(voice)
        self.add_panel_header(vl, "VOICE STATUS")
        voice_waveform = AudioWaveformWidget(height=25)
        vl.addWidget(voice_waveform)

        self.voice_status = QLabel("PIPER TTS                            READY")
        self.voice_status.setStyleSheet(
            "color: #00eaff; font-size: 10px; font-weight: 800;"
        )
        vl.addWidget(self.voice_status)
        right.addWidget(voice, 1)

        shortcuts = self.panel("SHORTCUTS")
        sl = QGridLayout(shortcuts)
        self.add_panel_header(sl, "SHORTCUTS", 0, 0, 1, 3)
        shortcut_names = [
            "YOUTUBE",
            "WIKIPEDIA",
            "GITHUB",
            "GOOGLE",
            "WEATHER",
            "CALENDAR",
        ]
        for i, text in enumerate(shortcut_names):
            button = QPushButton(text)
            button.setObjectName("shortcut")
            button.clicked.connect(
                lambda _, t=text: self.log_system_action(f"Shortcut {t} dipilih.")
            )
            sl.addWidget(button, 1 + i // 3, i % 3)
        right.addWidget(shortcuts, 2)

        # FOOTER
        footer = QHBoxLayout()
        footer_text = QLabel(
            "◉  OMNIA HUD INTERFACE   //   FUTURISTIC AI ASSISTANT SYSTEM"
        )
        footer_text.setStyleSheet("color: #229ec4; font-size: 9px; font-weight: 700;")
        footer.addWidget(footer_text)
        footer.addStretch()

        self.footer_voice = QLabel("VOICE: STANDBY")
        self.footer_voice.setStyleSheet(
            "color: #00ffad; font-size: 10px; font-weight: 900;"
        )
        footer.addWidget(self.footer_voice)
        footer.addSpacing(20)

        secure = QLabel("🔒 SECURE CONNECTION")
        secure.setStyleSheet("color: #00ffad; font-size: 9px; font-weight: 800;")
        footer.addWidget(secure)
        main.addLayout(footer)

    def panel(self, name):
        frame = QFrame()
        frame.setObjectName("panel")
        frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return frame

    def add_panel_header(self, layout, title, *grid_args):
        label = QLabel(title)
        label.setProperty("class", "sectionTitle")
        label.setStyleSheet(
            "color: #8feaff; font-size: 13px; font-weight: 800; letter-spacing: 1px; padding-bottom: 5px;"
        )
        if grid_args:
            layout.addWidget(label, *grid_args)
        else:
            layout.addWidget(label)

    def add_metric_row(self, layout, title, value):
        row = QHBoxLayout()
        label = QLabel(title)
        label.setStyleSheet("color: #3fbfe8; font-size: 9px; font-weight: 800;")
        value_label = QLabel(value)
        value_label.setStyleSheet("color: #b9efff; font-size: 10px; font-weight: 800;")
        row.addWidget(label)
        row.addStretch()
        row.addWidget(value_label)
        layout.addLayout(row)
        return value_label

    def action_button(self, text, fn):
        button = QPushButton(text)
        button.setObjectName("action")
        button.setMinimumHeight(38)
        # Langsung pasang style di sini agar pasti berubah dan tidak terpotong
        button.setStyleSheet("font-size: 8px; padding-left: 10px; padding-right: 4px;")
        button.clicked.connect(fn)
        return button

    def initTimers(self):
        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)

        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self.randomize_telemetry)
        self.telemetry_timer.start(2500)

        self.typewriter_timer = QTimer(self)
        self.typewriter_timer.timeout.connect(self.typewriter_step)
        self.typewriter_timer.start(12)

        self.update_clock()

    def show_chat_popup(self):
        if not hasattr(self, "chat_popup_window") or self.chat_popup_window is None:
            self.chat_popup_window = ChatPopupDialog(self)
        self.chat_popup_window.show()
        self.chat_popup_window.raise_()
        self.chat_popup_window.activateWindow()

    def update_clock(self):
        now = time.localtime()
        self.clock_label.setText(time.strftime("%H:%M:%S", now))
        self.date_label.setText(
            time.strftime("%d %B %Y", now).upper()
            + "\n"
            + time.strftime("%A", now).upper()
        )

    def randomize_telemetry(self):
        cpu = random.randint(17, 38)
        ram = random.randint(38, 67)
        disk = random.randint(51, 72)
        net = random.uniform(80, 140)
        self.cpu_lbl.setText(f"{cpu}%")
        self.ram_lbl.setText(f"{ram}%")
        self.disk_lbl.setText(f"{disk}%")
        self.net_lbl.setText(f"{net:.1f} Mbps")

    def set_voice_state(self, active):
        self.voice_active = active
        if active:
            self.voice_status.setText("PIPER TTS                            LISTENING")
            self.voice_status.setStyleSheet(
                "color: #c36bff; font-size: 10px; font-weight: 900;"
            )
            self.footer_voice.setText("VOICE: LISTENING")
            self.log_system_action("Mikrofon aktif.")
        else:
            self.voice_status.setText("PIPER TTS                            READY")
            self.voice_status.setStyleSheet(
                "color: #00eaff; font-size: 10px; font-weight: 800;"
            )
            self.footer_voice.setText("VOICE: STANDBY")
            self.log_system_action("Mikrofon standby.")

    def toggle_mic(self):
        self.mic_button.toggle_listening()

    def clear_chat(self):
        self.chat_display.clear()
        self.log_system_action("Conversation buffer dibersihkan.")

    def log_system_action(self, text):
        self.chat_display.append(f"[OMNIA SYSTEM] {text}")

    def handle_user_input(self):
        query = self.input_field.text().strip()
        if not query:
            return
        self.chat_display.append(f"USER > {query}")
        self.input_field.clear()
        self.status_processing(True)

        # Menjalankan Core di background thread agar UI tidak freeze/lag
        self.worker = GroqWorker(query)
        self.worker.finished.connect(self.on_groq_response)
        self.worker.start()

    def status_processing(self, active):
        if active:
            self.footer_voice.setText("CORE: PROCESSING")
        else:
            self.footer_voice.setText("CORE: READY")

    def on_groq_response(self, response_text):
        self.status_processing(False)
        self.full_response_text = f"OMNIA > {response_text}\n\n"
        self.current_char_index = 0
        self.chat_display.append("OMNIA > ")

    def typewriter_step(self):
        if self.current_char_index >= len(self.full_response_text):
            return
        cursor = self.chat_display.textCursor()
        cursor.movePosition(cursor.End)
        cursor.insertText(self.full_response_text[self.current_char_index])
        self.chat_display.setTextCursor(cursor)
        self.current_char_index += 1
        self.chat_display.verticalScrollBar().setValue(
            self.chat_display.verticalScrollBar().maximum()
        )

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.old_pos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.old_pos and event.buttons() == Qt.LeftButton:
            delta = event.globalPos() - self.old_pos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.old_pos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.old_pos = QPoint()

    def set_voice_state(self, active):
        self.voice_active = active
        if self.voice_active:
            if hasattr(self, "status_label") and self.status_label:
                self.status_label.setText("STATUS: MENDENGARKAN...")

            # Simpan referensi thread ke variabel self agar tidak hancur prematur
            self.speech_thread = SpeechRecognizeWorker()
            self.speech_thread.text_recognized.connect(self.on_speech_recognized)
            self.speech_thread.start()
        else:
            if hasattr(self, "status_label") and self.status_label:
                self.status_label.setText("STATUS: SIAP")

            # Hentikan thread dengan aman jika pengguna membatalkan manual
            if hasattr(self, "speech_thread") and self.speech_thread.isRunning():
                self.speech_thread.quit()
                self.speech_thread.wait(500)

    def on_speech_recognized(self, text):
        self.voice_active = False
        if hasattr(self, "mic_btn") and self.mic_btn:
            self.mic_btn.listening = False
            self.mic_btn.setProperty("listening", "false")
            self.mic_btn.style().unpolish(self.mic_btn)
            self.mic_btn.style().polish(self.mic_btn)
            self.mic_btn.setText("●")

        if text and not text.startswith("[ERROR]"):
            if hasattr(self, "input_field") and self.input_field:
                self.input_field.setText(text)
                self.handle_user_input()
        else:
            if hasattr(self, "status_label") and self.status_label:
                if text.startswith("[ERROR]"):
                    self.status_label.setText(text)
                else:
                    self.status_label.setText("STATUS: SIAP")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    gui = OmniaGUI()
    gui.show()
    sys.exit(app.exec_())
