![alt text](https://img.shields.io/badge/license-MIT-blue.svg) ![alt text](https://img.shields.io/badge/python-3.10%2B-green.svg) ![alt text](https://img.shields.io/badge/UI-PySide6-orange.svg)

# kitty❤️llama

A lightweight, elegant Python GUI wrapper for llama-server (from the llama.cpp project). kitty❤️llama simplifies the process of launching and managing local LLM servers with a focus on ease of use, drag-and-drop functionality, and real-time monitoring.

## ✨ Features
Drag & Drop Loading: Easily load .gguf models and mmproj (multimodal) files by dropping them directly into the UI.

Configuration Persistence: Automatically saves your last used settings, paths, and parameters to kitty_config.json.

Integrated Browser: Built-in web preview using QtWebEngine to interact with the llama-server UI without leaving the app.

Real-time Logging: Terminal output is captured and displayed in a clean, scrollable log view.

Flexible Parameters: Fine-tune context size, GPU layers (ngl), thread count, temperature, and additional CLI arguments.

Process Management: Safe shutdown handling ensures the backend server is killed properly when the application closes.

## 🚀 Getting Started

Prerequisites
Python 3.10+
PySide6

llama.cpp Binaries: You must have the llama-server (or llama-serve) executable for your platform. You can download them from the llama.cpp releases page.

## 📦 Installation
Clone the repository:

code
```bash
git clone https://github.com/ROCK-LAB-PRIVATE-LIMITED/kitty-loves-llama
cd kitty-llama
```
Install dependencies:

code
```bash
pip install PySide6
```
## ⚡ Usage
Run the application:

code
```bash
python src/kitty-loves-llama.py
```
Set the Binary: Click "Browse Bin" or type the path to your llama-server executable.

Load a Model: Drag and drop a .gguf file into the first drop area.

Load multimodal/vision pipeline: Drag and drop the associated mmproj.gguf (or similar) into the second drop area. If none available, ignore this.

Configure: Adjust your context size, GPU layers (set to 0 for CPU only), and port.

Start: Hit Start Server. If "Display preview" is checked, the chat interface will open automatically.

## 🛠️ Build for distribution

Install build dependencies:
code
```bash
pip install nuitka==2.7.14
```
Build with nuitka:
```bash
cd src
nuitka kitty-loves-llama.py
```

## ⚙️ Configuration Fields
Parameter	Description
Server Binary	Path to the llama-server executable.
Context Size	Total tokens the model can process (-c).
GPU Layers	Number of layers to offload to GPU (-ngl).
Threads	Number of CPU threads to use (-t).
Extra Args	Add any other flags like --continuous-batching or --flash-attn.

More args will be added soon.

## 📝 Troubleshooting
Binary not found: Ensure you have selected the actual executable file (e.g., llama-server.exe on Windows).

Web Preview not showing: If PySide6-WebEngine is missing, the app will automatically fallback to opening the server URL in your default system browser (Chrome, Firefox, etc.).

GPU Loading: If the server fails to start with GPU layers, ensure your llama-server build matches your hardware (CUDA vs Metal vs Vulkan).

## 📄 License
This project is licensed under the MIT License - see the LICENSE file for details.

Made with ❤️ for the local LLM community.
