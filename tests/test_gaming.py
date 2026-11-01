"""O modo jogo libera o Whisper, mantém texto e respeita a preferência de voz."""
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from gaming import game_name
from voice import Voice


class DetectionTests(unittest.TestCase):
    steam = {'SteamGameId': '1172380'}

    def test_snap_proton_game_uses_its_title(self):
        info = {'name': 'starwarsjedifal',
                'exe': '/snap/steam/common/.local/share/Steam/steamapps/common/Proton - Experimental/files/wine64-preloader',
                'cmdline': [r'S:\steamapps\common\Jedi Fallen Order\SwGame\Binaries\Win64\starwarsjedifallenorder.exe']}
        self.assertEqual(game_name(info, self.steam), 'Jedi Fallen Order')

    def test_launchers_helpers_and_runtime_do_not_keep_game_mode_on(self):
        for program in ('steam', 'steamwebhelper', 'EADesktop.exe', 'EASteamAuthHelper.exe',
                        'tabtip.exe', 'wineserver', 'pv-adverb', 'xalia.exe', 'UnityCrashHandler64.exe',
                        'd3ddriverquery64', 'fossilize_replay'):
            with self.subTest(program=program):
                self.assertIsNone(game_name({'cmdline': [program, '/steamapps/common/Game/game.exe']}, self.steam))

    def test_python_proton_wrapper_is_not_a_game(self):
        self.assertIsNone(game_name({'cmdline': ['python3', '/steamapps/common/Proton/proton', 'run', 'game.exe']}, self.steam))

    def test_native_steam_game_without_readable_environment(self):
        self.assertEqual(game_name({'exe': '/games/steamapps/common/Celeste/Celeste'}, {}), 'Celeste')

    def test_steam_runtime_path_without_game_is_ignored(self):
        self.assertIsNone(game_name({'exe': '/snap/steam/common/.local/share/Steam/steamapps/common/Proton/files/wine64-preloader'}, {}))

    def test_inherited_game_id_alone_is_not_game(self):
        self.assertIsNone(game_name({'exe': '/Steam/ubuntu12_64/helper'}, self.steam))

    def test_relative_game_executable_uses_steam_working_directory(self):
        info = {'cmdline': ['game.exe'], 'exe': '/steamapps/common/Proton/wine64-preloader',
                'cwd': '/steamapps/common/My Game/bin'}
        self.assertEqual(game_name(info, self.steam), 'My Game')

    def test_ea_helper_with_game_working_directory_is_ignored(self):
        info = {'cmdline': [r'C:\Program Files\Electronic Arts\EA Desktop\helper.exe'],
                'cwd': '/steamapps/common/Jedi Fallen Order'}
        self.assertIsNone(game_name(info, self.steam))

    def test_unrelated_python_is_not_game(self):
        self.assertIsNone(game_name({'exe': '/usr/bin/python3', 'cmdline': ['python3', 'capi_server.py']}, {}))

    def test_other_game_requires_configured_executable(self):
        self.assertIsNone(game_name({'cmdline': ['/opt/mygame/bin/game']}, {}))
        self.assertEqual(game_name({'cmdline': ['/opt/mygame/bin/game']}, {}, {'game'}), 'game')


class PolicyTests(unittest.TestCase):
    def voice(self):
        v = Voice.__new__(Voice)
        v.game_mode = False
        v.games = []
        v._stt_generation = 0
        v._stt_lock = threading.RLock()
        v._stt = Mock()
        v._stt_used = time.time()
        v.stt_idle_seconds = 60
        v.enabled = True
        v.hub = Mock()
        v.agent = Mock()
        v.voices = Mock(return_value={})
        v._synth = Mock()
        return v

    def test_game_frees_model_and_prevents_new_audio_or_warmup(self):
        v = self.voice()
        freed = threading.Event()
        torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=freed.set))
        with patch.dict(sys.modules, {'torch': torch}):
            v.set_games(['Jedi'])
            self.assertTrue(freed.wait(2))
            self.assertIsNone(v._stt)
            with patch('voice.threading.Thread') as spawn:
                self.assertFalse(v.hear(b'audio'))
                v.warm()
                spawn.assert_not_called()
            self.assertIsNone(v._load_stt())
        self.assertTrue(v.enabled)

    def test_reply_uses_text_without_synthesis_while_gaming(self):
        v = self.voice()
        v.game_mode = True
        v.say('Tudo pronto!', 'reply')
        v._synth.assert_not_called()
        v.hub.broadcast.assert_called_once_with('reply', {'text': 'Tudo pronto!', 'kind': 'reply'})

    def test_pending_audio_is_discarded_after_game_transition(self):
        v = self.voice()
        v._unload_stt = Mock()
        old_generation = v._stt_generation
        v.set_games(['Game'])
        v.set_games([])
        v._hear(b'old audio', generation=old_generation)
        v._stt.transcribe.assert_not_called()
        v.agent.log.assert_not_called()

    def test_removing_one_of_two_games_does_not_restore_voice(self):
        v = self.voice()
        v._unload_stt = Mock()
        v.enabled = False
        v.set_games(['A', 'B'])
        v.set_games(['B'])
        self.assertTrue(v.game_mode)
        v.set_games([])
        self.assertFalse(v.game_mode)
        self.assertFalse(v.enabled)  # não liga avisos que o usuário havia desligado

    def test_inflight_transcription_finishes_before_unload_and_cannot_act(self):
        v = self.voice()
        entered, finish, freed = threading.Event(), threading.Event(), threading.Event()
        model = v._stt
        def transcribe(*args, **kwargs):
            entered.set()
            self.assertTrue(finish.wait(2))
            return {'text': 'Guará abra alguma coisa'}
        model.transcribe.side_effect = transcribe
        torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=freed.set))
        with patch.dict(sys.modules, {'torch': torch}):
            t = threading.Thread(target=v._hear, args=(b'audio',))
            t.start()
            self.assertTrue(entered.wait(2))
            v.set_games(['Game'])
            self.assertTrue(v.game_mode)
            self.assertFalse(freed.is_set())
            finish.set()
            t.join(2)
            self.assertFalse(t.is_alive())
            self.assertTrue(freed.wait(2))
        self.assertIsNone(v._stt)
        v.agent.log.assert_not_called()

    def test_idle_releases_at_one_minute_and_reloads_on_demand(self):
        v = self.voice()
        with patch('voice.time.time', return_value=v._stt_used + 59):
            self.assertFalse(v._unload_if_idle())
        torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=Mock()))
        whisper = SimpleNamespace(load_model=Mock(return_value=Mock()))
        with patch.dict(sys.modules, {'torch': torch, 'whisper': whisper}):
            with patch('voice.time.time', return_value=v._stt_used + 60):
                self.assertTrue(v._unload_if_idle())
            self.assertIsNone(v._stt)
            whisper.load_model.assert_not_called()
            v._load_stt()
            whisper.load_model.assert_called_once()
            self.assertIsNotNone(v._stt)


if __name__ == '__main__':
    unittest.main()
