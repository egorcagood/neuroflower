import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from core import Store
from sensors import create_ingest_server

class IngestTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.db=Store(Path(self.temp.name)/'db.sqlite')
        self.server=create_ingest_server(self.db,'secret-test',('127.0.0.1',0))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()
    def request(self,token,data):
        req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+'/v1/readings',json.dumps(data).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req) as r: return r.status
        except urllib.error.HTTPError as e: return e.code
    def test_requires_token(self):
        self.assertEqual(self.request('wrong',{'soil_raw':2000}),401)
        self.assertIsNone(self.db.snapshot()['reading'])
    def test_accepts_valid_rejects_invalid(self):
        self.assertEqual(self.request('secret-test',{'soil_raw':2000,'temperature_C':23}),200)
        self.assertEqual(self.request('secret-test',{'soil_raw':9999}),400)
        self.assertEqual(self.db.snapshot()['reading']['soil_raw'],2000)
    def test_rejects_stale_remote_sample(self):
        self.assertEqual(self.request('secret-test',{'soil_raw':2000,'at':100}),400)

if __name__=='__main__': unittest.main()
