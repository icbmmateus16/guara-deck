import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'server'))
import pc


class AppsTests(unittest.TestCase):
    def test_usage_file_is_sorted_and_filters_unavailable_apps(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'.local/share/gnome-shell/application_state'
            path.parent.mkdir(parents=True)
            path.write_text('<application-state><context><application id="code.desktop" score="10"/>'
                            '<application id="firefox.desktop" score="50"/>'
                            '<application id="gone.desktop" score="99"/></context></application-state>')
            with patch.object(pc.Path, 'home', return_value=Path(tmp)), \
                 patch.object(pc, 'desktop_entry', side_effect=lambda key: None if key=='gone' else {'name':key}):
                self.assertEqual(pc.frequent_ids(), ['firefox', 'code'])

    def test_union_of_frequent_and_pinned_apps_has_no_duplicates(self):
        with patch.object(pc, 'frequent_ids', return_value=['firefox', 'code']), \
             patch.object(pc, 'favorite_ids', return_value=['code', 'files']), \
             patch.object(pc, 'desktop_entry', side_effect=lambda key: {'name':key}):
            items=pc.apps_catalog([])
        self.assertEqual([app['id'] for app in items], ['firefox','code','files'])

    def test_frequent_app_can_open_even_if_not_pinned(self):
        with patch.object(pc, 'frequent_ids', return_value=['frequent']), \
             patch.object(pc, 'favorite_ids', return_value=[]), \
             patch.object(pc, 'find_desktop', return_value=Path('/apps/frequent.desktop')), \
             patch.object(pc, '_spawn') as spawn:
            self.assertTrue(pc.launch_app('frequent')[0])
            spawn.assert_called_once_with(['gio','launch','/apps/frequent.desktop'])
            self.assertFalse(pc.launch_app('unlisted')[0])


if __name__=='__main__': unittest.main()
