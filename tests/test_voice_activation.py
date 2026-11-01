import sys
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from voice import Voice, after_wake_word, reliable_speech


def result(text, **metrics):
    return {'text': text, 'segments': [{'text': text, 'no_speech_prob': 0.05,
            'avg_logprob': -0.2, 'compression_ratio': 1.1, **metrics}]}


class VoiceActivationTests(unittest.TestCase):
    def hear(self, data, wake=False, cancel_during_transcription=False):
        voice = Voice.__new__(Voice)
        voice.game_mode = False
        voice._stt_generation = 0
        voice._capture_generation = 0
        voice.handsfree_enabled = wake
        voice._stt_lock = threading.RLock()
        voice._stt = Mock()
        voice._stt.transcribe.return_value = data
        if cancel_during_transcription:
            def transcribe(*args, **kwargs):
                voice.cancel_listening()
                return data
            voice._stt.transcribe.side_effect = transcribe
        voice._load_stt = Mock()
        voice.hub = Mock()
        voice.agent = Mock()
        voice.say = Mock()
        voice.converse = Mock()
        voice._hear(b'fixture audio', wake=wake)
        return voice

    def test_silence_and_unreliable_transcriptions_never_start_a_request_or_speak(self):
        for data in ({'text': '', 'segments': []},
                     result('Guará abre o navegador', no_speech_prob=0.95),
                     result('abre o navegador', avg_logprob=-2),
                     result('abre o navegador', compression_ratio=3)):
            for wake in (False, True):
                with self.subTest(data=data, wake=wake):
                    voice = self.hear(data, wake)
                    voice.converse.assert_not_called()
                    voice.say.assert_not_called()
                    if wake:
                        voice.hub.broadcast.assert_not_called()
                    else:
                        self.assertEqual(voice.hub.broadcast.call_args.args,
                                         ('heard', {'state': 'vazio'}))

    def test_real_manual_request_still_works(self):
        voice = self.hear(result('qual é a hora'))
        voice.converse.assert_called_once_with('qual é a hora')

    def test_disabling_capture_discards_audio_already_being_transcribed(self):
        for wake in (True, False):
            voice = self.hear(result('Guará abre o navegador'), wake,
                              cancel_during_transcription=True)
            voice.converse.assert_not_called()
            voice.say.assert_not_called()
            for call in voice.hub.broadcast.call_args_list:
                self.assertNotEqual(call.args[0], 'wake')
                self.assertNotEqual(call.args, ('heard', {'state': 'ok', 'text': 'Guará abre o navegador'}))

    def test_manual_mode_rejects_background_audio_before_starting_transcription(self):
        voice = Voice.__new__(Voice)
        voice.game_mode = False
        voice.handsfree_enabled = False
        with patch('voice.threading.Thread') as spawn:
            self.assertFalse(voice.hear(b'audio', wake=True))
            spawn.assert_not_called()

    def test_handsfree_requires_a_direct_call(self):
        for text in ('falei com Guará ontem', 'não Guará isso não', 'qual é a hora'):
            self.assertIsNone(after_wake_word(text))
            self.hear(result(text), wake=True).converse.assert_not_called()
        voice = self.hear(result('Ei Guará, qual é a hora'), wake=True)
        voice.converse.assert_called_once_with('qual é a hora')

    def test_name_only_wakes_without_creating_a_request(self):
        voice = self.hear(result('Guará'), wake=True)
        voice.converse.assert_not_called()
        voice.hub.broadcast.assert_called_once_with('wake', {})

    def test_manual_name_only_also_waits_for_the_actual_request(self):
        voice = self.hear(result('Guará'))
        voice.converse.assert_not_called()
        self.assertEqual(voice.hub.broadcast.call_args.args, ('wake', {}))

    def test_manual_audio_allows_confident_speech_with_some_background_noise(self):
        self.assertTrue(reliable_speech(result('qual é a hora', no_speech_prob=0.7), wake=False))
        self.assertFalse(reliable_speech(result('qual é a hora', no_speech_prob=0.7), wake=True))

    def test_conversation_survives_server_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = Voice.__new__(Voice)
            first.session_path = Path(tmp)/'voice-session.local.json'
            first.history = [(time.time(), 'Meu projeto é o Guará.', 'Entendi.')]
            first.conversation = {'engine': 'codex', 'id': 'test-session'}
            first.conversation_at = time.time()
            first._save_conversation()
            second = Voice.__new__(Voice)
            second.session_path = first.session_path
            second.config = {}
            second.history = []
            second.conversation = None
            second._restore_conversation()
            self.assertEqual(second.history[0][1], 'Meu projeto é o Guará.')
            self.assertEqual(second.conversation, first.conversation)
            self.assertEqual(first.session_path.stat().st_mode & 0o777, 0o600)

    def test_stale_or_queued_handsfree_audio_is_dropped(self):
        voice = Voice.__new__(Voice)
        voice.game_mode, voice._stt_generation, voice._capture_generation = False, 0, 0
        voice.handsfree_enabled = True
        voice._stt_lock = threading.RLock()
        voice._queue_lock = threading.Lock()
        voice._stt = Mock()
        voice._load_stt = Mock()
        voice.hub, voice.agent, voice.converse = Mock(), Mock(), Mock()
        voice._manual_waiting = 0
        voice._hear(b'old', wake=True, arrived=time.time() - 30)
        voice._manual_waiting = 1
        voice._hear(b'queued', wake=True, arrived=time.time())
        voice._stt.transcribe.assert_not_called()

    def test_manual_audio_leaves_the_queue_once(self):
        voice = self.hear(result('Que horas são agora?'))
        voice._queue_lock = threading.Lock()
        voice._manual_waiting = 1
        voice._hear(b'audio', wake=False, arrived=time.time())
        self.assertEqual(voice._manual_waiting, 0)

    def test_answer_to_a_question_uses_the_strict_filter(self):
        noisy = result('e aí falou que vai chover', no_speech_prob=0.7, avg_logprob=-0.5)
        voice = Voice.__new__(Voice)
        voice.game_mode, voice._stt_generation, voice._capture_generation = False, 0, 0
        voice.handsfree_enabled = False
        voice._stt_lock = threading.RLock()
        voice._stt = Mock()
        voice._stt.transcribe.return_value = noisy
        voice._load_stt = Mock()
        voice.hub, voice.agent, voice.converse = Mock(), Mock(), Mock()
        voice.followup_until = time.time() + 10
        voice._hear(b'eco', wake=False)
        voice.converse.assert_not_called()
        self.assertEqual(voice.followup_until, 0.0)
        voice._hear(b'mesmo audio, sem pergunta pendente', wake=False)
        voice.converse.assert_called_once()

    def test_missing_confidence_is_not_treated_as_reliable(self):
        self.assertFalse(reliable_speech({'segments': [{}]}))

    def test_one_good_segment_does_not_validate_a_hallucinated_command(self):
        data = result('Guará')
        data['segments'] += result('abre o navegador', avg_logprob=-2)['segments']
        self.assertFalse(reliable_speech(data))


if __name__ == '__main__':
    unittest.main()
