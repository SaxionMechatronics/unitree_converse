# unitree_converse

A complete voice conversation pipeline for the **Unitree G1 humanoid robot** ("Aletta"), running fully on-robot with no cloud dependency. The robot listens, understands, and responds using a smooth English female voice through its built-in speaker.

---

## Demo

- **Hold F1** on the Unitree remote → robot listens → release F1 → robot responds
- **Press F3** → toggle continuous conversation mode (robot keeps listening after each response)
- Aletta knows her battery level, orientation, network status, uptime, and software stack

---

## Quick Start

```bash
git clone --recurse-submodules https://github.com/AkhileshSingh01/unitree_converse.git
cd unitree_converse
./setup.sh
```

The setup script will ask whether you are setting up on the **Unitree G1 Jetson** or a **dev machine**, then handle everything automatically:

- Downloads Piper voice model (`en_US-lessac-medium`)
- Downloads faster-whisper base model
- Installs Piper binary (Jetson) or piper-tts Python package (dev machine)
- Installs and starts Ollama, pulls LLaMA 3.2 3B
- Builds the ROS2 workspace
- Installs and enables systemd services (Jetson only)

> **Note:** If `setup.sh` fails at any step, see the [Manual Installation](#manual-installation) section below for step-by-step instructions.

---

## Architecture

![unitree_converse architecture](unitree_converse_architecture.svg)

---

## Hardware

| Component | Details |
|-----------|---------|
| Robot | Unitree G1 Edu (29-DOF + Dex3-L hands) |
| Onboard compute | NVIDIA Jetson Orin NX 16GB (`192.168.123.164`) |
| Dev machine | Ubuntu 22.04, RTX Pro 5000 Blackwell |
| Microphone | G1 built-in mic via RockChip UDP multicast `239.168.123.161:5555` |
| Speaker | G1 built-in speaker via Unitree AudioHub API |
| Remote | Unitree wireless controller (`/wirelesscontroller`) |
| Network | Ethernet: dev `192.168.123.100` ↔ Jetson `192.168.123.164` |

---

## Software Stack

| Component | Technology |
|-----------|-----------|
| ROS2 | Foxy (Jetson) / Humble (dev machine) |
| DDS | CycloneDDS via `~/cyclonedds_ws` |
| LLM | Ollama + LLaMA 3.2 3B |
| LLM ROS2 node | bob_llm |
| Speech-to-text | faster-whisper (base, CPU) |
| Text-to-speech | Piper TTS (`en_US-lessac-medium`) |
| Audio output | Unitree AudioHub API via `g1_piper_tts` C++ binary |
| Wake word | openWakeWord (`hey_jarvis`) — disabled in production |

---

## Package Structure

```
unitree_converse/
├── setup.sh                        # Interactive setup script
├── unitree_converse.service        # Systemd service file
├── ollama.service                  # Ollama systemd service reference
├── README.md
└── src/
    ├── g1_voice/
    │   ├── g1_voice/
    │   │   ├── wake_word_node.py       # openWakeWord + keyboard trigger (sim)
    │   │   ├── stt_node.py             # faster-whisper + UDP mic + stop signal
    │   │   ├── tts_node.py             # Piper TTS via g1_piper_tts binary
    │   │   ├── button_trigger_node.py  # F1/F3 remote button mapping
    │   │   └── robot_state_node.py     # Live robot state injection into LLM
    │   ├── launch/
    │   │   ├── voice_sim.launch.py     # Dev machine (sounddevice mic, Python TTS)
    │   │   └── voice_real.launch.py    # On-robot (UDP mic, g1_piper_tts)
    │   └── config/
    │       ├── voice_params.yaml       # Dev machine params
    │       └── voice_params_real.yaml  # Jetson robot params
    └── bob_llm/                        # LLM ROS2 node (submodule, Foxy-patched fork)
```

---

## Key Discovery: Audio Routing

The G1's audio is **not** handled by the Jetson's ALSA/PulseAudio. It is managed by a separate **RockChip MCU** at `192.168.123.161`.

### Microphone
The RockChip streams raw **16-bit mono 16kHz PCM** via UDP multicast. The `stt_node` joins the multicast group to receive mic audio.

```python
sock.bind(('', 5555))
mreq = struct.pack('4s4s',
    socket.inet_aton('239.168.123.161'),
    socket.inet_aton('192.168.123.164'))
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
```

### Speaker
The G1 speaker is controlled via the Unitree `AudioClient::PlayStream()` API which requires **16kHz mono PCM**. A custom C++ binary `g1_piper_tts` handles this:

```
tts_node → subprocess: g1_piper_tts eth0 < text
               │
               ├── piper → /tmp/tts_raw.wav  (22050Hz)
               ├── sox → /tmp/tts_16k.wav    (16000Hz mono)
               └── AudioClient::PlayStream() → RockChip → Speaker
```

Source: `~/unitree_sdk2_latest/example/g1/audio/g1_piper_tts.cpp`
Binary: `~/unitree_sdk2_latest/build/bin/g1_piper_tts`

---

## ROS2 Topics

| Topic | Type | Purpose |
|-------|------|---------|
| `/wirelesscontroller` | `unitree_go/msg/WirelessController` | Remote button input |
| `/g1/voice/trigger` | `std_msgs/Bool` | Start recording |
| `/g1/voice/stop_recording` | `std_msgs/Bool` | Stop recording (F1 released) |
| `/g1/voice/continuous_start` | `std_msgs/Bool` | Enable continuous mode |
| `/g1/voice/continuous_stop` | `std_msgs/Bool` | Disable continuous mode |
| `/g1/stt/transcript` | `std_msgs/String` | Raw transcribed speech |
| `/g1/stt/status` | `std_msgs/String` | recording/transcribing/idle |
| `/g1/robot_state` | `std_msgs/String` | Live robot state |
| `llm_prompt` | `std_msgs/String` | Enriched prompt (state + transcript) |
| `llm_response` | `std_msgs/String` | LLM reply |
| `/g1/tts/status` | `std_msgs/String` | speaking/idle |
| `/g1/button/status` | `std_msgs/String` | Button node status |

---

## Button Mapping

| Button | Keys Value | Action |
|--------|-----------|--------|
| **Hold F1** | 64 | Push-to-talk: records while held, transcribes on release |
| **F3** | 128 | Toggle continuous conversation mode on/off |

---

## Conversation Modes

### Push-to-Talk (default)
Hold F1 while speaking → release → robot responds → done.

### Continuous Mode
Press F3 to toggle on → robot listens → responds → automatically listens again.
Press F3 again to stop.

---

## Systemd Services

The pipeline uses two systemd services that auto-start at boot:

```
ollama.service              ← runs LLaMA 3.2 3B on Jetson GPU
unitree_converse.service    ← voice pipeline (depends on ollama)
```

```bash
# Check status
sudo systemctl status unitree_converse.service
sudo systemctl status ollama.service

# Follow live logs
journalctl -u unitree_converse.service -f

# Restart after config changes
sudo systemctl restart unitree_converse.service

# Stop before manual launch
sudo systemctl stop unitree_converse.service
```

> **Critical:** Never run `ros2 launch` manually while the service is running. Both instances compete for CycloneDDS shared memory and cause `bad_alloc` crashes. Always stop the service first:
> ```bash
> sudo systemctl stop unitree_converse.service
> sleep 2
> sudo rm -f /dev/shm/fastrtps_*
> ros2 launch g1_voice voice_real.launch.py
> ```

---

## Testing

```bash
# Manual transcript — bypasses mic, tests LLM + TTS
ros2 topic pub --once /g1/stt/transcript std_msgs/msg/String "data: 'What is your battery level?'"

# Manual trigger — tests full pipeline including mic
ros2 topic pub --once /g1/voice/trigger std_msgs/msg/Bool "data: true"

# Enable continuous mode
ros2 topic pub --once /g1/voice/continuous_start std_msgs/msg/Bool "data: true"

# Check live robot state
ros2 topic echo /g1/robot_state

# Test TTS binary directly
echo "Hello, I am Aletta." | ~/unitree_sdk2_latest/build/bin/g1_piper_tts eth0
```

---

## Configuration (voice_params_real.yaml)

```yaml
/llm_node:
  ros__parameters:
    api_url: "http://localhost:11434/v1"
    api_model: "llama3.2"
    system_prompt: "You are Aletta, a friendly humanoid robot by Unitree Robotics at Saxion University. You have access to your live robot state in [ROBOT STATE] blocks. Use this to answer questions about your battery, orientation, network, and software. Keep ALL responses under 2 sentences. Be concise."

/stt_node:
  ros__parameters:
    use_udp_mic: true
    udp_multicast_group: "239.168.123.161"
    udp_port: 5555
    udp_local_ip: "192.168.123.164"
    silence_threshold: 0.008
    silence_duration: 2.0
    recording_duration: 8.0
    continuous_mode: false

/tts_node:
  ros__parameters:
    tts_mode: "binary"
    continuous_mode: false
```

---

## Sim-to-Real Differences

| Parameter | Simulation (dev machine) | Real Robot (Jetson) |
|-----------|--------------------------|---------------------|
| `use_udp_mic` | `false` (sounddevice) | `true` (UDP multicast) |
| `tts_mode` | `python` (piper-tts lib) | `binary` (g1_piper_tts) |
| ROS2 distro | Humble | Foxy |
| Network interface | `lo` or `wlp132s0f0` | `eth0` |
| CycloneDDS interface | `wlan0` (dev) | `eth0` (robot) |

---

## Manual Installation

> Use these steps if `setup.sh` fails at any point.

### Jetson Orin NX (Ubuntu 20.04, ROS2 Foxy)

```bash
# Python deps
pip3 install faster-whisper sounddevice soundfile tqdm filelock openwakeword
sudo apt-get install -y sox portaudio19-dev

# Piper binary
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
tar -xzf piper_linux_aarch64.tar.gz
sudo cp piper/piper /usr/local/bin/piper

# Piper voice model
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

# faster-whisper base model
python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Ollama
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# Build g1_piper_tts C++ binary
git clone https://github.com/unitreerobotics/unitree_sdk2.git unitree_sdk2_latest
# Add g1_piper_tts.cpp to example/g1/audio/ and update CMakeLists.txt
cd unitree_sdk2_latest/build && cmake .. && make g1_piper_tts -j$(nproc)

# unitree_ros2 messages
git clone https://github.com/unitreerobotics/unitree_ros2.git
cd unitree_ros2/cyclonedds_ws
source /opt/ros/foxy/setup.bash
colcon build --packages-select unitree_go unitree_api unitree_hg

# Build workspace
cd ~/unitree_converse
source /opt/ros/foxy/setup.bash
source ~/cyclonedds_ws/install/setup.bash
source ~/unitree_ros2/cyclonedds_ws/install/setup.bash
colcon build --symlink-install
source install/setup.bash

# Install services
sudo cp unitree_converse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ollama.service unitree_converse.service
sudo systemctl start ollama.service unitree_converse.service
```

### Dev Machine (Ubuntu 22.04, ROS2 Humble)

```bash
pip install faster-whisper sounddevice soundfile tqdm filelock openwakeword piper-tts
sudo apt-get install -y sox portaudio19-dev

mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

python3 -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

source /opt/ros/humble/setup.bash
cd ~/UNITREE/unitree_converse
colcon build --symlink-install
source install/setup.bash
ros2 launch g1_voice voice_sim.launch.py
```

---

## Known Issues

| Issue | Fix |
|-------|-----|
| `bad_alloc` on launch | Service already running. Stop it, clear `/dev/shm/fastrtps_*`, relaunch. Or reboot. |
| `cyclonedds.xml` must use `eth0` | If set to `wlan0` and WiFi not up at boot, DDS fails. Change `NetworkInterface` to `eth0`. |
| openWakeWord uses ~10GB RAM | Disable with `use_wake_word: false`. Use F1 button instead. |
| Battery showing unknown | `BmsState` uses `unitree_hg` (not `unitree_go`) and needs QoS `RELIABLE`. |
| Piper Python unavailable on aarch64 | Use standalone binary + sox pipeline (`g1_piper_tts`). |
| Saxion WiFi AP isolation | Cannot SSH over WiFi. Use ethernet (`192.168.123.164`) or portable router. |

---

## Future Work

- Custom "Aletta" wake word model
- Voice-controlled motion commands
- Persistent conversation history across reboots
- Upgrade Jetson to ROS2 Humble
- Map additional remote buttons to actions

---

## Credits

- [bob_llm](https://github.com/bob-ros2/bob_llm) — ROS2 LLM node
- [Piper TTS](https://github.com/rhasspy/piper) — Fast local TTS
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Efficient Whisper implementation
- Unitree Robotics — G1 SDK and AudioHub API

---

*SMART Research Group — Saxion University of Applied Sciences, Enschede, Netherlands*
