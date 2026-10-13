"""Protocol-list tests using the observed Opentrons OT-2 AX card layout."""
import unittest
from unittest.mock import Mock
from driver import Driver
from puda.command import resolve_command_names


def element(index, role, label='', parent=None):
    result = {'element_index': index, 'role': role, 'label': label}
    if parent is not None:
        result['parent_index'] = parent
    return result


def protocol_page():
    return [
        element(1, 'heading', 'Protocols', 0),
        element(2, 'push button', 'Import', 0),
        element(3, 'section', '', 0),
        element(4, 'paragraph', 'Water transfer', 3),
        element(5, 'paragraph', 'Instruments', 3),
        element(6, 'paragraph', 'P300 Single-Channel GEN2', 3),
        element(7, 'paragraph', 'Updated 10/2/26 16:13', 3),
        element(8, 'section', '', 0),
        element(9, 'paragraph', 'Water transfer', 8),
        element(10, 'paragraph', 'Instruments', 8),
        element(11, 'paragraph', 'Updated 10/9/26 14:02', 8),
        element(12, 'landmark', 'Create or download a new protocol', 0),
        # Offscreen import drawer must not be mistaken for a protocol.
        element(13, 'heading', 'Import a Protocol', 0),
    ]


class ProtocolListTests(unittest.TestCase):
    def make_driver(self, elements):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(return_value={'elements': elements})
        d.click_element = Mock()
        return d

    def test_lists_cards_and_preserves_duplicate_names(self):
        d = self.make_driver(protocol_page())
        self.assertEqual(d.list_protocols(), {
            'protocols': [
                {'name': 'Water transfer', 'instruments': ['P300 Single-Channel GEN2'],
                 'updated': '10/2/26 16:13'},
                {'name': 'Water transfer', 'instruments': [], 'updated': '10/9/26 14:02'},
            ], 'count': 2,
        })
        d.click_element.assert_not_called()
        self.assertIn('list_protocols', resolve_command_names(object.__new__(Driver)))

    def test_navigates_to_protocols_from_another_page(self):
        d = self.make_driver([])
        d.capture_screenshot.side_effect = [
            {'elements': [element(1, 'link', 'Protocols', 0)]},
            {'elements': protocol_page()},
        ]
        self.assertEqual(d.list_protocols()['count'], 2)
        d.click_element.assert_called_once_with('Protocols', role='link')

    def test_missing_page_is_not_reported_as_empty(self):
        d = self.make_driver([])
        with self.assertRaises(RuntimeError):
            d.list_protocols()

    def test_truncated_list_is_rejected(self):
        d = self.make_driver(protocol_page()[:11])
        with self.assertRaisesRegex(RuntimeError, 'incomplete'):
            d.list_protocols()

    def test_malformed_card_is_rejected(self):
        elements = protocol_page()
        elements[3]['label'] = 'Instruments'
        d = self.make_driver(elements)
        with self.assertRaisesRegex(RuntimeError, 'card layout'):
            d.list_protocols()
