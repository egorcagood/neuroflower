import unittest
from bridge import Forwarder

class BridgeTests(unittest.TestCase):
    def test_ingest_never_waits_for_network_and_keeps_only_latest(self):
        bridge=Forwarder({'ingest_url':'https://example.com/v1/readings','ingest_token':'test'})
        bridge.add_reading({'soil_raw':1000,'at':1})
        bridge.add_reading({'soil_raw':2000,'at':2})
        self.assertEqual(bridge.take_latest(),{'soil_raw':2000,'at':2})
        self.assertIsNone(bridge.take_latest())
    def test_reject_plain_http(self):
        with self.assertRaises(ValueError): Forwarder({'ingest_url':'http://example.com','ingest_token':'test'})
