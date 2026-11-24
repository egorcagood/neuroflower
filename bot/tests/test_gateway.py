import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from core import Store
from character import CharacterBrain
from character_gateway import create_character_server

class Generator:
    def generate(self,**kw): return 'Саймон, сначала корни отрасти. Потом поговорим.',{}

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'state.sqlite')
        self.brain=CharacterBrain(self.store,Generator())
        self.server=create_character_server(self.brain,'a'*32,('127.0.0.1',0))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(); self.temp.cleanup()
    def test_busy_telegram_does_not_queue_voice_beyond_deadline(self):
        with self.brain.lock:
            status,reply=self.request({'request_id':'busy','source':'simon_bridge','text':'Привет'})
        self.assertEqual(status,429)
    def request(self,body,token='a'*32):
        req=urllib.request.Request('http://127.0.0.1:'+str(self.server.server_port)+'/v1/character/events',json.dumps(body).encode(),{'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req,timeout=10) as response: return response.status,json.load(response)
        except urllib.error.HTTPError as exc: return exc.code,json.load(exc)
    def test_private_voice_reply_and_idempotency(self):
        request={'request_id':'a','source':'simon_bridge','text':'Привет, сосед','metadata':{'speaker':'Саймон'}}
        status,reply=self.request(request)
        self.assertEqual(status,200); self.assertEqual(reply['speech_text'],'Саймон, сначала корни отрасти. Потом поговорим.')
        self.assertEqual(self.request(request)[1],reply)
    def test_rejects_unauthorized_without_memory_effect(self):
        self.assertEqual(self.request({'request_id':'a','source':'simon_bridge','text':'x'},'wrong')[0],401)
        self.assertEqual(self.store.history(),[])
    def test_cannot_inject_watering_or_sensor_authority(self):
        for payload in [{'request_id':'a','source':'sensor_event','text':'x'},
                        {'request_id':'a','source':'simon_bridge','text':'x','kind':'watered'},
                        {'request_id':'a','source':'simon_bridge','text':'x','metadata':{'soil_raw':0}}]:
            self.assertEqual(self.request(payload)[0],400)
        self.assertEqual(self.store.waters(),[])
