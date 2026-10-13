"""Read-only run-header parsing and offline GUI control tests."""
import unittest
from unittest.mock import Mock
from driver import Driver


def e(index, role, label='', parent=None, enabled=True):
    return dict(element_index=index, role=role, label=label, parent_index=parent, enabled=enabled)


def run_page(status='Running'):
    return [e(0,'section'), e(1,'link','Devices',0), e(2,'link','robot-a',0),
            e(3,'link','10/12/2026 16:14:19',0), e(10,'section',parent=0),
            e(11,'link','Example',10), e(12,'heading','Example',11),
            e(13,'paragraph','Run',10), e(14,'paragraph','10/12/2026 16:14:19',10),
            e(15,'paragraph','Status',10), e(16,'paragraph',status,10),
            e(17,'paragraph','Run Time',10), e(18,'paragraph','00:00:10',10),
            e(19,'push button','Pause run' if status=='Running' else 'Resume run',10),
            e(20,'push button','Cancel run',10)]


class RunStatusTests(unittest.TestCase):
    def test_reads_current_run_header_without_input(self):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(return_value={'elements': run_page()})
        d._validate_element_position = Mock()
        d.click_element = Mock()
        self.assertEqual(d.get_run_status(), {
            'robot_name': 'robot-a', 'protocol_name': 'Example',
            'run_label': '10/12/2026 16:14:19', 'status': 'Running',
            'run_time': '00:00:10', 'available_controls': ['Pause run', 'Cancel run'],
            'confirmation_pending': False,
        })
        d.click_element.assert_not_called()

    def test_preview_headings_are_not_protocol_names(self):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(return_value={'elements': run_page() + [
            e(30,'heading','Run Preview',10), e(31,'heading','END OF PROTOCOL',10)]})
        d._validate_element_position = Mock()
        self.assertEqual(d.get_run_status()['protocol_name'], 'Example')


def snapshot(status, controls, pending=False):
    return {'robot_name': 'robot-a', 'protocol_name': 'Example', 'run_label': 'run-label',
            'status': status, 'run_time': '00:00:10', 'available_controls': controls,
            'confirmation_pending': pending}


class RunControlTests(unittest.TestCase):
    def driver(self, before, after):
        d = object.__new__(Driver)
        d.get_run_status = Mock(side_effect=[before, after])
        d.click_element = Mock()
        return d

    def test_pause_waits_for_paused(self):
        d = self.driver(snapshot('Running',['Pause run']), snapshot('Paused',['Resume run']))
        self.assertEqual(d.pause_run()['status'], 'Paused')
        d.click_element.assert_called_once_with('Pause run', role='push button')

    def test_resume_waits_for_running(self):
        d = self.driver(snapshot('Paused',['Resume run']), snapshot('Running',['Pause run']))
        self.assertEqual(d.resume_run()['status'], 'Running')
        d.click_element.assert_called_once_with('Resume run', role='push button')

    def test_cancel_confirms_standard_modal_and_waits_for_canceled(self):
        d = self.driver(snapshot('Running',['Cancel run']), snapshot('Canceled',[]))
        d.get_run_status.side_effect = [snapshot('Running',['Cancel run']),
            snapshot('Running',['Cancel run'],True), snapshot('Canceled',[])]
        d.capture_screenshot = Mock(return_value={'elements': [
            e(40,'section','ModalShell_ModalArea'),
            e(41,'heading','Are you sure you want to cancel?',40),
            e(42,'push button','Yes, cancel run',40)]})
        d._validate_element_position = Mock()
        self.assertEqual(d.cancel_run()['status'], 'Canceled')
        self.assertEqual([call.args[0] for call in d.click_element.call_args_list],
                         ['Cancel run', 'Yes, cancel run'])

    def test_cancel_does_not_repeat_confirmation_while_transitioning(self):
        from unittest.mock import patch
        d = self.driver(snapshot('Running',['Cancel run']), snapshot('Canceled',[]))
        d.get_run_status.side_effect = [snapshot('Running',['Cancel run']),
            snapshot('Running',['Cancel run'],True), snapshot('Stop requested',[],True),
            snapshot('Canceled',[])]
        d.capture_screenshot = Mock(return_value={'elements': [e(40,'section','ModalShell_ModalArea'),
            e(41,'heading','Are you sure you want to cancel?',40),
            e(42,'push button','Yes, cancel run',40)]})
        d._validate_element_position = Mock()
        with patch('time.sleep'):
            self.assertEqual(d.cancel_run()['status'], 'Canceled')
        self.assertEqual(d.click_element.call_count, 2)

    def test_cancel_finds_nested_confirmation_in_unordered_snapshot(self):
        d = self.driver(snapshot('Running', ['Cancel run']), snapshot('Canceled', []))
        d.get_run_status.side_effect = [
            snapshot('Running', ['Cancel run']),
            snapshot('Running', ['Cancel run'], True), snapshot('Canceled', [])]
        d.capture_screenshot = Mock(return_value={'elements': [
            e(43, 'push button', 'Yes, cancel run', 42),
            e(41, 'heading', 'Are you sure you want to cancel?', 42),
            e(42, 'section', parent=40),
            e(40, 'section', 'ModalShell_ModalArea'),
            e(50, 'push button', 'Yes, cancel run')]})
        d._validate_element_position = Mock()
        self.assertEqual(d.cancel_run()['status'], 'Canceled')
        self.assertEqual([call.args[0] for call in d.click_element.call_args_list],
                         ['Cancel run', 'Yes, cancel run'])

    def test_cancel_rejects_malformed_confirmation_before_accepting(self):
        for malformed in ('cycle', 'duplicate'):
            with self.subTest(malformed=malformed):
                d = self.driver(snapshot('Running', ['Cancel run']),
                                snapshot('Running', ['Cancel run'], True))
                elements = [
                    e(40, 'section', 'ModalShell_ModalArea',
                      parent=42 if malformed == 'cycle' else None),
                    e(41, 'heading', 'Are you sure you want to cancel?', 40),
                    e(42, 'push button', 'Yes, cancel run', 40)]
                if malformed == 'duplicate':
                    elements.append(e(42, 'section', parent=40))
                d.capture_screenshot = Mock(return_value={'elements': elements})
                d._validate_element_position = Mock()
                with self.assertRaisesRegex(RuntimeError, 'Malformed cancel confirmation'):
                    d.cancel_run()
                d.click_element.assert_called_once_with('Cancel run', role='push button')

    def test_invalid_state_does_not_click(self):
        for method in ('pause_run','resume_run','cancel_run'):
            d = self.driver(snapshot('Completed',[]), snapshot('Completed',[]))
            with self.subTest(method=method), self.assertRaises(RuntimeError):
                getattr(d,method)()
            d.click_element.assert_not_called()

    def test_existing_dialog_is_not_accepted(self):
        d = self.driver(snapshot('Running',['Pause run'],True), snapshot('Paused',[]))
        with self.assertRaisesRegex(RuntimeError, 'existing confirmation'):
            d.pause_run()
        d.click_element.assert_not_called()

    def test_changed_run_identity_is_rejected(self):
        after = snapshot('Paused',[])
        after['run_label'] = 'different-run'
        d = self.driver(snapshot('Running',['Pause run']),after)
        with self.assertRaisesRegex(RuntimeError, 'identity changed'):
            d.pause_run()
        d.click_element.assert_called_once()

    def test_pause_timeout_does_not_retry(self):
        d = self.driver(snapshot('Running',['Pause run']),snapshot('Running',['Pause run']))
        with self.assertRaisesRegex(TimeoutError, 'inspect before retrying'):
            d.pause_run(timeout=0)
        d.click_element.assert_called_once()

    def test_resume_accepts_rapid_completion(self):
        d = self.driver(snapshot('Paused',['Resume run']),snapshot('Completed',[]))
        self.assertEqual(d.resume_run()['status'],'Completed')

    def test_door_open_pause_is_not_silently_resumed(self):
        d = self.driver(snapshot('Paused - door open',['Resume run']),snapshot('Running',[]))
        with self.assertRaises(RuntimeError):
            d.resume_run()
        d.click_element.assert_not_called()

    def test_invalid_timeout_does_not_capture(self):
        d = self.driver(snapshot('Running',['Pause run']),snapshot('Paused',[]))
        with self.assertRaises(ValueError):
            d.pause_run(timeout=-1)
        d.get_run_status.assert_not_called()
