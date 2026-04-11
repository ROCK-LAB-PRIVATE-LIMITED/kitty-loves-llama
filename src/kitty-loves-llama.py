# kitty_loves_llama.py
import sys
import os
import shutil
import json
import webbrowser
import socket
import subprocess
import time
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, 
    QPlainTextEdit, QFileDialog, QGroupBox, QGridLayout, QComboBox, QCheckBox, QMainWindow
)
from PySide6.QtCore import Qt, QProcess, Signal, QUrl, QTimer
from PySide6.QtGui import QIcon

try:
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAS_WEBENGINE = True
except ImportError:
    HAS_WEBENGINE = False

CONFIG_FILE = "kitty_config.json"

class DropArea(QLabel):
    fileDropped = Signal(str)

    def __init__(self, label_text, parent=None):
        super().__init__(label_text, parent)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(70)
        self.setStyleSheet("""
            border: 2px dashed #aaa;
            border-radius: 10px;
            background: #f0f0f0;
            color: #555;
            font-weight: bold;
        """)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.setStyleSheet("border: 2px dashed #3498db; background: #ebf5fb; color: #3498db;")

    def dragLeaveEvent(self, event):
        self.setStyleSheet("border: 2px dashed #aaa; background: #f0f0f0; color: #555;")

    def dropEvent(self, event):
        self.setStyleSheet("border: 2px dashed #aaa; background: #f0f0f0; color: #555;")
        urls = event.mimeData().urls()
        if urls:
            file_path = urls[0].toLocalFile()
            self.fileDropped.emit(file_path)

class LlamaServerWidget(QWidget):
    server_state_changed = Signal(int) # 0: Red, 1: Yellow, 2: Green
    output_received = Signal()         # For blinking the LED

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("kitty❤️llama")
        self.setMinimumSize(700, 850)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)

        self.model_path = ""
        self.mmproj_path = ""
        self.preview_window = None
        
        self.force_close = False
        self.waiting_for_server_ready = False

        self.init_ui()
        self.load_settings()

        # Port polling for LED state
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self.check_status)
        self.status_timer.start(2000)
        
        # Autorun logic
        if self.check_autorun.isChecked():
            QTimer.singleShot(500, self.start_server)

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        # --- Binary Selection ---
        bin_layout = QHBoxLayout()
        self.bin_path_edit = QLineEdit()
        self.bin_path_edit.setPlaceholderText("Binary name or full path...")
        self.bin_path_edit.setText("llama-server") 
        btn_browse_bin = QPushButton("Browse Bin")
        btn_browse_bin.clicked.connect(self.browse_binary)
        bin_layout.addWidget(QLabel("Server Binary:"))
        bin_layout.addWidget(self.bin_path_edit)
        bin_layout.addWidget(btn_browse_bin)
        main_layout.addLayout(bin_layout)

        # --- Model & MMProj Drop Areas ---
        drops_group = QGroupBox("Model Loading")
        drops_vbox = QVBoxLayout(drops_group)
        
        self.drop_area_model = DropArea("Drag & Drop GGUF Model Here", self)
        self.drop_area_model.fileDropped.connect(self.set_model_path)
        self.model_path_label = QLabel("No model selected")
        self.model_path_label.setStyleSheet("color: #2980b9; font-style: italic;")
        drops_vbox.addWidget(self.drop_area_model)
        drops_vbox.addWidget(self.model_path_label)

        self.drop_area_mmproj = DropArea("Drag & Drop MMProj (Optional) Here", self)
        self.drop_area_mmproj.fileDropped.connect(self.set_mmproj_path)
        mmproj_info_layout = QHBoxLayout()
        self.mmproj_path_label = QLabel("No mmproj selected")
        self.mmproj_path_label.setStyleSheet("color: #7f8c8d; font-style: italic;")
        mmproj_info_layout.addWidget(self.mmproj_path_label)
        btn_clear_mm = QPushButton("Clear")
        btn_clear_mm.setFixedWidth(50)
        btn_clear_mm.clicked.connect(lambda: self.set_mmproj_path(""))
        mmproj_info_layout.addWidget(btn_clear_mm)
        drops_vbox.addWidget(self.drop_area_mmproj)
        drops_vbox.addLayout(mmproj_info_layout)
        main_layout.addWidget(drops_group)

        # --- Configuration ---
        config_group = QGroupBox("Parameters")
        vbox_config = QVBoxLayout(config_group)
        grid = QGridLayout()

        self.spin_ctx = QSpinBox(); self.spin_ctx.setRange(512, 128000); self.spin_ctx.setValue(4096)
        grid.addWidget(QLabel("Ctx (-c):"), 0, 0); grid.addWidget(self.spin_ctx, 0, 1)

        self.spin_ngl = QSpinBox(); self.spin_ngl.setRange(0, 200); self.spin_ngl.setValue(32)
        grid.addWidget(QLabel("GPU (-ngl):"), 0, 2); grid.addWidget(self.spin_ngl, 0, 3)

        self.spin_threads = QSpinBox(); self.spin_threads.setRange(1, 64); self.spin_threads.setValue(os.cpu_count() or 4)
        grid.addWidget(QLabel("Threads:"), 0, 4); grid.addWidget(self.spin_threads, 0, 5)

        self.spin_port = QSpinBox(); self.spin_port.setRange(1024, 65535); self.spin_port.setValue(8080)
        grid.addWidget(QLabel("Port:"), 0, 6); grid.addWidget(self.spin_port, 0, 7)

        self.spin_temp = QDoubleSpinBox(); self.spin_temp.setRange(0.0, 2.0); self.spin_temp.setSingleStep(0.1); self.spin_temp.setValue(0.7)
        grid.addWidget(QLabel("Temp:"), 1, 0); grid.addWidget(self.spin_temp, 1, 1)

        self.spin_top_p = QDoubleSpinBox(); self.spin_top_p.setRange(0.0, 1.0); self.spin_top_p.setSingleStep(0.05); self.spin_top_p.setValue(0.0)
        grid.addWidget(QLabel("Top P:"), 1, 2); grid.addWidget(self.spin_top_p, 1, 3)

        self.spin_top_k = QSpinBox(); self.spin_top_k.setRange(0, 100); self.spin_top_k.setValue(0)
        grid.addWidget(QLabel("Top K:"), 1, 4); grid.addWidget(self.spin_top_k, 1, 5)

        self.combo_kv = QComboBox()
        self.combo_kv.addItems(["Default", "f16", "q8_0", "q4_0"])
        grid.addWidget(QLabel("KV Cache:"), 1, 6); grid.addWidget(self.combo_kv, 1, 7)
        vbox_config.addLayout(grid)

        extra_layout = QHBoxLayout()
        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("e.g. --repeat-penalty 1.1 ...")
        extra_layout.addWidget(QLabel("Extra Args:"))
        extra_layout.addWidget(self.extra_args)
        vbox_config.addLayout(extra_layout)
        main_layout.addWidget(config_group)

        # --- Controls ---
        ctrl_layout = QHBoxLayout()
        self.check_autorun = QCheckBox("Autorun on start")
        self.check_autorun.setChecked(False)
        ctrl_layout.addWidget(self.check_autorun)

        self.check_preview = QCheckBox("Display preview")
        self.check_preview.setChecked(False)
        ctrl_layout.addWidget(self.check_preview)
        
        self.check_lan = QCheckBox("Share over LAN")
        self.check_lan.setChecked(False)
        ctrl_layout.addWidget(self.check_lan)
        
        ctrl_layout.addStretch()
        
        self.btn_start = QPushButton("Start Server")
        self.btn_start.clicked.connect(self.start_server)
        ctrl_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("Stop Server")
        self.btn_stop.clicked.connect(self.stop_server)
        ctrl_layout.addWidget(self.btn_stop)

        self.btn_webui = QPushButton("WebUI")
        self.btn_webui.clicked.connect(self.open_preview)
        ctrl_layout.addWidget(self.btn_webui)
        main_layout.addLayout(ctrl_layout)

        # --- URL & Logs ---
        url_layout = QHBoxLayout()
        self.url_display = QLineEdit()
        self.url_display.setReadOnly(True)
        self.url_display.setStyleSheet("background: #ecf0f1; font-weight: bold; color: #2c3e50;")
        url_layout.addWidget(QLabel("Base URL:"))
        url_layout.addWidget(self.url_display)
        main_layout.addLayout(url_layout)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; font-family: 'Courier New', Courier, monospace;")
        main_layout.addWidget(self.log_view)

    def browse_binary(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select llama binary")
        if path: self.bin_path_edit.setText(path)

    def set_model_path(self, path):
        if path and not path.lower().endswith('.gguf'):
             self.log_append("Warning: Selected model may not be a GGUF file.")
        self.model_path = path
        self.model_path_label.setText(f"Model: {os.path.basename(path)}" if path else "No model selected")
        if path: self.log_append(f"Model selected: {path}")

    def set_mmproj_path(self, path):
        self.mmproj_path = path
        self.mmproj_path_label.setText(f"MMProj: {os.path.basename(path)}" if path else "No mmproj selected")
        if path: self.log_append(f"MMProj selected: {path}")

    def log_append(self, text):
        self.log_view.appendPlainText(text)

    def handle_stdout(self):
        data = self.process.readAllStandardOutput().data().decode(errors='replace')
        if data:
            self.log_append(data.strip())
            self.output_received.emit()
            if self.waiting_for_server_ready and "starting the main loop" in data.lower():
                self.waiting_for_server_ready = False
                self.open_preview()

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode(errors='replace')
        if data:
            self.log_append(data.strip())
            self.output_received.emit()
            if self.waiting_for_server_ready and "starting the main loop" in data.lower():
                self.waiting_for_server_ready = False
                self.open_preview()

    def check_status(self):
        if self.process.state() == QProcess.Running:
            self.server_state_changed.emit(2) # Green
        else:
            if self.is_port_in_use(self.spin_port.value()):
                self.server_state_changed.emit(1) # Yellow (Blocked)
            else:
                self.server_state_changed.emit(0) # Red (Clear)

    def save_settings(self):
        settings = {
            "bin_path": self.bin_path_edit.text(),
            "model_path": self.model_path,
            "mmproj_path": self.mmproj_path,
            "ctx": self.spin_ctx.value(),
            "ngl": self.spin_ngl.value(),
            "threads": self.spin_threads.value(),
            "port": self.spin_port.value(),
            "temp": self.spin_temp.value(),
            "top_p": self.spin_top_p.value(),
            "top_k": self.spin_top_k.value(),
            "kv_cache": self.combo_kv.currentIndex(),
            "extra": self.extra_args.text(),
            "preview": self.check_preview.isChecked(),
            "share_lan": self.check_lan.isChecked(),
            "autorun": self.check_autorun.isChecked()
        }
        try:
            with open(CONFIG_FILE, "w") as f: json.dump(settings, f, indent=4)
        except Exception as e:
            self.log_append(f"Failed to save settings: {e}")

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE): return
        try:
            with open(CONFIG_FILE, "r") as f:
                s = json.load(f)
                self.bin_path_edit.setText(s.get("bin_path", "llama-server"))
                self.set_model_path(s.get("model_path", ""))
                self.set_mmproj_path(s.get("mmproj_path", ""))
                self.spin_ctx.setValue(s.get("ctx", 4096))
                self.spin_ngl.setValue(s.get("ngl", 32))
                self.spin_threads.setValue(s.get("threads", 4))
                self.spin_port.setValue(s.get("port", 8080))
                self.spin_temp.setValue(s.get("temp", 0.7))
                self.spin_top_p.setValue(s.get("top_p", 0.0))
                self.spin_top_k.setValue(s.get("top_k", 0))
                self.combo_kv.setCurrentIndex(s.get("kv_cache", 0))
                self.extra_args.setText(s.get("extra", ""))
                self.check_preview.setChecked(s.get("preview", False))
                self.check_lan.setChecked(s.get("share_lan", False))
                self.check_autorun.setChecked(s.get("autorun", False))
        except Exception as e:
            self.log_append(f"Failed to load settings: {e}")

    def is_port_in_use(self, port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('127.0.0.1', port)) == 0
    
    def free_port(self, port):
        self.log_append(f"\n[DEBUG] Port {port} is blocked! Hunting down the zombie process...")
        killed_any = False
        if sys.platform.startswith("win"):
            try:
                output = subprocess.check_output(["netstat", "-ano"], text=True, stderr=subprocess.STDOUT)
                for line in output.splitlines():
                    if f":{port}" in line and "LISTENING" in line:
                        parts = line.strip().split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            self.log_append(f"[DEBUG] Killing PID {pid}")
                            kill_out = subprocess.check_output(["taskkill", "/F", "/PID", pid], text=True, stderr=subprocess.STDOUT)
                            self.log_append(f"[DEBUG] {kill_out.strip()}")
                            killed_any = True
            except Exception as e:
                self.log_append(f"[DEBUG] Windows port hunt error: {e}")
        else:
            try:
                output = subprocess.check_output(["lsof", "-t", "-i", f"tcp:{port}"], text=True, stderr=subprocess.DEVNULL)
                for pid_str in output.strip().split():
                    if pid_str:
                        pid = int(pid_str)
                        self.log_append(f"[DEBUG] Sending SIGKILL to PID {pid}")
                        os.kill(pid, 9)
                        killed_any = True
            except Exception as e:
                self.log_append(f"[DEBUG] Unix port hunt error: {e}")
                
        if killed_any: time.sleep(1)

    def start_server(self):
        if not self.model_path:
            self.log_append("ERROR: Please select or drop a GGUF model first.")
            return

        self.stop_server()
        port = self.spin_port.value()
        
        if self.is_port_in_use(port):
            self.free_port(port)
            if self.is_port_in_use(port):
                self.log_append(f"ERROR: Port {port} is STILL in use! Cannot clear port.")
                return

        self.save_settings()
        
        if self.check_lan.isChecked():
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                display_ip = s.getsockname()[0]
                s.close()
            except Exception:
                display_ip = "127.0.0.1" 
            host_arg = "0.0.0.0" 
            base_url = f"http://{display_ip}:{port}"
        else:
            host_arg = "127.0.0.1"
            base_url = f"http://127.0.0.1:{port}"

        self.url_display.setText(base_url+"/v1")

        input_bin = self.bin_path_edit.text().strip()
        binary = os.path.abspath(input_bin) if os.path.exists(input_bin) else shutil.which(input_bin)
        if not binary and input_bin == "llama-server":
            binary = shutil.which("llama-serve")

        if not binary:
            self.log_append(f"ERROR: Could not find binary '{input_bin}'.")
            return

        args = [
            "-m", self.model_path, "--host", host_arg, "--port", str(port),
            "-c", str(self.spin_ctx.value()), "-ngl", str(self.spin_ngl.value()),
            "-t", str(self.spin_threads.value()), "--temp", str(self.spin_temp.value())
        ]
        if self.spin_top_p.value() > 0: args.extend(["--top-p", str(self.spin_top_p.value())])
        if self.spin_top_k.value() > 0: args.extend(["--top-k", str(self.spin_top_k.value())])
        if self.combo_kv.currentIndex() > 0:
            kv_type = self.combo_kv.currentText()
            args.extend(["--cache-type-k", kv_type, "--cache-type-v", kv_type])
        if self.mmproj_path: args.extend(["--mmproj", self.mmproj_path])
        args.extend(self.extra_args.text().split())

        self.log_append(f"\n>>> Executing: {binary} {' '.join(args)}")
        self.process.start(binary, args)

        if self.process.waitForStarted(3000):
            self.btn_start.setEnabled(False)
            self.waiting_for_server_ready = self.check_preview.isChecked()
            self.check_status()
        else:
            self.log_append(f"ERROR: Failed to start process (Error Code: {self.process.error()}).")

    def open_preview(self):
        url = self.url_display.text().replace("/v1", "")
        if not url: return
        
        if HAS_WEBENGINE:
            try:
                if not self.preview_window:
                    self.preview_window = QMainWindow()
                    self.preview_window.resize(1024, 768)
                    self.browser = QWebEngineView()
                    self.preview_window.setCentralWidget(self.browser)
                self.preview_window.setWindowTitle(f"Llama Preview - {self.spin_port.value()}")
                self.browser.setUrl(QUrl(url))
                self.preview_window.show()
            except RuntimeError:
                self.preview_window = QMainWindow()
                self.preview_window.resize(1024, 768)
                self.browser = QWebEngineView()
                self.preview_window.setCentralWidget(self.browser)
                self.preview_window.setWindowTitle(f"Llama Preview - {self.spin_port.value()}")
                self.browser.setUrl(QUrl(url))
                self.preview_window.show()
        else:
            self.log_append("Warning: PySide6-WebEngine not found. Opening in system browser.")
            webbrowser.open(url)

    def stop_server(self):
        if self.process.state() != QProcess.NotRunning:
            self.process.terminate()
            if not self.process.waitForFinished(2000):
                self.process.kill()
                self.process.waitForFinished(1000)
        else:
            self.free_port(self.spin_port.value())
                
        if self.preview_window:
            self.preview_window.close()
            if hasattr(self, 'browser') and self.browser:
                self.browser.setUrl(QUrl("about:blank"))
        self.check_status()

    def process_finished(self):
        self.log_append("<<< Server process stopped.")
        self.btn_start.setEnabled(True)
        self.check_status()

    def closeEvent(self, event):
        # Prevent the window from killing the server when the user 'X's it out
        if not self.force_close:
            self.hide()
            self.save_settings()
            event.ignore()
        else:
            self.stop_server()
            self.save_settings()
            event.accept()

# Standalone execution Wrapper
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setWindowIcon(QIcon(os.path.join(os.path.dirname(__file__), "..", "assets", "kittycon.png")))
    window = LlamaServerWidget()
    window.force_close = True # Standalone mode forces close
    window.show()
    sys.exit(app.exec())