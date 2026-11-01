import time
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

import voice as voice_mod


class DummyHub:
    def __init__(self):
        self.events = []

    def broadcast(self, ev, data):
        self.events.append((ev, data))


class DummyAgent:
    def __init__(self):
        self.summarized_prompts = []
        self.logs = []

    def log(self, kind, text):
        self.logs.append((kind, text))

    def summarize_safe(self, prompt: str) -> str:
        self.summarized_prompts.append(prompt)
        return "No grupo Família falaram sobre o churrasco de domingo e quem vai levar carne."


class FakeWhatsApp:
    def __init__(self):
        self.sent = []
        self.read_calls = []

    def find(self, query):
        if query.lower() == "desconhecido":
            return None
        if query.lower() in ("amor", "esposa"):
            return "Amor"
        return query

    def unread_categorized(self):
        return {
            "people": [("Amor", 3), ("João", 1)],
            "groups": [("Família", 42)],
        }

    def read_new(self, title, n=6, only_new=True, transcribe=None):
        self.read_calls.append(("read_new", title, n, only_new))
        if title == "Família":
            return (
                [
                    ("Tio Zé", "Bora fazer churrasco domingo", False),
                    ("Prima Ana", "[áudio: Eu levo pão de alho]", False),
                ],
                False,
            )
        return (
            [
                ("", "[áudio: passa no mercado e compra pão]", False),
                ("", "e traz leite também", False),
            ],
            False,
        )

    def send(self, to, body):
        self.sent.append((to, body))
        return True


class TestWhatsAppFeatures(unittest.TestCase):
    def setUp(self):
        self.hub = DummyHub()
        self.cfg = {
            "voice": "edge:guara-desenho",
            "whatsapp_aliases": {"esposa": "Amor"},
            "whatsapp_vip": ["Amor"],
        }
        self.agent = DummyAgent()
        with patch.object(voice_mod.Voice, "_warm_voices", lambda self: None), \
             patch.object(voice_mod.Voice, "_unload_idle", lambda self: None):
            self.v = voice_mod.Voice(self.hub, self.agent, self.cfg)
        self.fake_wa = FakeWhatsApp()
        self.v.wa = self.fake_wa
        self.spoken = []
        self.v.say = lambda text, kind="reply", limit=440, ask=False: self.spoken.append((text, kind)) or text
        self.v.say_async = lambda text, kind="reply": self.spoken.append((text, kind))
        self.v._save_config_key = lambda k, val: self.cfg.__setitem__(k, val)

    def test_1_and_2_audio_format_and_read_new(self):
        self.v._wa_action("Deixa eu ver.", "WHATSAPP_LER", "esposa")
        self.assertTrue(self.spoken)
        reply = self.spoken[-1][0]
        self.assertIn("2 mensagens de Amor", reply)
        self.assertIn("Amor mandou um áudio: 'passa no mercado e compra pão'", reply)
        self.assertIn("Amor: e traz leite também", reply)
        self.assertEqual(self.v.wa_last_chat, "Amor")

    def test_3_unread_categorized_people_first_groups_second_skip_muted(self):
        self.v._wa_action("Vou olhar.", "WHATSAPP_NOVAS", "")
        reply = self.spoken[-1][0]
        self.assertIn("Tem mensagem de Amor (3) e João", reply)
        self.assertIn("E nos grupos: Família (42)", reply)
        self.assertLess(reply.index("Tem mensagem de Amor"), reply.index("E nos grupos"))

    def test_4_and_5_reply_last_chat_and_tablet_confirm_buttons(self):
        self.v.wa_last_chat = "Amor"
        self.v._wa_action("", "WHATSAPP_ENVIAR", "RESPONDER | tudo bem, já estou indo")
        reply = self.spoken[-1][0]
        self.assertIn("Vou mandar para Amor: tudo bem, já estou indo", reply)
        self.assertIsNotNone(self.v.wa_pending)
        self.assertEqual(self.v.wa_pending["title"], "Amor")
        confirm_evs = [d for ev, d in self.hub.events if ev == "wa_confirm" and d]
        self.assertTrue(confirm_evs)

        ok = self.v.wa_decide(True)
        self.assertTrue(ok)
        self.assertIsNone(self.v.wa_pending)
        time.sleep(0.05)
        self.assertEqual(self.fake_wa.sent, [("Amor", "tudo bem, já estou indo")])

    def test_6_vip_notification(self):
        self.v._on_vip_message("Amor", 2)
        self.assertEqual(len(self.spoken), 1)
        self.assertIn("chegou mensagem de Amor no WhatsApp", self.spoken[0][0])

    def test_7_safe_group_summary(self):
        self.v._wa_action("", "WHATSAPP_RESUMO", "Família")
        reply = self.spoken[-1][0]
        self.assertIn("churrasco de domingo", reply)
        self.assertEqual(len(self.agent.summarized_prompts), 1)
        self.assertIn("Prima Ana mandou um áudio: 'Eu levo pão de alho'", self.agent.summarized_prompts[0])

    def test_8_learn_alias_automatically_and_retry(self):
        self.v._wa_action("", "WHATSAPP_LER", "desconhecido")
        self.assertIn("Como está salvo o nome nos contatos?", self.spoken[-1][0])
        self.assertIsNotNone(self.v.wa_failed_lookup)

        matched = self.v._try_direct_alias_learn("o nome dela está como Amor")
        self.assertTrue(matched)
        time.sleep(0.05)
        self.assertEqual(self.cfg["whatsapp_aliases"].get("desconhecido"), "Amor")
        self.assertTrue(any("2 mensagens de Amor" in s[0] for s in self.spoken))

    def test_9_vip_names_and_keywords(self):
        from whatsapp import vip_match
        names, keywords = ["Amor", "Mae❤️", "Pai ♥️", "Lucas Irmão", "Eduardo V."], ["senac"]
        self.assertTrue(vip_match("Amor❤️", names, keywords))
        self.assertTrue(vip_match("Mae❤️", names, keywords))
        self.assertTrue(vip_match("Pai ♥️", names, keywords))
        self.assertTrue(vip_match("Lucas Irmão", names, keywords))
        self.assertTrue(vip_match("Eduardo V.", names, keywords))
        self.assertTrue(vip_match("Instrutores(as) T.I. Senac/GO👨🏻‍💻", names, keywords))
        self.assertFalse(vip_match("Mãe Armando", names, keywords))
        self.assertFalse(vip_match("Pai Numero 2", names, keywords))
        self.assertFalse(vip_match("Lucas", names, keywords))

    def test_9b_search_prefers_the_exact_contact(self):
        from whatsapp import WhatsApp
        titles = ["Karla Mãe IA", "Mãe Matheus Face", "Mae❤️", "Mãe Armando"]
        self.assertEqual(WhatsApp._best_match(titles, "Mãe"), "Mae❤️")
        self.assertEqual(WhatsApp._best_match(["Sampaio", "Pai Numero 2", "Pai ♥️"], "pai"), "Pai ♥️")
        self.assertEqual(WhatsApp._best_match(["Eduardo Pimentel", "Eduardo V."], "Eduardo V"), "Eduardo V.")

    def test_10_question_replies_open_the_microphone(self):
        v = self.v
        v.say = voice_mod.Voice.say.__get__(v)
        v.enabled, v.game_mode, v.clips = True, False, {}
        v._synth = lambda text: b"wav"
        with patch.object(voice_mod, "envelope", lambda data: ([1, 2], 1.5)):
            v.answer("Vou mandar para Amor: oi. Posso mandar?")
            v.answer("Mandei para Amor!")
            v.say("Gostou da voz?", "reply")
        says = [d for ev, d in self.hub.events if ev == "say"]
        self.assertEqual([d["ask"] for d in says], [True, False, False])
        self.assertGreater(v.followup_until, time.time())

    def test_11_request_hint_lists_aliases_and_apps(self):
        captured = {}
        self.agent.engines = lambda: ["codex"]
        self.agent.mission_start = lambda text, *a, **k: captured.setdefault("text", text) and (True, "ok")
        self.v._apps_cache = (time.time(), "Firefox, VS Code, Steam")
        self.v.converse("manda mensagem pra minha esposa")
        self.assertIn("esposa = Amor", captured["text"])
        self.assertIn("apps do PC: Firefox, VS Code, Steam", captured["text"])


if __name__ == "__main__":
    unittest.main()
