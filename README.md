# unitree_converse

A complete voice conversation pipeline for the **Unitree G1 humanoid robot** ("Aletta"), running fully on-robot with no cloud dependency. The robot listens, understands, and responds using a smooth English female voice through its built-in speaker.

---

## Demo

- **Hold F1** on the Unitree remote → robot listens → release F1 → robot responds
- **Press F3** → toggle continuous conversation mode (robot keeps listening after each response)
- Aletta knows her battery level, orientation, network status, uptime, and software stack

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      Jetson Orin NX 16GB (192.168.123.164)              │
│                                                                          │
│  ┌──────────────────┐   /g1/voice/trigger    ┌─────────────────────┐   │
│  │ button_trigger_  │ ───────────────────►   │     stt_node        │   │
│  │ node             │                         │                     │   │
│  │                  │   /g1/voice/            │  faster-whisper     │   │
│  │  F1 = push-to-   │   stop_recording  ────► │  base model (CPU)   │   │
│  │  talk            │                         │                     │   │
│  │  F3 = continuous │   /g1/voice/            │  UDP mic stream     │   │
│  │  mode toggle     │   continuous_start/stop │  239.168.123.161    │   │
│  └──────────────────┘                         └──────────┬──────────┘   │
│         ▲                                                │               │
│  /wirelesscontroller                        /g1/stt/transcript           │
│         │                                                │               │
│  ┌──────────────────┐                                    ▼               │
│  │ Unitree Remote   │                        ┌─────────────────────┐    │
│  │ F1: keys=64      │                        │  robot_state_node   │    │
│  │ F3: keys=128     │                        │                     │    │
│  └──────────────────┘                        │  Injects live state │    │
│                                              │  into LLM context   │    │
│                                              └──────────┬──────────┘    │
│                                                         │               │
│                                                   llm_prompt            │
│                                                         │               │
│                                                         ▼               │
│                                              ┌─────────────────────┐    │
│                                              │     llm_node        │    │
│                                              │    (bob_llm)        │    │
│                                              │                     │    │
│                                              │  Ollama LLaMA 3.2   │    │
│                                              │  3B (GPU)           │    │
│                                              └──────────┬──────────┘    │
│                                                         │               │
│                                                  llm_response           │
│                                                         │               │
│                                                         ▼               │
│                                              ┌─────────────────────┐    │
│                                              │     tts_node        │    │
│                                              │                     │    │
│                                              │  Piper TTS          │    │
│                                              │  en_US-lessac-      │    │
│                                              │  medium             │    │
│                                              │  + sox resample     │    │
│                                              │  + AudioHub API     │    │
│                                              └─────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│   RockChip MCU (192.168.123.161)             │
│                                              │
│  Microphone → UDP multicast ─────────────►  │ → stt_node
│               239.168.123.161:5555           │
│                                              │
│  AudioHub API ◄── /api/voice/request ─────► │ ← tts_node (g1_piper_tts)
│  Speaker                                     │
└──────────────────────────────────────────────┘
```

---

## Hardware

| Component | Details |
|-----------|---------|
| Robot | Unitree G1 Edu (29-DOF + Dex3-L hands) |
| Onboard compute | NVIDIA Jetson Orin NX 16GB (`192.168.123.164`) |
| Dev machine | `luciferHimself` — Ubuntu 22.04, RTX Pro 5000 Blackwell |
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
    └── bob_llm/                        # LLM ROS2 node (upstream)
```

---

## Key Discovery: Audio Routing

The G1's audio is **not** handled by the Jetson's ALSA/PulseAudio. It is managed by a separate **RockChip MCU** at `192.168.123.161`.

### Microphone
The RockChip streams raw **16-bit mono 16kHz PCM** via UDP multicast. The `stt_node` joins the multicast group to receive mic audio.

```python
# stt_node.py — UDP multicast mic
sock.bind(('', 5555))
mreq = struct.pack('4s4s',
    socket.inet_aton('239.168.123.161'),
    socket.inet_aton('192.168.123.164'))
sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
```

### Speaker
Audio output uses the Unitree `AudioClient::PlayStream()` API which requires **16kHz mono PCM**. A custom C++ binary `g1_piper_tts` was written to handle this:

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
| `/g1/robot_state` | `std_msgs/String` | Live robot state (JSON) |
| `llm_prompt` | `std_msgs/String` | Enriched prompt (state + transcript) |
| `llm_response` | `std_msgs/String` | LLM reply |
| `/g1/tts/status` | `std_msgs/String` | speaking/idle |
| `/g1/button/status` | `std_msgs/String` | Button node status |
| `/lf/bmsstate` | `unitree_hg/msg/BmsState` | Battery state |
| `/odommodestate` | `unitree_go/msg/SportModeState` | IMU + motion mode |

---

## Button Mapping

| Button | Action |
|--------|--------|
| **Hold F1** (`keys=64`) | Push-to-talk: starts recording while held, stops and transcribes on release |
| **F3** (`keys=128`) | Toggle continuous conversation mode on/off |

Implemented in `button_trigger_node.py` with 0.3s debounce on F3.

---

## Conversation Modes

### Push-to-Talk (default)
Hold F1 while speaking → release → robot responds → done.

### Continuous Mode
Press F3 to toggle on → robot listens → responds → automatically listens again.
Press F3 again to stop.

---

## Robot State Awareness

`robot_state_node.py` collects live data and injects it into every LLM prompt:

```
[ROBOT STATE]
Battery: 53% (health 99%, 2.0A discharging, temp 37°C, 7 cycles)
Orientation: roll=-0.1° pitch=2.3° yaw=-84.5°
Motion mode: idle
Network: eth 192.168.123.164, wifi 10.0.1.147
Uptime: 2h 15m
Active ROS2 nodes: 8
LLM: Ollama LLaMA 3.2 3B (local)
STT: faster-whisper base
TTS: Piper en_US-lessac-medium (Aletta voice)
[/ROBOT STATE]
```

---

## Systemd Service

The pipeline auto-starts at boot via systemd:

```bash
# Status
sudo systemctl status unitree_converse.service

# Logs
journalctl -u unitree_converse.service -f

# Restart
sudo systemctl restart unitree_converse.service

# Stop
sudo systemctl stop unitree_converse.service
```

Service file: `/etc/systemd/system/unitree_converse.service`

**Important:** Never run `ros2 launch` manually while the service is running — they will conflict and cause `bad_alloc` crashes from DDS port collisions.

```bash
# Always stop the service first if launching manually
sudo systemctl stop unitree_converse.service
sleep 2
sudo rm -f /dev/shm/fastrtps_*
ros2 launch g1_voice voice_real.launch.py
```

---

## Installation

### On Jetson (Ubuntu 20.04, ROS2 Foxy)

```bash
# Python deps
pip3 install faster-whisper sounddevice soundfile tqdm filelock openwakeword

# Sox for audio resampling
sudo apt-get install -y sox

# Piper standalone binary (Python package unavailable for aarch64/Python 3.8)
wget https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz
tar -xzf piper_linux_aarch64.tar.gz
sudo cp piper/piper /usr/local/bin/piper

# Piper voice model
mkdir -p ~/.local/share/piper && cd ~/.local/share/piper
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx
wget https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json

# Ollama + LLaMA 3.2
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2

# Build g1_piper_tts C++ binary
cd ~/unitree_sdk2_latest/build
cmake .. && make g1_piper_tts -j$(nproc)

# Clone unitree_ros2 messages
git clone https://github.com/unitreerobotics/unitree_ros2.git
cd unitree_ros2/cyclonedds_ws
source /opt/ros/foxy/setup.bash
colcon build --packages-select unitree_go unitree_api unitree_hg
source install/setup.bash

# Build workspace
cd ~/unitree_converse
colcon build --symlink-install
source install/setup.bash

# Install systemd service
sudo cp unitree_converse.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable unitree_converse.service
sudo systemctl start unitree_converse.service
```

---

## Testing

```bash
# Manual transcript (bypasses mic, tests LLM + TTS)
ros2 topic pub --once /g1/stt/transcript std_msgs/msg/String "data: 'What is your battery level?'"

# Manual trigger (tests mic + full pipeline)
ros2 topic pub --once /g1/voice/trigger std_msgs/msg/Bool "data: true"

# Enable continuous mode
ros2 topic pub --once /g1/voice/continuous_start std_msgs/msg/Bool "data: true"

# Check robot state
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
    continuous_mode: false   # controlled at runtime by F3

/tts_node:
  ros__parameters:
    tts_mode: "binary"
    continuous_mode: false   # controlled at runtime by F3
```

---

## Sim-to-Real Differences

| Parameter | Simulation (dev machine) | Real Robot (Jetson) |
|-----------|--------------------------|---------------------|
| `use_udp_mic` | `false` (sounddevice) | `true` (UDP multicast) |
| `tts_mode` | `python` (piper-tts lib) | `binary` (g1_piper_tts) |
| ROS2 distro | Humble | Foxy |
| Network interface | `lo` or `wlp132s0f0` | `eth0` |
| DDS interface | cyclonedds.xml → `wlan0` (dev) | cyclonedds.xml → `eth0` |

---

## Known Issues

- **Never run manual launch while service is running** — causes DDS `bad_alloc` crashes. Always stop the service first.
- **cyclonedds.xml must use `eth0`** — if set to `wlan0` and WiFi isn't up, DDS fails to allocate shared memory at startup.
- **openWakeWord uses ~10GB RAM** — disabled in production (`use_wake_word: false`). Button trigger is used instead.
- **Piper Python package unavailable on aarch64/Python 3.8** — use the standalone binary + sox pipeline.
- **Jetson clock skew** — system clock is wrong, causes harmless `make` warnings.
- **Saxion WiFi AP isolation** — prevents SSH over WiFi. Use ethernet or a portable router.

---

## Future Work

- [ ] Custom "Aletta" wake word model with openWakeWord
- [ ] Map additional remote buttons (SELECT, L1/R1) to actions
- [ ] Add motion commands via voice ("walk forward", "sit down")
- [ ] Add `robot_state_node` pose tracking (feet contact, CoM position)
- [ ] Upgrade Jetson to ROS2 Humble
- [ ] Persistent conversation history across restarts

---

## Credits

- [bob_llm](https://github.com/bob-ros2/bob_llm) — ROS2 LLM node
- [Piper TTS](https://github.com/rhasspy/piper) — Fast local TTS
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Efficient Whisper implementation
- Unitree Robotics — G1 SDK and AudioHub API

---

*SMART Research Group — Saxion University of Applied Sciences, Enschede, Netherlands*
