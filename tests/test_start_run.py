"""Offline run-start tests: actual hardware input is mocked."""
import unittest
from unittest.mock import Mock, patch
from driver import Driver


def e(index, label, role='paragraph', parent=None, enabled=True):
    return dict(element_index=index, label=label, role=role,
                parent_index=parent, enabled=enabled)


class StartRunTests(unittest.TestCase):
    def driver(self, after):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(side_effect=[{'elements': [e(1,'Not started'),
            e(2,'Start run','push button')]}, {'elements': after}])
        d._validate_element_position = Mock()
        d.click_element = Mock()
        return d

    def test_clicks_once_and_observes_running(self):
        d = self.driver([e(3,'Running')])
        self.assertEqual(d.start_run(), {'status': 'Running', 'started': True})
        d.click_element.assert_called_once_with('Start run', role='push button')

    def test_fast_run_can_be_observed_completed(self):
        d = self.driver([e(3,'Completed')])
        self.assertEqual(d.start_run()['status'], 'Completed')
        d.click_element.assert_called_once()

    def test_running_or_completed_run_is_not_started_again(self):
        for status in ('Running', 'Completed'):
            d = self.driver([])
            d.capture_screenshot.side_effect = [{'elements': [e(1,status), e(2,'Start run','push button')]}]
            with self.subTest(status=status), self.assertRaises(RuntimeError):
                d.start_run()
            d.click_element.assert_not_called()

    def test_disabled_start_button_is_rejected(self):
        d = self.driver([])
        d.capture_screenshot.side_effect = [{'elements': [e(1,'Not started'),
            e(2,'Start run','push button',enabled=False)]}]
        with self.assertRaisesRegex(RuntimeError, 'enabled Start run'):
            d.start_run()
        d.click_element.assert_not_called()

    def test_existing_confirmation_is_rejected_before_dispatch(self):
        for label, role in (('Confirm', 'dialog'), ('Confirm', 'alert dialog'),
                            ('ModalShell_ModalArea', 'group')):
            with self.subTest(label=label, role=role):
                d = self.driver([e(4, 'Running')])
                d.capture_screenshot.side_effect = [
                    {'elements': [e(1, 'Not started'),
                                  e(2, 'Start run', 'push button'),
                                  e(3, label, role)]},
                    {'elements': [e(4, 'Running')]},
                ]
                with self.assertRaisesRegex(RuntimeError, 'confirmation'):
                    d.start_run(timeout=0)
                d.click_element.assert_not_called()
                d.capture_screenshot.assert_called_once_with(include_elements=True)

    def test_confirmation_is_not_silently_accepted(self):
        d = self.driver([e(3,'Confirm','dialog'), e(4,'Start run','push button',parent=3)])
        with self.assertRaisesRegex(RuntimeError, 'confirmation'):
            d.start_run()
        d.click_element.assert_called_once()

    def test_modal_area_only_confirmation_after_dispatch_is_rejected(self):
        d = self.driver([e(3, 'ModalShell_ModalArea', 'group'),
                         e(4, 'Start run', 'push button', parent=3)])
        with self.assertRaisesRegex(RuntimeError, 'confirmation'):
            d.start_run(timeout=0)
        d.click_element.assert_called_once_with('Start run', role='push button')

    def test_confirmation_takes_precedence_over_running_or_completed(self):
        for status in ('Running', 'Completed'):
            for label, role in (('Confirm', 'dialog'), ('Confirm', 'alert dialog'),
                                ('ModalShell_ModalArea', 'group')):
                with self.subTest(status=status, label=label, role=role):
                    d = self.driver([e(3, status), e(4, label, role),
                                     e(5, 'Start run', 'push button', parent=4)])
                    with self.assertRaisesRegex(RuntimeError, 'confirmation'):
                        d.start_run(timeout=0)
                    d.click_element.assert_called_once_with('Start run', role='push button')

    def test_failed_run_raises(self):
        d = self.driver([e(3,'Failed')])
        with self.assertRaisesRegex(RuntimeError, 'failure'):
            d.start_run()
        d.click_element.assert_called_once()

    def test_timeout_does_not_repeat_start(self):
        d = self.driver([e(3,'Not started')])
        with self.assertRaisesRegex(TimeoutError, 'inspect before retrying'):
            d.start_run(timeout=0)
        d.click_element.assert_called_once()

    def test_invalid_timeout_fails_before_capture(self):
        d = self.driver([])
        for value in (-1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                d.start_run(timeout=value)
        d.capture_screenshot.assert_not_called()
