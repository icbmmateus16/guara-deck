import sys
import threading
import time
import unittest
from pathlib import Path
import unittest.mock
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
from agent import Agent  # noqa: E402

QUESTION = {'questions': [{'question': 'Qual cor?', 'header': 'Cor', 'multiSelect': False,
                           'options': [{'label': 'Azul', 'description': 'frio'}, {'label': 'Verde'}]}]}


def agent():
    a = Agent.__new__(Agent)
    a.lock = threading.RLock()
    a.permissions = {}
    a.sessions = {}
    a.hub = Mock()
    a.hub.has_clients.return_value = True
    a.voice = None
    a.config = {'permission_timeout': 5}
    a.publish = Mock()
    a.log = Mock()
    a.pc_idle_ms = 0
    return a


def ask(a, tool, tool_input, session='s1'):
    out = {}
    ev = {'session_id': session, 'tool_name': tool, 'tool_input': tool_input, 'cwd': '/x/TABLET CONTROL'}
    with unittest.mock.patch('agent._peer_closed', return_value=False):
        t = threading.Thread(target=lambda: out.update(r=a.permission_request(ev, None)))
        t.start()
        for _ in range(100):
            if a.permissions:
                break
            time.sleep(0.01)
    return t, out


class PermissionTests(unittest.TestCase):
    def test_question_answered_on_the_tablet_goes_back_as_answers(self):
        a = agent()
        t, out = ask(a, 'AskUserQuestion', QUESTION)
        pid = next(iter(a.permissions))
        view = a._perm_view(a.permissions[pid], time.time())
        self.assertEqual([o['label'] for o in view['questions'][0]['options']], ['Azul', 'Verde'])
        self.assertFalse(a.permission_decide(pid, 'allow', {'Qual cor?': ['Roxo']}))   # opção inexistente
        self.assertTrue(a.permission_decide(pid, 'allow', {'Qual cor?': ['Verde']}))
        t.join(2)
        decision = out['r']['hookSpecificOutput']['decision']
        self.assertEqual(decision['behavior'], 'allow')
        self.assertEqual(decision['updatedInput']['answers'], {'Qual cor?': 'Verde'})
        self.assertEqual(decision['updatedInput']['questions'], QUESTION['questions'])

    def test_answering_on_the_pc_clears_the_tablet_right_away(self):
        a = agent()
        t, out = ask(a, 'AskUserQuestion', QUESTION)
        a._answered_elsewhere('s1', 'PostToolUse',
                              {'tool_name': 'AskUserQuestion', 'tool_input': {**QUESTION, 'answers': {'Qual cor?': 'Azul'}}})
        t.join(2)
        self.assertFalse(t.is_alive())
        self.assertEqual(out['r'], {})            # sem decisão: o Claude Code já seguiu com a resposta do PC
        self.assertEqual(a.permissions, {})

    def test_other_sessions_and_other_calls_do_not_clear_the_request(self):
        a = agent()
        t, _ = ask(a, 'Bash', {'command': 'ls'})
        a._answered_elsewhere('outra', 'PostToolUse', {'tool_name': 'Bash', 'tool_input': {'command': 'ls'}})
        a._answered_elsewhere('s1', 'PostToolUse', {'tool_name': 'Bash', 'tool_input': {'command': 'pwd'}})
        self.assertEqual(len(a.permissions), 1)
        a._answered_elsewhere('s1', 'UserPromptSubmit', {})
        t.join(2)
        self.assertEqual(a.permissions, {})


if __name__ == '__main__':
    unittest.main()
