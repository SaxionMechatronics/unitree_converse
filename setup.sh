#!/bin/bash
set -e

echo "========================================"
echo "   unitree_converse — Aletta Setup"
echo "========================================"
echo ""
echo "Where are you setting this up?"
echo "  1) Unitree G1 Jetson Orin NX (Ubuntu 20.04, ROS2 Foxy)"
echo "  2) Dev machine (Ubuntu 22.04, ROS2 Humble)"
echo ""
read -p "Enter 1 or 2: " CHOICE

if [ "$CHOICE" == "1" ]; then
    echo ""
    echo ">>> Setting up for Unitree G1 Jetson..."
    ROS_DISTRO="foxy"
    IS_ROBOT=true
elif [ "$CHOICE" == "2" ]; then
    echo ""
    echo ">>> Setting up for dev machine..."
    ROS_DISTRO="humble"
    IS_ROBOT=false
else
    echo "Invalid choice. Exiting."
    exit 1
fi

# ── Common: Python deps ──────────────────────────────────────────
echo ""
echo "[1/6] Installing Python dependencies..."
if [ "$IS_ROBOT" == "true" ]; then
    pip3 install faster-whisper sounddevice soundfile tqdm filelock openwakeword
    sudo apt-get install -y sox portaudio19-dev
else
    pip install faster-whisper sounddevice soundfile tqdm filelock openwakeword piper-tts
    sudo apt-get install -y sox portaudio19-dev
fi

# ── Piper voice model (both machines) ───────────────────────────
echo ""
echo "[2/6] Downloading Piper voice model..."
mkdir -p ~/.local/share/piper
cd ~/.local/share/piper
wget -q --show-progress \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget -q --show-progress \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
cd -

# ── faster-whisper base model (both machines) ────────────────────
echo ""
echo "[3/6] Downloading faster-whisper base model..."
python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"
echo "faster-whisper base model cached."

# ── Piper binary (Jetson only) ───────────────────────────────────
if [ "$IS_ROBOT" == "true" ]; then
    echo ""
    echo "[4/6] Installing Piper standalone binary (aarch64)..."
    wget -q --show-progress \
        https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xzf piper_linux_aarch64.tar.gz
    sudo cp piper/piper /usr/local/bin/piper
    rm -rf piper piper_linux_aarch64.tar.gz
    echo "Piper binary installed at /usr/local/bin/piper"
else
    echo ""
    echo "[4/5] Skipping Piper binary (dev machine uses piper-tts Python package)"
fi

# ── Ollama + LLaMA 3.2 ──────────────────────────────────────────
echo ""
echo "[5/6] Installing Ollama and pulling LLaMA 3.2 3B..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
ollama pull llama3.2

# ── Build workspace ──────────────────────────────────────────────
echo ""
echo "[6/6] Building ROS2 workspace..."
source /opt/ros/$ROS_DISTRO/setup.bash

# Apply Foxy CMakeLists patch for bob_llm
if [ "$IS_ROBOT" == "true" ]; then
    cat > src/bob_llm/CMakeLists.txt << 'CMAKE'
cmake_minimum_required(VERSION 3.8)
project(bob_llm)
find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)
find_package(std_msgs REQUIRED)

install(DIRECTORY config DESTINATION share/${PROJECT_NAME})
ament_python_install_package(${PROJECT_NAME})
install(PROGRAMS
  bob_llm/llm_node.py
  bob_llm/chat_node.py
  DESTINATION lib/${PROJECT_NAME}
)
ament_package()
CMAKE
    echo "Applied Foxy-compatible CMakeLists.txt to bob_llm"
fi

colcon build --symlink-install
source install/setup.bash

# ── Systemd service ───────────────────────────────
if [ "$IS_ROBOT" == "true" ]; then
    echo ""
    read -p "Install systemd services (auto-start at boot)? [y/N]: " INSTALL_SERVICE
    if [ "$INSTALL_SERVICE" == "y" ] || [ "$INSTALL_SERVICE" == "Y" ]; then
        # Ollama — installed by install script, just enable
        sudo systemctl enable ollama.service
        sudo systemctl start ollama.service
        echo "Ollama service enabled."

        # unitree_converse
        sudo cp unitree_converse.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable unitree_converse.service
        sudo systemctl start unitree_converse.service
        echo "unitree_converse service enabled."
    fi
else
    echo ""
    echo "[6/6] Starting Ollama on dev machine..."
    # On dev machine just start Ollama — no systemd service needed
    if systemctl is-active --quiet ollama 2>/dev/null; then
        echo "Ollama already running."
    else
        # Start manually in background if not a service
        nohup ollama serve > /tmp/ollama.log 2>&1 &
        sleep 2
        echo "Ollama started in background (log: /tmp/ollama.log)"
        echo "To start automatically at login, add to ~/.bashrc:"
        echo "  nohup ollama serve > /tmp/ollama.log 2>&1 &"
    fi
fi
