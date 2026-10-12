"""Offline inventory tests based on observed App accessibility layouts."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
from driver import Driver


def e(index, role, label='', parent=None):
    return dict(element_index=index, role=role, label=label, parent_index=parent, enabled=True)


def devices_page(collapsed=False):
    es = [e(0,'section'),e(1,'heading','Devices',0), e(2,'section',parent=0),
          e(3,'paragraph','Available (1)',2),e(4,'push button',parent=2),
          e(5,'section',parent=0),e(6,'paragraph','OT-2',5),e(7,'paragraph','robot-a',5),
          e(8,'paragraph','Instruments',5),e(9,'paragraph','P300',5),
          e(10,'section',parent=0),e(11,'paragraph','Not Available (1)',10),
          e(12,'push button',parent=10)]
    if not collapsed:
        es += [e(13,'section',parent=0),e(14,'paragraph','OT-2',13),e(15,'paragraph','robot-b',13)]
    return es


class InventoryTests(unittest.TestCase):
    def driver(self, pages):
        d = object.__new__(Driver)
        d.capture_screenshot = Mock(side_effect=[{'elements': es} for es in pages])
        d.click_element = Mock()
        d._validate_element_position = Mock()
        d._cua = SimpleNamespace(click=Mock(return_value='click'))
        d._run = Mock()
        return d

    def test_devices_include_available_and_unavailable(self):
        d = self.driver([devices_page()])
        self.assertEqual(d.list_devices(), {'devices': [
            {'name':'robot-a','model':'OT-2','available':True,'instruments':['P300']},
            {'name':'robot-b','model':'OT-2','available':False,'instruments':[]},
        ], 'count':2})
        d.click_element.assert_called_once_with('Devices', role='link')

    def test_devices_expand_collapsed_unavailable_group(self):
        d = self.driver([devices_page(collapsed=True), devices_page()])
        self.assertEqual(d.list_devices()['count'], 2)
        d._cua.click.assert_called_once_with(element=12)

    def test_labware_reads_category_name_and_api_name(self):
        es = [e(0,'section'),e(1,'heading','Labware',0), e(2,'paragraph','Category',0),
              e(3,'section',parent=0),e(4,'paragraph','All',3),
              e(5,'paragraph','Sort by',0),e(6,'section',parent=0),e(7,'paragraph','Alphabetical',6),
              e(10,'link','Reservoir Example Opentrons Definition API NAME example',0),
              e(11,'paragraph','Reservoir',10),e(12,'heading','Example',10),
              e(13,'heading','API NAME',10),e(14,'paragraph','example',10),
              e(15,'paragraph','Create a new labware definition',0)]
        d = self.driver([es])
        self.assertEqual(d.list_labware(), {'labware': [
            {'name':'Example','category':'Reservoir','api_name':'example'}], 'count':1,
            'category':'All','sort_by':'Alphabetical'})
        d.click_element.assert_called_once_with('Labware', role='link')

    def test_invalid_filters_fail_before_navigation(self):
        d = self.driver([])
        for kwargs in ({'category':'Unknown'}, {'sort_by':'Newest'}, {'category':None}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                d.list_labware(**kwargs)
        d.click_element.assert_not_called()

    def test_labware_gui_category_and_sort_are_selected(self):
        from copy import deepcopy
        initial = [e(0,'section'),e(1,'heading','Labware',0),e(2,'paragraph','Category',0),
            e(3,'section',parent=0),e(4,'paragraph','All',3),e(5,'paragraph','Sort by',0),
            e(6,'section',parent=0),e(7,'paragraph','Alphabetical',6),
            e(15,'paragraph','Create a new labware definition',0)]
        filtered = deepcopy(initial)
        filtered[4]['label'] = 'Tip Rack'
        sorted_page = deepcopy(filtered)
        sorted_page[7]['label'] = 'Reverse alphabetical'
        d = self.driver([initial,filtered,sorted_page])
        d.wait_for_element = Mock()
        result = d.list_labware(category='tip rack',sort_by='reverse alphabetical')
        self.assertEqual(result['category'],'Tip Rack')
        self.assertEqual(result['sort_by'],'Reverse alphabetical')
        self.assertEqual([c.args[0] for c in d.click_element.call_args_list],
                         ['Labware','Tip Rack','Reverse alphabetical'])
        self.assertEqual([c.kwargs['element'] for c in d._cua.click.call_args_list],[4,7])

    def test_labware_footer_is_required_even_for_empty_list(self):
        es = [e(0,'section'),e(1,'heading','Labware',0),e(2,'paragraph','Category',0),
            e(3,'section',parent=0),e(4,'paragraph','All',3),e(5,'paragraph','Sort by',0),
            e(6,'section',parent=0),e(7,'paragraph','Alphabetical',6)]
        d = self.driver([es])
        with self.assertRaisesRegex(RuntimeError,'incomplete'):
            d.list_labware()

    def test_navigation_waits_for_target_not_sidebar_heading(self):
        from unittest.mock import patch
        sidebar = [e(50,'link','Devices'),e(51,'heading','Devices',50)]
        d = self.driver([sidebar,devices_page()])
        with patch('time.sleep'):
            self.assertEqual(d.list_devices()['count'],2)
        d.click_element.assert_called_once_with('Devices',role='link')

    def test_zero_devices_with_confirmed_counts_returns_empty(self):
        es = [e(0,'section'),e(1,'heading','Devices',0),e(2,'section',parent=0),
              e(3,'paragraph','Available (0)',2),e(4,'section',parent=0),
              e(5,'paragraph','Not Available (0)',4)]
        d = self.driver([es])
        self.assertEqual(d.list_devices(),{'devices':[],'count':0})
