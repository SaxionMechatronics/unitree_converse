import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
import numpy as np
import sounddevice as sd
import threading
import queue
import time


class WakeWordNode(Node):
    def __init__(self):
        super().__init__('wake_word_node')

        self.declare_parameter('wake_word_model', 'hey_jarvis')
        self.declare_parameter('detection_threshold', 0.5)
        self.declare_parameter('sample_rate', 16000)
        self.declare_parameter('chunk_duration', 0.08)
        self.declare_parameter('use_wake_word', True)
        self.declare_parameter('use_select_button', True)
        self.declare_parameter('select_key', 's')

        self.wake_word_model = self.get_parameter('wake_word_model').get_parameter_value().string_value
        self.detection_threshold = self.get_parameter('detection_threshold').get_parameter_value().double_value
        self.sample_rate = self.get_parameter('sample_rate').get_parameter_value().integer_value
        self.chunk_duration = self.get_parameter('chunk_duration').get_parameter_value().double_value
        self.use_wake_word = self.get_parameter('use_wake_word').get_parameter_value().bool_value
        self.use_select_button = self.get_parameter('use_select_button').get_parameter_value().bool_value
        self.select_key = self.get_parameter('select_key').get_parameter_value().string_value

        self.last_trigger_time = 0.0
        self.cooldown = 3.0
        self.oww_model = None

        self.trigger_pub = self.create_publisher(Bool, '/g1/voice/trigger', 10)
        self.status_pub = self.create_publisher(String, '/g1/wake/status', 10)

        self.stt_busy = False
        self.llm_busy = False
        self.stt_status_sub = self.create_subscription(
            String, '/g1/stt/status', self.stt_status_callback, 10)
        self.llm_status_sub = self.create_subscription(
            String, '/g1/llm/status', self.llm_status_callback, 10)

        if self.use_wake_word:
            self._init_wake_word()
            if self.oww_model is not None:
                threading.Thread(target=self._wake_word_loop, daemon=True).start()
                self.get_logger().info(f'Wake word listener started — model: {self.wake_word_model}')
            else:
                self.get_logger().warn('Wake word disabled — model failed to load')

        if self.use_select_button:
            # Use a ROS2 timer-based keyboard poller instead of raw tty
            # This works even when stdin is not a terminal (e.g. ros2 launch)
            threading.Thread(target=self._select_button_loop, daemon=True).start()
            self.get_logger().info(f'SELECT button listener started — press "{self.select_key}" + Enter to trigger')

        self.get_logger().info('Wake word node ready')

    def stt_status_callback(self, msg: String):
        self.stt_busy = msg.data in ('recording', 'transcribing')

    def llm_status_callback(self, msg: String):
        self.llm_busy = msg.data == 'thinking'

    def _can_trigger(self):
        now = time.time()
        if self.stt_busy or self.llm_busy:
            return False
        if (now - self.last_trigger_time) < self.cooldown:
            return False
        return True

    def _fire_trigger(self, source: str):
        if not self._can_trigger():
            self.get_logger().info('Trigger blocked — pipeline busy or cooldown active')
            return
        self.last_trigger_time = time.time()
        self.get_logger().info(f'Trigger fired from: {source}')
        msg = Bool()
        msg.data = True
        self.trigger_pub.publish(msg)
        status = String()
        status.data = f'triggered:{source}'
        self.status_pub.publish(status)

    def _init_wake_word(self):
        try:
            from openwakeword.model import Model
            self.oww_model = Model(
                wakeword_models=[self.wake_word_model],
                inference_framework='onnx'
            )
            self.get_logger().info('openWakeWord model loaded')
        except Exception as e:
            self.get_logger().error(f'Failed to load openWakeWord model: {e}')
            self.oww_model = None

    def _wake_word_loop(self):
        chunk_size = int(self.sample_rate * self.chunk_duration)
        audio_queue = queue.Queue()

        def audio_callback(indata, frames, time, status):
            audio_queue.put(indata.copy())

        try:
            with sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype='int16',
                blocksize=chunk_size,
                callback=audio_callback
            ):
                self.get_logger().info('Wake word mic stream open')
                while rclpy.ok():
                    if self.oww_model is None:
                        break
                    try:
                        chunk = audio_queue.get(timeout=1.0)
                        prediction = self.oww_model.predict(chunk.flatten())
                        for model_name, score in prediction.items():
                            if score >= self.detection_threshold:
                                self.get_logger().info(
                                    f'Wake word detected: "{model_name}" (score: {score:.2f})')
                                self._fire_trigger('wake_word')
                                self.oww_model.reset()
                                break
                    except queue.Empty:
                        continue
                    except Exception as e:
                        self.get_logger().error(f'Wake word prediction error: {e}')
        except Exception as e:
            self.get_logger().error(f'Wake word mic stream error: {e}')

    def _select_button_loop(self):
        """
        Reads lines from stdin. Works both in terminal and via ros2 launch.
        Press Enter (or 's' + Enter) to trigger.
        On real robot: replace this with a subscriber to the Unitree remote topic.
        """
        import sys
        self.get_logger().info(
            f'Keyboard trigger ready — press Enter (or "{self.select_key}" + Enter) in this terminal')
        try:
            for line in sys.stdin:
                line = line.strip()
                if line == '' or line == self.select_key:
                    self._fire_trigger('select_button')
        except Exception as e:
            self.get_logger().error(f'SELECT button listener error: {e}')


def main(args=None):
    rclpy.init(args=args)
    node = WakeWordNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
