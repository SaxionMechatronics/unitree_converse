import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Bool
import numpy as np
import socket
import struct
import threading
import time


class STTNode(Node):
    def __init__(self):
        super().__init__('stt_node')

        self.declare_parameter('model_size', 'base')
        self.declare_parameter('language', 'en')
        self.declare_parameter('device', 'cpu')
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('recording_duration', 8.0)
        self.declare_parameter('silence_threshold', 0.008)
        self.declare_parameter('silence_duration', 2.0)
        self.declare_parameter('use_udp_mic', True)
        self.declare_parameter('udp_multicast_group', '239.168.123.161')
        self.declare_parameter('udp_port', 5555)
        self.declare_parameter('udp_local_ip', '192.168.123.164')
        self.declare_parameter('continuous_mode', False)

        self.model_size = self.get_parameter('model_size').get_parameter_value().string_value
        self.language = self.get_parameter('language').get_parameter_value().string_value
        self.device = self.get_parameter('device').get_parameter_value().string_value
        self.sample_rate = self.get_parameter('sample_rate').get_parameter_value().integer_value
        self.recording_duration = self.get_parameter('recording_duration').get_parameter_value().double_value
        self.silence_threshold = self.get_parameter('silence_threshold').get_parameter_value().double_value
        self.silence_duration = self.get_parameter('silence_duration').get_parameter_value().double_value
        self.use_udp_mic = self.get_parameter('use_udp_mic').get_parameter_value().bool_value
        self.udp_multicast_group = self.get_parameter('udp_multicast_group').get_parameter_value().string_value
        self.udp_port = self.get_parameter('udp_port').get_parameter_value().integer_value
        self.udp_local_ip = self.get_parameter('udp_local_ip').get_parameter_value().string_value
        self.continuous_mode = self.get_parameter('continuous_mode').get_parameter_value().bool_value

        self.is_recording = False

        self.get_logger().info(f'Loading faster-whisper model: {self.model_size}')
        from faster_whisper import WhisperModel
        self.model = WhisperModel(self.model_size, device=self.device, compute_type='int8')
        self.get_logger().info('faster-whisper model loaded')

        self.trigger_sub = self.create_subscription(
            Bool, '/g1/voice/trigger', self.trigger_callback, 10)
	self.stop_sub = self.create_subscription(
    	    Bool, '/g1/voice/stop_recording', self.stop_callback, 10)
	self.stop_requested = False

        self.transcript_pub = self.create_publisher(String, '/g1/stt/transcript', 10)
        self.status_pub = self.create_publisher(String, '/g1/stt/status', 10)
        self.trigger_pub = self.create_publisher(Bool, '/g1/voice/trigger', 10)

        mic_mode = 'UDP multicast' if self.use_udp_mic else 'sounddevice'
        self.get_logger().info(f'STT node ready — mic: {mic_mode}')
        self.get_logger().info(f'Continuous mode: {self.continuous_mode}')

    def trigger_callback(self, msg: Bool):
        if msg.data and not self.is_recording:
            self.get_logger().info('Trigger received — starting recording')
            threading.Thread(target=self._record_and_transcribe, daemon=True).start()

    def _record_and_transcribe(self):
        self.is_recording = True
        self._publish_status('recording')

        if self.use_udp_mic:
            audio_data = self._record_via_udp()
        else:
            audio_data = self._record_via_sounddevice()

        if audio_data is None or len(audio_data) == 0:
            self.get_logger().warn('No audio recorded')
            self._publish_status('idle')
            self.is_recording = False
            # In continuous mode, re-trigger even on empty recording
            if self.continuous_mode:
                time.sleep(0.3)
                self._fire_trigger()
            return

        self._publish_status('transcribing')

        try:
            segments, info = self.model.transcribe(
                audio_data,
                language=self.language,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500)
            )

            transcript = ' '.join([seg.text.strip() for seg in segments]).strip()

            if transcript:
                self.get_logger().info(f'Transcript: "{transcript}"')
                msg = String()
                msg.data = transcript
                self.transcript_pub.publish(msg)
            else:
                self.get_logger().warn('Empty transcript — nothing detected')

        except Exception as e:
            self.get_logger().error(f'Transcription error: {e}')
            self._publish_status('error')
            self.is_recording = False
            return

        self._publish_status('idle')
        self.is_recording = False

    def _fire_trigger(self):
        trigger = Bool()
        trigger.data = True
        self.trigger_pub.publish(trigger)
        self.get_logger().info('Continuous mode — re-triggering STT')

    def _record_via_udp(self):
	self.stop_requested = False
        BYTES_PER_SAMPLE = 2
        target_bytes = int(self.sample_rate * BYTES_PER_SAMPLE * self.recording_duration)
        silence_limit = int(self.silence_duration * self.sample_rate * BYTES_PER_SAMPLE)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        sock.bind(('', self.udp_port))

        mreq = struct.pack('4s4s',
            socket.inet_aton(self.udp_multicast_group),
            socket.inet_aton(self.udp_local_ip))
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
        sock.settimeout(1.0)

        frames = []
        total_bytes = 0
        silence_bytes = 0
        speech_detected = False

        self.get_logger().info(f'Recording via UDP {self.udp_multicast_group}:{self.udp_port}...')

        try:
            while total_bytes < target_bytes and not self.stop_requested:
                try:
                    data, _ = sock.recvfrom(65535)
                    frames.append(data)
                    total_bytes += len(data)

                    samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                    rms = np.sqrt(np.mean(samples**2))

                    if rms >= self.silence_threshold:
                        speech_detected = True
                        silence_bytes = 0
                    else:
                        if speech_detected:
                            silence_bytes += len(data)

                    if speech_detected and silence_bytes >= silence_limit:
                        self.get_logger().info('Silence detected — stopping early')
                        break

                except socket.timeout:
                    self.get_logger().warn('UDP timeout')
                    break

        except Exception as e:
            self.get_logger().error(f'UDP recording error: {e}')
            return None
        finally:
            sock.close()

        if not frames:
            return None

        raw = b''.join(frames)
        return np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    def _record_via_sounddevice(self):
        import sounddevice as sd

        audio_frames = []
        silence_frames = 0
        silence_limit = int(self.silence_duration * self.sample_rate)
        chunk_size = 1024
        speech_detected = False

        def audio_callback(indata, frames, time, status):
            audio_frames.append(indata.copy())

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='float32',
                blocksize=chunk_size,
                callback=audio_callback
            ):
                self.get_logger().info('Recording via sounddevice...')
                total_samples = 0
                max_samples = int(self.recording_duration * self.sample_rate)

                while total_samples < max_samples:
                    sd.sleep(100)
                    total_samples = sum(len(f) for f in audio_frames)

                    if audio_frames:
                        recent = np.concatenate(audio_frames[-10:]) if len(audio_frames) >= 10 else np.concatenate(audio_frames)
                        rms = np.sqrt(np.mean(recent**2))
                        if rms >= self.silence_threshold:
                            speech_detected = True
                            silence_frames = 0
                        else:
                            if speech_detected:
                                silence_frames += chunk_size

                        if speech_detected and silence_frames >= silence_limit:
                            self.get_logger().info('Silence detected — stopping early')
                            break

        except Exception as e:
            self.get_logger().error(f'Recording error: {e}')
            return None

        if not audio_frames:
            return None

        return np.concatenate(audio_frames).flatten()

    def _publish_status(self, status: str):
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)

    def stop_callback(self, msg: Bool):
    	if msg.data:
        	self.stop_requested = True
        	self.get_logger().info('Stop recording requested')


def main(args=None):
    rclpy.init(args=args)
    node = STTNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
