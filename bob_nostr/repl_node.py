# Copyright 2026 Bob Ros
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import io
import json
import sys
import threading
import traceback

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class ReplNode(Node):
    """
    Hardened Python REPL node for the Agent.

    Includes execution timeouts and isolated namespace management.
    """

    def __init__(self):
        super().__init__('repl_node')
        self._locals = {
            'node': self,
            'rclpy': rclpy,
            'json': json,
            'sys': sys,
            'os': __import__('os'),
            'time': __import__('time'),
            'math': __import__('math')
        }

        self.sub_input = self.create_subscription(
            String, 'repl/input', self.input_callback, 10)
        self.pub_output = self.create_publisher(
            String, 'repl/output', 10)
        self.pub_status = self.create_publisher(
            String, 'repl/status', 10)

        self._start_time = __import__('time').time()
        self.timer_status = self.create_timer(5.0, self.publish_status)

        self.get_logger().info('Agent REPL Node active and hardened.')

    def publish_status(self):
        """Publish REPL session metadata."""
        status = {
            'start_time': self._start_time,
            'locals_count': len(self._locals)
        }
        msg = String()
        msg.data = json.dumps(status)
        self.pub_status.publish(msg)

    def input_callback(self, msg):
        """Execute code with a timeout safety net."""
        code = msg.data
        result_container = [None]

        def run_target():
            if code == '__RESET__':
                self._locals = {
                    'node': self,
                    'rclpy': rclpy,
                    'json': json,
                    'sys': sys,
                    'os': __import__('os'),
                    'time': __import__('time'),
                    'math': __import__('math')
                }
                result_container[0] = 'REPL namespace has been reset.'
            elif code == '__HISTORY__':
                keys = sorted([k for k in self._locals.keys() if not k.startswith('_')])
                result_container[0] = 'REPL HISTORY: ' + ', '.join(keys)
            else:
                result_container[0] = self.execute_code(code)

        thread = threading.Thread(target=run_target)
        thread.start()
        thread.join(timeout=15.0)  # Maximum execution time per block

        if thread.is_alive():
            result = ('Error: Execution Timeout (15s). '
                      'The process is still running in the background.')
        else:
            result = result_container[0]

        out_msg = String()
        out_msg.data = str(result)
        self.pub_output.publish(out_msg)

    def execute_code(self, code):
        """Execute and capture output."""
        stdout = io.StringIO()
        stderr = io.StringIO()
        old_stdout, old_stderr = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = stdout, stderr

        try:
            exec(code, {}, self._locals)
            res = stdout.getvalue() + stderr.getvalue()
            return res if res else '[Success: No output]'
        except Exception:
            return traceback.format_exc()
        finally:
            sys.stdout, sys.stderr = old_stdout, old_stderr


def main(args=None):
    """Start the REPL node."""
    rclpy.init(args=args)
    node = ReplNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
