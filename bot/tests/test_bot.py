import tempfile
import unittest
import time
from pathlib import Path
from core import Store
from bot import PlantBot
from character import CharacterBrain

class TelegramFake:
    def __init__(self): self.sent=[]
    def send(self,text,**kwargs): self.sent.append(text)
    def photo(self,file_id): return b'photo','image/jpeg'
    def action(self): pass
    def answer_callback(self,ident): pass

class AIFake:
    def __init__(self): self.calls=[]
    def generate(self,**kwargs):
        self.calls.append(kwargs)
        return 'Кожаный, я великолепен. Вопросы?',{}

class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Store(Path(self.temp.name)/'db.sqlite')
        self.tg=TelegramFake(); self.ai=AIFake()
        self.brain=CharacterBrain(self.db,self.ai)
        self.bot=PlantBot({'owner_id':123},self.db,self.tg,self.brain)
    def tearDown(self): self.temp.cleanup()
    def test_server_help_does_not_require_windows_computer(self):
        self.db.set('runtime_mode','server')
        self.bot.handle(self.update('/help'))
        self.assertNotIn('включённом компьютере',self.tg.sent[-1])
        self.assertIn('USB',self.tg.sent[-1])
        self.assertIn('не спать',self.tg.sent[-1])
    def update(self,text='',user=123,photo=None,ident=1):
        msg={'from':{'id':user},'chat':{'id':user,'type':'private'},'text':text}
        if photo: msg['photo']=[{'file_id':photo}]
        return {'update_id':ident,'message':msg}
    def test_stranger_cannot_spend_or_read(self):
        self.bot.handle(self.update('Как ты?',user=999))
        self.assertEqual(self.tg.sent,[]); self.assertEqual(self.ai.calls,[])
    def test_group_is_rejected_even_for_owner(self):
        update=self.update('Как ты?'); update['message']['chat']['type']='group'
        self.bot.handle(update); self.assertEqual(self.tg.sent,[])
    def test_water_button_requires_confirmation(self):
        self.bot.handle(self.update('Я полил'))
        self.assertEqual(self.db.waters(),[])
        self.bot.handle({'update_id':2,'callback_query':{'id':'x','from':{'id':123},'message':{'chat':{'id':123,'type':'private'}},'data':'water:yes'}})
        self.assertEqual(len(self.db.waters()),1)
    def test_duplicate_update_not_reprocessed(self):
        self.bot.handle(self.update('Привет'))
        self.bot.handle(self.update('Привет'))
        self.assertEqual(len(self.ai.calls),1)
    def test_profile_persists_and_is_readable(self):
        self.bot.handle(self.update('/plant',ident=1))
        self.bot.handle(self.update('Фикус Борис, на подоконнике',ident=2))
        self.assertEqual(self.db.get('profile'),'Фикус Борис, на подоконнике')
        self.bot.handle(self.update('О растении',ident=3))
        self.assertIn('Фикус Борис',self.ai.calls[-1]['context']['profile'])
    def test_photo_passes_to_ai_and_marks_inspection(self):
        self.db.set('awaiting_photo',True)
        self.bot.handle(self.update(photo='file1'))
        self.assertEqual(self.ai.calls[0]['image'],b'photo')
        self.assertFalse(self.db.get('awaiting_photo'))
        self.assertIsNotNone(self.db.get('last_photo_at'))
    def test_empty_reading_honest(self):
        self.bot.handle(self.update('Показания'))
        self.assertIn('нет',self.tg.sent[-1].lower())
        self.assertEqual(self.ai.calls,[])
    def test_readings_button_returns_numbers_without_ai_or_profile_overwrite(self):
        self.db.set('awaiting_profile',True)
        self.db.set('profile','Стёпа')
        self.db.set('calibration',{'dry':3250,'wet':2750})
        self.db.add_reading({'at':time.time(),'soil_raw':3000,'soil_mV':2300,'light_lux':0,'temperature_C':21.5,'air_RH_pct':47.2})
        self.bot.handle(self.update('Показатели'))
        text=self.tg.sent[-1]
        for value in ('50','0 лк','21.5 °C','47.2 %','МСК','калибровке'): self.assertIn(value,text)
        self.assertEqual(self.ai.calls,[])
        self.assertEqual(self.db.get('profile'),'Стёпа')
        from adapters import KEYBOARD
        self.assertIn('Показатели',sum(KEYBOARD['keyboard'],[]))
    def test_readings_stale_and_missing_fields_are_explicit(self):
        self.db.add_reading({'at':time.time()-200,'soil_raw':3000})
        self.bot.handle(self.update('/readings'))
        text=self.tg.sent[-1]
        self.assertIn('устарели',text)
        self.assertIn('нет данных',text)
        self.assertIn('не настроена',text)
        self.assertEqual(self.ai.calls,[])
    def test_no_calibration_with_missing_data(self):
        self.bot.handle(self.update('/dry'))
        self.assertEqual(self.db.get('calibration',{}),{})
    def test_question_about_watering_does_not_record_it(self):
        self.bot.handle(self.update('Я полил вчера или позавчера?'))
        self.assertEqual(self.db.waters(),[])
    def test_same_confirmation_button_cannot_record_twice(self):
        for ident in (1,2):
            self.bot.handle({'update_id':ident,'callback_query':{'id':str(ident),'from':{'id':123},'message':{'message_id':77,'chat':{'id':123,'type':'private'}},'data':'water:yes'}})
        self.assertEqual(len(self.db.waters()),1)
    def test_historical_water_confirms_entered_time(self):
        self.db.water('newer',1795348800)
        self.bot.handle(self.update('/watered 2026-11-20 12:00'))
        self.assertIn('20.11.2026 12:00',self.tg.sent[-1])

if __name__=='__main__': unittest.main()
