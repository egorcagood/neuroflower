import tempfile
import unittest
import threading
import time
from pathlib import Path
from core import Store
from character import CharacterBrain, CharacterEvent
from voice import voice_control

class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.tmp.name)/'db')
        self.brain=CharacterBrain(self.store,None)
    def tearDown(self): self.tmp.cleanup()
    def ask(self,text,ident='1',now=1000,speaker='Егор',source='simon_bridge'):
        return voice_control(self.brain,CharacterEvent(ident,source,text,metadata={'speaker':speaker}),now)
    def test_water_requires_confirmation_is_idempotent_and_shared(self):
        self.assertIn('подтверждаю',self.ask('я полил').speech_text)
        self.assertEqual(self.store.waters(),[])
        reply=self.ask('подтверждаю полив','2',1010)
        self.assertIn('запомнил',reply.text); self.assertEqual(len(self.store.waters()),1)
        self.ask('подтверждаю полив','2',1020); self.ask('подтверждаю полив','3',1021)
        self.assertEqual(len(self.store.waters()),1)
    def test_expired_and_other_source_confirmation_rejected(self):
        self.ask('я полил'); self.ask('подтверждаю полив','2',1061)
        self.assertEqual(self.store.waters(),[])
        self.ask('я полил','3',1070)
        self.ask('подтверждаю полив','4',1080,source='yandex_station')
        self.assertEqual(self.store.waters(),[])
    def test_pause_resume_without_generation(self):
        self.ask('поставь напоминания на паузу'); self.assertTrue(self.store.get('reminders_paused'))
        self.ask('верни напоминания','2'); self.assertFalse(self.store.get('reminders_paused'))
    def test_simon_cannot_record_water_and_intentions_are_not_actions(self):
        self.ask('я полил',speaker='Саймон'); self.ask('подтверждаю полив','2',speaker='Саймон')
        self.assertEqual(self.store.waters(),[])
        self.assertIsNone(self.ask('я завтра полью','3'))
    def test_readings_mark_stale_and_do_not_claim_pump(self):
        self.store.add_reading({'soil_raw':2800,'at':1,'light_lux':12})
        self.assertIn('устарел',self.ask('показания').text)
        self.assertIn('насос',self.ask('полей растение','2').text.lower())
    def test_controls_do_not_wait_for_photo_generation(self):
        done=threading.Event()
        def request():
            self.ask('поставь напоминания на паузу'); done.set()
        with self.brain.lock:
            thread=threading.Thread(target=request); thread.start()
            finished=done.wait(1)
        thread.join(2)
        self.assertTrue(finished,'Voice control was blocked behind Telegram GPT call')
    def test_confirmation_expiring_while_waiting_is_not_written(self):
        self.store.set('voice_water_pending:simon_bridge',{'request_id':'old','expires':time.time()+.1})
        event=CharacterEvent('expire','simon_bridge','подтверждаю полив',metadata={'speaker':'Егор'})
        with self.brain.control_lock:
            thread=threading.Thread(target=lambda:voice_control(self.brain,event)); thread.start()
            time.sleep(.2)
        thread.join(2)
        self.assertEqual(self.store.waters(),[])

