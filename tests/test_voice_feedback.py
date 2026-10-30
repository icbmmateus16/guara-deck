"""A espera deve aparecer antes da resposta e nunca interrompê-la depois."""
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from agent import Agent
from voice import Voice, _pcm_to_wav


class FeedbackTests(unittest.TestCase):
    def voice(self):
        voice = Voice.__new__(Voice)
        mission = {'id': 'demo', 'status': 'running'}
        voice.agent = SimpleNamespace(mission=mission)
        voice.hub = Mock()
        voice.enabled = True
        voice.voice_id = 'demo'
        voice._ack_cache = {}
        voice._ack_lock = threading.Lock()
        voice.clips = {}
        voice._synth = Mock(return_value=_pcm_to_wav(b'\x00\x00' * 2400))
        return voice, mission

    def test_cached_audio_does_not_wait_for_synthesis_again(self):
        voice, mission = self.voice()
        voice._acknowledge(mission, 'Deixa eu conferir.')
        voice._acknowledge(mission, 'Deixa eu conferir.')
        self.assertEqual(voice._synth.call_count, 1)
        self.assertEqual(voice.hub.broadcast.call_count, 2)

    def test_reply_finishing_during_synthesis_suppresses_late_ack(self):
        voice, mission = self.voice()
        def synth(text):
            mission['status'] = 'done'
            return _pcm_to_wav(b'\x00\x00' * 2400)
        voice._synth = synth
        voice._acknowledge(mission, 'Deixa eu conferir.')
        voice.hub.broadcast.assert_not_called()

    def test_replaced_request_cannot_play_old_ack(self):
        voice, old = self.voice()
        voice.agent.mission = {'id': 'new', 'status': 'running'}
        voice._acknowledge(old, 'Deixa eu conferir.')
        voice.hub.broadcast.assert_not_called()

    def test_synthesis_failure_keeps_text_feedback_available(self):
        voice, mission = self.voice()
        voice._synth.side_effect = RuntimeError('offline')
        voice._acknowledge(mission, 'Deixa eu conferir.')
        voice.hub.broadcast.assert_not_called()

    def test_even_fast_reply_starts_after_feedback(self):
        agent = Agent.__new__(Agent)
        agent.lock = threading.Lock()
        agent.config = {}
        agent.mission = None
        seen = []
        agent.voice = SimpleNamespace(on_mission_start=lambda m: seen.append('feedback'))
        agent._mission_publish = lambda: None
        def reply(m, spec):
            self.assertEqual(seen, ['feedback'])
            m['status'] = 'done'
        agent._mission_run = reply
        class ImmediateThread:
            def __init__(self, target, args, **kwargs):
                self.target, self.args = target, args
            def start(self):
                self.target(*self.args)
        with patch('agent.threading.Thread', ImmediateThread):
            ok, _ = agent.mission_start('Oi', voice=True)
        self.assertTrue(ok)
        self.assertEqual(agent.mission['status'], 'done')


if __name__ == '__main__':
    unittest.main()
