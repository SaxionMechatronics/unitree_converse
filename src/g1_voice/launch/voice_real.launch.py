from launch import LaunchDescription
from launch_ros.actions import Node
from launch.actions import LogInfo
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():

    pkg_share = get_package_share_directory('g1_voice')
    params_file = os.path.join(pkg_share, 'config', 'voice_params_real.yaml')

    return LaunchDescription([

        LogInfo(msg='Starting G1 voice pipeline (real robot)...'),

        Node(
            package='g1_voice',
            executable='wake_word_node',
            name='wake_word_node',
            output='screen',
            parameters=[params_file],
        ),

        Node(
            package='g1_voice',
            executable='stt_node',
            name='stt_node',
            output='screen',
            parameters=[params_file],
        ),

        Node(
            package='bob_llm',
            executable='llm_node.py',
            name='llm_node',
            output='screen',
            parameters=[params_file],
            remappings=[
                ('llm_prompt', '/g1/stt/transcript'),
            ],
        ),

        Node(
            package='g1_voice',
            executable='tts_node',
            name='tts_node',
            output='screen',
            parameters=[params_file],
        ),
	    Node(
    	    package='g1_voice',
    	    executable='button_trigger_node',
    	    name='button_trigger_node',
    	    output='screen',
    	    parameters=[params_file],
	    ),
        Node(
            package='g1_voice',
            executable='robot_state_node',
            name='robot_state_node',
            output='screen',
            parameters=[params_file],
        ),
    ])
