import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from core import Store, MOSCOW
from care import light_history, next_notice, notice_sent

class CareTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.tmp.name)/'db')
        self.now=datetime(2026,11,23,12,tzinfo=MOSCOW).timestamp()
        self.store.set('owner_started',True); self.store.set('care_started_at',self.now-8*86400)
        self.store.set('last_photo_at',self.now)
        self.store.add_reading({'at':self.now,'soil_raw':2800,'light_lux':100})
    def tearDown(self): self.tmp.cleanup()
    def history(self,lux=100,sparse=False):
        for days in (1,2):
            start=datetime.fromtimestamp(self.now,MOSCOW).replace(hour=9,minute=0,second=0)-timedelta(days=days)
            for i in range(54):
                for j in range(1 if sparse else 6):
                    self.store.add_reading({'at':start.timestamp()+i*600+j*60,'soil_raw':2800,'light_lux':lux})
    def test_two_days_dim_and_good_coverage(self):
        self.history(); self.assertEqual(light_history(self.store,self.now)['status'],'low')
        self.assertEqual(next_notice(self.store,self.now)['kind'],'light_notice')
    def test_sparse_samples_and_current_darkness_not_history(self):
        self.history(sparse=True); self.assertEqual(light_history(self.store,self.now)['status'],'insufficient')
        self.assertIsNone(next_notice(self.store,self.now))
    def test_bright_days_not_alert(self):
        self.history(4000); self.assertEqual(light_history(self.store,self.now)['status'],'not_low')
    def test_weekly_photo_even_without_sensors_but_no_thirst(self):
        self.store.set('last_photo_at',self.now-8*86400)
        notice=next_notice(self.store,self.now+1000)
        self.assertEqual(notice['kind'],'photo_notice'); self.assertIn('фото',notice['text'].lower())
        notice_sent(self.store,notice,self.now+1000)
        self.assertIsNone(next_notice(self.store,self.now+1010))
    def test_pause_quiet_time_and_shared_cooldown(self):
        self.store.set('last_photo_at',self.now-8*86400)
        self.store.set('reminders_paused',True); self.assertIsNone(next_notice(self.store,self.now))
        self.store.set('reminders_paused',False)
        self.assertIsNone(next_notice(self.store,self.now+11*3600))
        self.store.set('last_care_notice',self.now-10); self.assertIsNone(next_notice(self.store,self.now))
    def test_missing_current_data_does_not_send_light_claim(self):
        self.history(); self.assertIsNone(next_notice(self.store,self.now+1000))
    def test_no_photo_repeat_after_recent_dry_photo_request(self):
        self.store.set('last_photo_at',self.now-8*86400)
        self.store.set('last_photo_request',self.now-2*86400)
        self.assertIsNone(next_notice(self.store,self.now))

