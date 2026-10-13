"""Offline Start setup tests; no desktop or hardware is touched."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from driver import Driver


def e(index, role, label='', parent=None, enabled=True):
    return {'element_index': index, 'role': role, 'label': label,
            'parent_index': parent, 'enabled': enabled}


def card_page():
    return [e(1, 'section'), e(2, 'paragraph', 'Water', 1),
            e(3, 'paragraph', 'Instruments', 1), e(4, 'section', parent=1),
            e(5, 'push button', parent=4)]


class StartSetupTests(unittest.TestCase):
    def make_driver(self):
        d = object.__new__(Driver)
        d.list_protocols = Mock(return_value={'protocols': [{'name': 'Water'}]})
        # Proceed may remain disabled until a robot is selected; that's still open.
        d.capture_screenshot = Mock(side_effect=[{'elements': card_page()},
            {'elements': [e(8, 'push button', 'Proceed to setup', enabled=False)]}])
        d._validate_element_position = Mock()
        d._cua = SimpleNamespace(click=Mock(return_value='click'))
        d._run = Mock()
        d.click_element = Mock()
        d.wait_for_element = Mock(return_value=e(7, 'push button', 'Start setup'))
        return d

    def test_opens_scoped_menu_then_stops_at_robot_selection(self):
        d = self.make_driver()
        self.assertEqual(d.start_setup('Water'), {'protocol_name': 'Water', 'setup_open': True})
        d._cua.click.assert_called_once_with(element=5)
        d.click_element.assert_called_once_with('Start setup')
        d.wait_for_element.assert_called_once_with('Start setup', timeout=10.0)

    def test_duplicate_name_is_rejected_before_menu_input(self):
        d = self.make_driver()
        d.list_protocols.return_value = {'protocols': [{'name': 'Water'}, {'name': 'Water'}]}
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous protocol name'):
            d.start_setup('Water')
        d._cua.click.assert_not_called()

    def test_missing_and_case_mismatched_name_are_rejected(self):
        d = self.make_driver()
        with self.assertRaisesRegex(RuntimeError, 'No protocol named'):
            d.start_setup('water')
        d._cua.click.assert_not_called()

    def test_empty_name_is_rejected_before_navigation(self):
        d = self.make_driver()
        with self.assertRaises(ValueError):
            d.start_setup(' ')
        d.list_protocols.assert_not_called()

    def test_ambiguous_overflow_button_is_rejected(self):
        d = self.make_driver()
        d.capture_screenshot.side_effect = [{'elements': card_page() + [e(6, 'push button', parent=1)]}]
        with self.assertRaisesRegex(RuntimeError, 'overflow button'):
            d.start_setup('Water')
        d._cua.click.assert_not_called()

    def test_offscreen_card_does_not_dispatch_menu_input(self):
        d = self.make_driver()
        d._validate_element_position.side_effect = RuntimeError('outside the captured window')
        with self.assertRaisesRegex(RuntimeError, 'outside'):
            d.start_setup('Water')
        d._cua.click.assert_not_called()

    def test_completion_timeout_does_not_repeat_actions(self):
        from unittest.mock import patch
        d = self.make_driver()
        d.capture_screenshot.side_effect = [{'elements': card_page()}, {'elements': []}]
        with patch('time.monotonic', side_effect=[0.0, 11.0]):
            with self.assertRaisesRegex(TimeoutError, 'not verified'):
                d.start_setup('Water')
        d._cua.click.assert_called_once()
        d.click_element.assert_called_once_with('Start setup')
