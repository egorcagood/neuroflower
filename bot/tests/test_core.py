import tempfile
import unittest
from pathlib import Path
from core import Store, parse_reading, moisture, reminder_due, validate_reading

LINE = 'uptime_s=58 | soil_raw=3277/4095 | soil_mV=2708 (uncalibrated) | light_lux=0.8 | temperature_C=26.16 | air_RH_pct=37.71'

class CoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Store(Path(self.temp.name)/'memory.sqlite')
    def tearDown(self): self.temp.cleanup()
    def test_serial_parser_and_sensor_failure(self):
        row = parse_reading(LINE, 100)
        self.assertEqual(row['soil_raw'],3277)
        self.assertEqual(row['temperature_C'],26.16)
        broken = parse_reading('uptime_s=1 | soil_raw=2000/4095 | BH1750=NOT_FOUND | SHT30=READ_ERROR',100)
        self.assertIsNone(broken['temperature_C'])
        self.assertIsNone(broken['light_lux'])
        self.assertIsNone(parse_reading('USB_STARTUP',100))
        self.assertIsNone(parse_reading(LINE.replace('3277','9000'),100))
    def test_validation_rejects_nan_bool_and_bad_ranges(self):
        for change in [{'soil_raw':True},{'soil_raw':9000},{'temperature_C':float('nan')},{'air_RH_pct':101}]:
            with self.assertRaises(ValueError): validate_reading(dict(parse_reading(LINE,100),**change))
    def test_uncalibrated_and_direction(self):
        self.assertIsNone(moisture(3000,{}))
        self.assertEqual(moisture(2500,{'dry':3000,'wet':2000}),50)
        with self.assertRaises(ValueError): moisture(2500,{'dry':2000,'wet':3000})
    def test_history_survives_restart_and_water_is_idempotent(self):
        self.assertTrue(self.db.water('tg:1',100))
        self.assertFalse(self.db.water('tg:1',101))
        other = Store(self.db.path)
        self.assertEqual(other.waters()[0]['at'],100)
        self.assertEqual(len(other.waters()),1)
    def test_stale_readings_explicit(self):
        self.db.add_reading(parse_reading(LINE,100))
        self.assertTrue(self.db.snapshot(now=191)['stale'])
        self.assertFalse(self.db.snapshot(now=150)['stale'])
    def test_dryness_requires_sustained_fresh_calibrated_samples(self):
        for at in range(0,601,10): self.db.add_reading(parse_reading(LINE,at))
        self.assertFalse(reminder_due(self.db,600))
        self.db.set('calibration',{'dry':3300,'wet':1800})
        self.db.set('profile','Фикус, имя Борис')
        self.assertTrue(reminder_due(self.db,600))
        self.assertFalse(reminder_due(self.db,800))
        self.db.set('last_reminder',600)
        self.assertFalse(reminder_due(self.db,601))
    def test_recent_watering_suppresses_reminder(self):
        self.db.set('calibration',{'dry':3300,'wet':1800})
        self.db.set('profile','Фикус')
        for at in range(0,601,10): self.db.add_reading(parse_reading(LINE,at))
        self.db.water('water',590)
        self.assertFalse(reminder_due(self.db,600))
    def test_daily_ai_limit_is_persistent(self):
        self.assertTrue(self.db.reserve_ai(2,100))
        self.assertTrue(self.db.reserve_ai(2,100))
        self.assertFalse(Store(self.db.path).reserve_ai(2,100))
    def test_chat_memory_is_bounded(self):
        for i in range(210): self.db.chat('user',str(i),100+i)
        self.assertEqual(len(self.db.history(300)),200)

if __name__=='__main__': unittest.main()
