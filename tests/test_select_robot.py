"""Offline robot-choice tests; no robot setup is advanced."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from driver import Driver


def element(index, role, label='', parent=None, **extra):
    return dict(element_index=index, role=role, label=label, parent_index=parent,
                enabled=True, **extra)


def robot_page(names=('First', 'Second'), selected=None):
    result = [element(1, 'section'),
              element(2, 'heading', 'Choose Robot to Run\nWater', 1),
              element(3, 'push button', 'Proceed to setup', 1)]
    for i, name in enumerate(names):
        card = 10 + i * 10
        result += [element(card, 'section', parent=1, selected=name == selected),
                   element(card + 1, 'heading', 'OT-2', card),
                   element(card + 2, 'paragraph', name, card)]
    return result


class SelectRobotTests(unittest.TestCase):
    def driver(self):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(side_effect=[{'elements': robot_page()},
            {'elements': robot_page(selected='First')}])
        d._validate_element_position = Mock()
        d._cua = SimpleNamespace(click=Mock(return_value='click'))
        d._run = Mock()
        d.click_element = Mock()
        d.wait_for_element = Mock(return_value=element(3, 'push button', 'Proceed to setup', 1))
        d._wait_for_robot_setup = Mock()
        return d

    def test_omitted_name_selects_first_listed_robot(self):
        d = self.driver()
        self.assertEqual(d.select_robot(), {'robot_name': 'First',
            'selection_dispatched': True, 'selection_verified': True, 'setup_open': True})
        d._cua.click.assert_called_once_with(element=12)
        d.wait_for_element.assert_called_once_with('Proceed to setup', role='push button', timeout=10.0)
        d.click_element.assert_called_once_with('Proceed to setup', role='push button')
        d._wait_for_robot_setup.assert_called_once_with('First')

    def test_named_robot_is_selected_exactly(self):
        d = self.driver()
        d.capture_screenshot.side_effect = [{'elements': robot_page()},
            {'elements': robot_page(selected='Second')}]
        self.assertEqual(d.select_robot('Second')['robot_name'], 'Second')
        d._cua.click.assert_called_once_with(element=22)

    def test_empty_name_uses_first(self):
        d = self.driver()
        self.assertEqual(d.select_robot('')['robot_name'], 'First')

    def test_no_robots_raises_before_input(self):
        d = self.driver()
        d.capture_screenshot.side_effect = [{'elements': robot_page(names=())}]
        with self.assertRaisesRegex(RuntimeError, 'No robots are listed'):
            d.select_robot()
        d._cua.click.assert_not_called()

    def test_missing_named_robot_does_not_fall_back(self):
        d = self.driver()
        with self.assertRaisesRegex(RuntimeError, 'No listed robot'):
            d.select_robot('first')
        d._cua.click.assert_not_called()

    def test_duplicate_named_robot_is_rejected(self):
        d = self.driver()
        d.capture_screenshot.side_effect = [{'elements': robot_page(names=('Same', 'Same'))}]
        with self.assertRaisesRegex(RuntimeError, 'Ambiguous robot name'):
            d.select_robot('Same')
        d._cua.click.assert_not_called()

    def test_css_only_selection_is_not_claimed_verified(self):
        d = self.driver()
        d.capture_screenshot.side_effect = [{'elements': robot_page()}, {'elements': robot_page()}]
        self.assertFalse(d.select_robot()['selection_verified'])

    def test_closed_drawer_raises(self):
        d = self.driver()
        d.capture_screenshot.side_effect = [{'elements': []}]
        with self.assertRaisesRegex(RuntimeError, 'start_setup first'):
            d.select_robot()
        d._cua.click.assert_not_called()

    def test_none_is_not_a_string(self):
        d = self.driver()
        with self.assertRaises(ValueError):
            d.select_robot(None)
        d.capture_screenshot.assert_not_called()

    def test_unrelated_robot_card_outside_drawer_is_ignored(self):
        d = self.driver()
        unrelated = [element(100, 'section'), element(101, 'heading', 'OT-2', 100),
                     element(102, 'paragraph', 'Outside', 100)]
        d.capture_screenshot.side_effect = [{'elements': unrelated + robot_page()},
            {'elements': unrelated + robot_page(selected='First')}]
        self.assertEqual(d.select_robot()['robot_name'], 'First')
        d._cua.click.assert_called_once_with(element=12)

    def test_proceed_disabled_does_not_dispatch_proceed(self):
        d = self.driver()
        d.wait_for_element.side_effect = TimeoutError('Proceed disabled')
        with self.assertRaises(TimeoutError):
            d.select_robot()
        d.click_element.assert_not_called()
        d._wait_for_robot_setup.assert_not_called()


class RobotSetupReadbackTests(unittest.TestCase):
    def test_requires_robot_identity_and_not_started_status(self):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(return_value={'elements': [
            element(1, 'link', 'First'), element(2, 'paragraph', 'Not started')]})
        d._validate_element_position = Mock()
        self.assertIsNone(d._wait_for_robot_setup('First'))

    def test_timeout_is_not_success(self):
        from unittest.mock import patch
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(return_value={'elements': [element(1, 'link', 'Wrong')]})
        d._validate_element_position = Mock()
        with patch('time.monotonic', side_effect=[0.0, 31.0]):
            with self.assertRaisesRegex(TimeoutError, 'inspect before retrying'):
                d._wait_for_robot_setup('First')
