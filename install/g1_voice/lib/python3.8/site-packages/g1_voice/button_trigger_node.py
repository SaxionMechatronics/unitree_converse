import rclpy
from rclpy.node import Node
from std_msgs.msg import Bool, String
import threading
import time

F1_KEY = 64
F3_KEY = 128

DEBOUNCE_TIME = 0.5  # seconds — ignore repeated F3 presses within this window


class ButtonTriggerNode(Node):
    def __init__(self):
        super().__init__('button_trigger_node')

        self.continuous_mode = False
        self.f1_pressed = False
        self.f3_pressed = False
        self.recording_active = False
        self.prev_keys = 0
        self.last_f3_time = 0.0  # for debouncing

        # Publishers
        self.trigger_pub = self.create_publisher(Bool, '/g1/voice/trigger', 10)
        self.stop_pub = self.create_publisher(Bool, '/g1/voice/stop_recording', 10)
        self.continuous_start_pub = self.create_publisher(Bool, '/g1/voice/continuous_start', 10)
        self.continuous_stop_pub = self.create_publisher(Bool, '/g1/voice/continuous_stop', 10)
        self.status_pub = self.create_publisher(String, '/g1/button/status', 10)

        from unitree_go.msg import WirelessController
        self.controller_sub = self.create_subscription(
            WirelessController,
            '/wirelesscontroller',
            self.controller_callback,
            10
        )

        self.get_logger().info('Button trigger node ready')
        self.get_logger().info('Hold F1 → push-to-talk (release to send)')
        self.get_logger().info('F3 → toggle continuous mode on/off')

    def controller_callback(self, msg):
        keys = msg.keys
        prev = self.prev_keys
        self.prev_keys = keys

        f1_now = bool(keys & F1_KEY)
        f3_now = bool(keys & F3_KEY)
        f1_prev = bool(prev & F1_KEY)
        f3_prev = bool(prev & F3_KEY)

        self.f1_pressed = f1_now
        self.f3_pressed = f3_now

        # F3 rising edge with debounce → toggle continuous mode
        if f3_now and not f3_prev:
            now = time.time()
            if now - self.last_f3_time > DEBOUNCE_TIME:
                self.last_f3_time = now
                threading.Thread(target=self._toggle_continuous, daemon=True).start()
            return

        # F1 pressed (rising edge) → start recording, only in push-to-talk mode
        if f1_now and not f1_prev and not self.continuous_mode:
            self.get_logger().info('F1 held → start recording')
            self.recording_active = True
            self._publish_trigger(True)
            self._publish_status('recording')

        # F1 released (falling edge) → stop recording
        if not f1_now and f1_prev and self.recording_active:
            self.get_logger().info('F1 released → stop recording, transcribing...')
            self.recording_active = False
            self._publish_stop()
            self._publish_status('transcribing')

    def _toggle_continuous(self):
        if self.continuous_mode:
            self.continuous_mode = False
            msg = Bool()
            msg.data = True
            self.continuous_stop_pub.publish(msg)
            self.get_logger().info('Continuous mode OFF')
            self._publish_status('continuous_off')
        else:
            self.continuous_mode = True
            msg = Bool()
            msg.data = True
            self.continuous_start_pub.publish(msg)
            self.get_logger().info('Continuous mode ON')
            self._publish_status('continuous_on')
            # Small delay then fire first trigger
            time.sleep(0.5)
            self._publish_trigger(True)

    def _publish_trigger(self, value: bool):
        msg = Bool()
        msg.data = value
        self.trigger_pub.publish(msg)

    def _publish_stop(self):
        msg = Bool()
        msg.data = True
        self.stop_pub.publish(msg)

    def _publish_status(self, status: str):
        msg = String()
        msg.data = status
        self.status_pub.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = ButtonTriggerNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()