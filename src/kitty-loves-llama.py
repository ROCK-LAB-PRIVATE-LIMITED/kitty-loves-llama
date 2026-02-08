import sys
import os
import shutil
import json
import webbrowser
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QLineEdit, QSpinBox, QDoubleSpinBox, QPushButton, 
    QPlainTextEdit, QFileDialog, QGroupBox, QFormLayout, QCheckBox
)
from PySide6.QtCore import Qt, QProcess, Signal, QUrl, QTimer

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

class LlamaWrapperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("kitty❤️llama")
        self.setMinimumSize(700, 850)

        self.process = QProcess(self)
        self.process.readyReadStandardOutput.connect(self.handle_stdout)
        self.process.readyReadStandardError.connect(self.handle_stderr)
        self.process.finished.connect(self.process_finished)

        self.model_path = ""
        self.mmproj_path = ""
        self.preview_window = None

        self.init_ui()
        self.load_settings()
        
        self.is_closing = False

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

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

        # --- Model & MMProj Drop Areas (Vertical Stack) ---
        drops_group = QGroupBox("Model Loading")
        drops_vbox = QVBoxLayout(drops_group)
        
        # Main Model
        self.drop_area_model = DropArea("Drag & Drop GGUF Model Here", self)
        self.drop_area_model.fileDropped.connect(self.set_model_path)
        self.model_path_label = QLabel("No model selected")
        self.model_path_label.setStyleSheet("color: #2980b9; font-style: italic;")
        drops_vbox.addWidget(self.drop_area_model)
        drops_vbox.addWidget(self.model_path_label)

        # MMProj
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
        form_layout = QFormLayout(config_group)

        self.spin_ctx = QSpinBox()
        self.spin_ctx.setRange(512, 128000)
        self.spin_ctx.setValue(4096)
        form_layout.addRow("Context Size (-c):", self.spin_ctx)

        self.spin_ngl = QSpinBox()
        self.spin_ngl.setRange(0, 200)
        self.spin_ngl.setValue(32)
        form_layout.addRow("GPU Layers (-ngl):", self.spin_ngl)

        self.spin_threads = QSpinBox()
        self.spin_threads.setRange(1, 64)
        self.spin_threads.setValue(os.cpu_count() or 4)
        form_layout.addRow("Threads (-t):", self.spin_threads)

        self.spin_port = QSpinBox()
        self.spin_port.setRange(1024, 65535)
        self.spin_port.setValue(8080)
        form_layout.addRow("Port:", self.spin_port)

        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 2.0)
        self.spin_temp.setSingleStep(0.1)
        self.spin_temp.setValue(0.7)
        form_layout.addRow("Temperature:", self.spin_temp)

        self.extra_args = QLineEdit()
        self.extra_args.setPlaceholderText("--top-k 40 --top-p 0.95 ...")
        form_layout.addRow("Extra Args:", self.extra_args)

        main_layout.addWidget(config_group)

        # --- Controls ---
        ctrl_layout = QHBoxLayout()
        self.check_preview = QCheckBox("Display preview")
        self.check_preview.setChecked(False)
        
        self.btn_start = QPushButton("Start Server")
        self.btn_start.setFixedHeight(40)
        self.btn_start.setStyleSheet("background-color: #27ae60; color: white; font-weight: bold;")
        self.btn_start.clicked.connect(self.start_server)

        self.btn_stop = QPushButton("Stop Server")
        self.btn_stop.setFixedHeight(40)
        self.btn_stop.setEnabled(False)
        self.btn_stop.setStyleSheet("background-color: #c0392b; color: white; font-weight: bold;")
        self.btn_stop.clicked.connect(self.stop_server)

        ctrl_layout.addWidget(self.check_preview)
        ctrl_layout.addStretch()
        ctrl_layout.addWidget(self.btn_start)
        ctrl_layout.addWidget(self.btn_stop)
        main_layout.addLayout(ctrl_layout)

        # --- Logs ---
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet("background-color: #2c3e50; color: #ecf0f1; font-family: 'Courier New', Courier, monospace;")
        main_layout.addWidget(self.log_view)

    def browse_binary(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select llama binary")
        if path:
            self.bin_path_edit.setText(path)

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
        self.log_append(data.strip())

    def handle_stderr(self):
        data = self.process.readAllStandardError().data().decode(errors='replace')
        self.log_append(data.strip())

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
            "extra": self.extra_args.text(),
            "preview": self.check_preview.isChecked()
        }
        try:
            with open(CONFIG_FILE, "w") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            self.log_append(f"Failed to save settings: {e}")

    def load_settings(self):
        if not os.path.exists(CONFIG_FILE):
            return
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
                self.extra_args.setText(s.get("extra", ""))
                self.check_preview.setChecked(s.get("preview", False))
        except Exception as e:
            self.log_append(f"Failed to load settings: {e}")

    def start_server(self):
        if not self.model_path:
            self.log_append("ERROR: Please select or drop a GGUF model first.")
            return

        self.save_settings()
        input_bin = self.bin_path_edit.text().strip()
        
        binary = None
        if os.path.exists(input_bin) and not os.path.isdir(input_bin):
            binary = input_bin
        else:
            binary = shutil.which(input_bin)
            if not binary and input_bin == "llama-server":
                binary = shutil.which("llama-serve")

        if not binary:
            self.log_append(f"ERROR: Could not find binary '{input_bin}'.")
            return

        args = [
            "-m", self.model_path,
            "-c", str(self.spin_ctx.value()),
            "-ngl", str(self.spin_ngl.value()),
            "-t", str(self.spin_threads.value()),
            "--port", str(self.spin_port.value()),
            "--temp", str(self.spin_temp.value())
        ]

        if self.mmproj_path:
            args.extend(["--mmproj", self.mmproj_path])

        extra = self.extra_args.text().split()
        args.extend(extra)

        self.log_append(f"\n>>> Executing: {binary} {' '.join(args)}")
        self.process.start(binary, args)

        if self.process.waitForStarted(3000):
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            if self.check_preview.isChecked():
                self.open_preview()
        else:
            self.log_append(f"ERROR: Failed to start process (Error Code: {self.process.error()}).")

    def open_preview(self):
        port = self.spin_port.value()
        url = f"http://127.0.0.1:{port}"
        if HAS_WEBENGINE:
            if not self.preview_window:
                self.preview_window = QMainWindow()
                self.preview_window.setWindowTitle(f"Llama Preview - {port}")
                self.preview_window.resize(1024, 768)
                self.browser = QWebEngineView()
                self.preview_window.setCentralWidget(self.browser)
            
            self.browser.setUrl(QUrl(url))
            self.preview_window.show()
        else:
            self.log_append("Warning: PySide6-WebEngine not found. Opening in system browser.")
            webbrowser.open(url)

    def stop_server(self):
        if self.process.state() == QProcess.Running:
            self.process.terminate()
            if not self.process.waitForFinished(3000):
                self.process.kill()
        if self.preview_window:
            self.preview_window.close()

    def process_finished(self):
        self.log_append("<<< Server process stopped.")
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        
        # If we were waiting for the process to stop to close the app:
        if self.is_closing:
            self.close()

    def closeEvent(self, event):
        # 1. If the process is already dead, just save and exit
        if self.process.state() == QProcess.NotRunning:
            self.save_settings()
            event.accept()
            return

        # 2. If the process is running, stop the exit and start killing the process
        self.log_append("Stopping server before exit...")
        self.is_closing = True
        
        # Use your existing stop_server logic
        # (It uses terminate() then kill() after 3s)
        self.stop_server()
        
        # 3. Ignore this specific close attempt. 
        # Once the process triggers 'finished', process_finished() will call self.close() again.
        event.ignore()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LlamaWrapperApp()
    window.show()
    sys.exit(app.exec())
