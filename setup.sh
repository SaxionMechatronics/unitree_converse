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
echo "[1/5] Installing Python dependencies..."
if [ "$IS_ROBOT" == "true" ]; then
    pip3 install faster-whisper sounddevice soundfile tqdm filelock openwakeword
    sudo apt-get install -y sox portaudio19-dev
else
    pip install faster-whisper sounddevice soundfile tqdm filelock openwakeword piper-tts
    sudo apt-get install -y sox portaudio19-dev
fi

# ── Piper voice model (both machines) ───────────────────────────
echo ""
echo "[2/5] Downloading Piper voice model..."
mkdir -p ~/.local/share/piper
cd ~/.local/share/piper
wget -q --show-progress \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget -q --show-progress \
    https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json
cd -

# ── Piper binary (Jetson only) ───────────────────────────────────
if [ "$IS_ROBOT" == "true" ]; then
    echo ""
    echo "[3/5] Installing Piper standalone binary (aarch64)..."
    wget -q --show-progress \
        https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
    tar -xzf piper_linux_aarch64.tar.gz
    sudo cp piper/piper /usr/local/bin/piper
    rm -rf piper piper_linux_aarch64.tar.gz
    echo "Piper binary installed at /usr/local/bin/piper"
else
    echo ""
    echo "[3/5] Skipping Piper binary (dev machine uses piper-tts Python package)"
fi

# ── Ollama + LLaMA 3.2 ──────────────────────────────────────────
echo ""
echo "[4/5] Installing Ollama and pulling LLaMA 3.2 3B..."
if ! command -v ollama &> /dev/null; then
    curl -fsSL https://ollama.com/install.sh | sh
fi
ollama pull llama3.2

# ── Build workspace ──────────────────────────────────────────────
echo ""
echo "[5/5] Building ROS2 workspace..."
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

# ── Systemd service (Jetson only) ───────────────────────────────
if [ "$IS_ROBOT" == "true" ]; then
    echo ""
    read -p "Install systemd service (auto-start at boot)? [y/N]: " INSTALL_SERVICE
    if [ "$INSTALL_SERVICE" == "y" ] || [ "$INSTALL_SERVICE" == "Y" ]; then
        sudo cp unitree_converse.service /etc/systemd/system/
        sudo systemctl daemon-reload
        sudo systemctl enable unitree_converse.service
        sudo systemctl start unitree_converse.service
        echo "Service installed and started."
    fi
fi

echo ""
echo "========================================"
echo "   Setup complete!"
echo "========================================"
if [ "$IS_ROBOT" == "true" ]; then
    echo ""
    echo "To launch manually (stop service first):"
    echo "  sudo systemctl stop unitree_converse.service"
    echo "  source /opt/ros/foxy/setup.bash"
    echo "  source ~/cyclonedds_ws/install/setup.bash"
    echo "  source install/setup.bash"
    echo "  ros2 launch g1_voice voice_real.launch.py"
else
    echo ""
    echo "To launch on dev machine:"
    echo "  source /opt/ros/humble/setup.bash"
    echo "  source install/setup.bash"
    echo "  ros2 launch g1_voice voice_sim.launch.py"
fi
