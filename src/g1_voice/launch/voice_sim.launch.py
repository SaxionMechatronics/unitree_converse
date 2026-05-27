from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import LogInfo
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():

    pkg_share = get_package_share_directory('g1_voice')
    params_file = os.path.join(pkg_share, 'config', 'voice_params.yaml')

    return LaunchDescription([

        LogInfo(msg='Starting G1 voice pipeline (sim mode)...'),

        # Wake word + SELECT button trigger
        Node(
            package='g1_voice',
            executable='wake_word_node',
            name='wake_word_node',
            output='screen',
            parameters=[params_file],
        ),

        # Speech to text
        Node(
            package='g1_voice',
            executable='stt_node',
            name='stt_node',
            output='screen',
            parameters=[params_file],
        ),

        # LLM — using bob_llm
        # llm_prompt  ← stt_node publishes transcript here
        # llm_response → tts_node subscribes here
        Node(
            package='bob_llm',
            executable='llm',
            name='llm_node',
            output='screen',
            parameters=[params_file],
            remappings=[
                ('llm_prompt', '/g1/stt/transcript'),
            ],
        ),

        # Text to speech
        Node(
            package='g1_voice',
            executable='tts_node',
            name='tts_node',
            output='screen',
            parameters=[params_file],
        ),

    ])
