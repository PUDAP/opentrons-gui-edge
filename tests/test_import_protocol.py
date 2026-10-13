"""Offline import tests; GUI interactions are mocked, no robot is contacted."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from driver import Driver


class ImportProtocolTests(unittest.TestCase):
    def test_native_picker_import_returns_new_card_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'protocol.py'
            path.write_text('# offline fixture\n')
            d = object.__new__(Driver)
            card = {'name': 'Example', 'instruments': [], 'updated': '10/12/26 16:00'}
            d.list_protocols = Mock(side_effect=[
                {'protocols': [], 'count': 0}, {'protocols': [card], 'count': 1},
            ])
            d.click_element = Mock()
            d.wait_for_element = Mock(return_value={'label': 'Import a Protocol'})
            d._validate_element_position = Mock()
            d._choose_file_in_dialog = Mock()
            result = d.import_protocol(str(path))
            self.assertEqual(result, {'imported_file': str(path), 'protocol': card})
            self.assertEqual(d.click_element.call_args_list[0].args, ('Import',))
            self.assertEqual(d.click_element.call_args_list[1].args, ('browse',))
            d._choose_file_in_dialog.assert_called_once_with(str(path), timeout=30.0)

    def test_invalid_paths_fail_before_gui_input(self):
        d = object.__new__(Driver)
        d.list_protocols = Mock()
        for value in ('', 'relative.py', '/file.txt'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                d.import_protocol(value)
        with self.assertRaises(FileNotFoundError):
            d.import_protocol('/no-such-import-protocol-test.py')
        d.list_protocols.assert_not_called()

    def test_uncertain_import_is_never_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'protocol.json'
            path.write_text('{}')
            d = object.__new__(Driver)
            d.list_protocols = Mock(return_value={'protocols': [], 'count': 0})
            d.click_element = Mock()
            d.wait_for_element = Mock(return_value={})
            d._validate_element_position = Mock()
            d._choose_file_in_dialog = Mock()
            with self.assertRaisesRegex(TimeoutError, 'inspect the App'):
                d.import_protocol(str(path), timeout=0)
            self.assertEqual(d.click_element.call_count, 2)
            d._choose_file_in_dialog.assert_called_once()

    def test_picker_failure_propagates_without_verification(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'protocol.py'
            path.write_text('# test')
            d = object.__new__(Driver)
            d.list_protocols = Mock(return_value={'protocols': [], 'count': 0})
            d.click_element = Mock()
            d.wait_for_element = Mock(return_value={})
            d._validate_element_position = Mock()
            d._choose_file_in_dialog = Mock(side_effect=RuntimeError('picker failed'))
            with self.assertRaisesRegex(RuntimeError, 'picker failed'):
                d.import_protocol(str(path))
            d.list_protocols.assert_called_once()

    def test_duplicate_card_preserves_multiplicity(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'protocol.py'
            path.write_text('# test')
            d = object.__new__(Driver)
            card = {'name': 'Same', 'instruments': [], 'updated': 'same minute'}
            d.list_protocols = Mock(side_effect=[
                {'protocols': [card]}, {'protocols': [card, card]},
            ])
            d.click_element = Mock()
            d.wait_for_element = Mock(return_value={})
            d._validate_element_position = Mock()
            d._choose_file_in_dialog = Mock()
            self.assertEqual(d.import_protocol(str(path))['protocol'], card)
