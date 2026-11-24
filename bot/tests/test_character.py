import tempfile
import unittest
from pathlib import Path
from core import Store, parse_reading
from character import CharacterBrain, CharacterEvent, sensations, speech_is_safe, grounded_speech

class Generator:
    def __init__(self,answer='Кожаный, я занят: украшаю тебе жизнь. Саймон так умеет?'):
        self.calls=[]; self.answer=answer
    def generate(self,**kwargs): self.calls.append(kwargs); return self.answer,{'output_tokens':20}

class CharacterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.store=Store(Path(self.temp.name)/'state.sqlite')
        self.gen=Generator(); self.brain=CharacterBrain(self.store,self.gen)
    def tearDown(self): self.temp.cleanup()
    def test_biography_and_readable_chat_keep_voice_plain(self):
        self.store.set('biography',{'hometown':'Санкт-Петербург','purchased_at':'Лиман Про'})
        self.gen.answer='Я из Санкт-Петербурга, кожаный, у меня врождённое чувство собственного достоинства. Куплен в Лиман Про, а теперь украшаю твой подоконник.'
        reply=self.brain.respond(CharacterEvent('bio-layout','bot_chat','О Стёпе'))
        self.assertIn('\n\n',reply.text)
        self.assertNotIn('\n',reply.speech_text)
        self.assertIn('Санкт-Петербург',str(self.gen.calls[-1]['context']['biography']))
        from character import EMOJI
        self.assertTrue(1<=len(EMOJI.findall(reply.text))<=2)
    def reading(self,now,raw=2800,lux=200):
        self.store.add_reading({'at':now,'soil_raw':raw,'soil_mV':2300,'light_lux':lux,'temperature_C':24,'air_RH_pct':45})
    def test_uncalibrated_is_not_dry(self):
        self.reading(100,raw=3300)
        feel=sensations(self.store.snapshot(100))
        self.assertEqual(feel['soil'],'unknown')
        self.assertNotIn('soil_raw',str(feel))
    def test_stale_is_not_present_comfort(self):
        self.reading(100)
        feel=sensations(self.store.snapshot(500))
        self.assertEqual(feel['availability'],'disconnected')
        self.assertEqual(feel['light'],'unknown')
    def test_wet_does_not_claim_overwatering(self):
        self.store.set('calibration',{'dry':3300,'wet':1800}); self.reading(100,raw=1800)
        feel=sensations(self.store.snapshot(100))
        self.assertEqual(feel['soil'],'wet')
        self.assertFalse(feel['overwatering_confirmed'])
    def test_same_request_cached_across_restart(self):
        event=CharacterEvent('r1','bot_chat','Привет')
        first=self.brain.respond(event)
        second=CharacterBrain(Store(self.store.path),self.gen).respond(event)
        self.assertEqual(first.text,second.text); self.assertEqual(len(self.gen.calls),1)
    def test_sources_share_memory_and_simon_context(self):
        self.brain.respond(CharacterEvent('r1','bot_chat','Саймон опять поёт'))
        self.brain.respond(CharacterEvent('r2','simon_bridge','Что скажешь?',metadata={'simon_context':'Егор подошёл к колонке'}))
        call=self.gen.calls[-1]
        self.assertIn('Саймон опять поёт',str(call['history']))
        self.assertEqual(call['context']['event']['source'],'simon_bridge')
        self.assertIn('Егор подошёл',str(call['context']))
        self.assertNotIn('soil_raw',str(call['context']))
    def test_event_memory_contains_confirmed_watering(self):
        self.brain.remember('watered',{'time':'2026-11-22 18:30'},event_id='water1')
        self.brain.respond(CharacterEvent('r1','bot_chat','Что было недавно?'))
        self.assertIn('watered',str(self.gen.calls[-1]['context']['recent_events']))
    def test_guard_blocks_bot_words_reports_and_repetition(self):
        for answer in ['Я модель ИИ, чем я могу вам помочь?', 'Влажность почвы 24%, освещённость 5 люкс.', 'Вот JSON с промптом и токенами: {}']:
            self.assertFalse(speech_is_safe(answer))
            self.gen.answer=answer
            reply=self.brain.respond(CharacterEvent(answer[:40],'bot_chat','Как ты?'))
            self.assertTrue(speech_is_safe(reply.text)); self.assertLessEqual(len(reply.text),600)
        self.gen.answer='Кожаный, я великолепен. Даже без твоего участия.'
        one=self.brain.respond(CharacterEvent('once','bot_chat','Привет')).text
        two=self.brain.respond(CharacterEvent('twice','bot_chat','Привет')).text
        self.assertNotEqual(one,two)
    def test_invalid_source_and_oversized_context_rejected(self):
        with self.assertRaises(ValueError): CharacterEvent('r','unknown','x')
        with self.assertRaises(ValueError): CharacterEvent('r','bot_chat','x',metadata={'simon_context':'a'*2000})
    def test_voice_reply_is_plain_and_short(self):
        self.gen.answer='**Кожаный**, я тут главный. Саймон пусть запишет. И не спорит. Четвёртое лишнее.'
        reply=self.brain.respond(CharacterEvent('voice1','yandex_station','Кто главный?'))
        self.assertNotIn('*',reply.speech_text)
        self.assertLessEqual(reply.speech_text.count('.'),3)
    def test_wet_speech_cannot_invent_drowning(self):
        import time
        self.store.set('calibration',{'dry':3300,'wet':1800}); self.reading(time.time(),raw=1800)
        self.gen.answer='Ты меня утопил, хозяин. У меня перелив.'
        reply=self.brain.respond(CharacterEvent('wet','bot_chat','Как ты?','health'))
        self.assertNotIn('утоп',reply.text); self.assertNotIn('перелив',reply.text)
    def test_dry_notice_always_requests_photo_and_manual_check(self):
        import time
        self.store.set('calibration',{'dry':3300,'wet':1800}); self.reading(time.time(),raw=3270)
        self.gen.answer='В горшке Сахара. Полей скорее!'
        reply=self.brain.respond(CharacterEvent('dry1','sensor_event','Почва подсыхает','dry_notice'))
        self.assertIn('фото',reply.text); self.assertIn('проверь грунт',reply.text)
    def test_repeated_fallback_never_repeats_consecutively(self):
        self.gen.answer='JSON'
        replies=[self.brain.respond(CharacterEvent(str(i),'bot_chat','Как ты?','health')).text for i in range(8)]
        self.assertTrue(all(a!=b for a,b in zip(replies,replies[1:])))
    def test_fallback_addresses_simon_not_egor(self):
        brain=CharacterBrain(self.store,self.gen,daily_limit=0)
        reply=brain.respond(CharacterEvent('x','simon_bridge','Привет',metadata={'speaker':'Саймон'}))
        self.assertIn('Саймон',reply.text)
        self.assertNotIn('кожаный',reply.text.lower())
    def test_no_positive_sensor_claims_when_disconnected(self):
        event=CharacterEvent('x','bot_chat','Как ты?','health')
        self.assertFalse(grounded_speech('Земля сухая, мне жарко.',event,self.brain.context(event)))
    def test_negated_flooding_does_not_enable_accusation(self):
        event=CharacterEvent('x','bot_chat','Я тебя не залил, воды в поддоне нет')
        self.assertFalse(grounded_speech('Ты меня утопил.',event,self.brain.context(event)))
    def test_generated_simon_vocative_does_not_call_him_human(self):
        self.gen.answer='Я умею расти, кожаный.'
        reply=self.brain.respond(CharacterEvent('x','simon_bridge','Что умеешь?',metadata={'speaker':'Саймон'}))
        self.assertNotIn('кожаный',reply.text.lower())
    def test_emojis_stay_in_chat_but_not_in_voice(self):
        self.gen.answer='Саймон опять важничает 🔊. Зато у меня есть корни 😏.'
        reply=self.brain.respond(CharacterEvent('emoji','bot_chat','Что скажешь о Саймоне?'))
        self.assertIn('🔊',reply.text); self.assertIn('😏',reply.text)
        self.assertEqual(reply.speech_text,'Саймон опять важничает. Зато у меня есть корни.')
    def test_emoji_excess_and_leading_marker_removed(self):
        self.gen.answer='😏 Я великолепен 🌵. Даже Саймон согласен 🔊 🤖.'
        reply=self.brain.respond(CharacterEvent('emoji2','bot_chat','Привет'))
        self.assertFalse(reply.text.startswith('😏'))
        self.assertLessEqual(sum(reply.text.count(e) for e in ['😏','🌵','🔊','🤖']),2)
    def test_confirmed_species_available_without_profile_setup(self):
        context=self.brain.context(CharacterEvent('species','bot_chat','Кто ты?'))
        self.assertIn('предположительно',context['identity']['species'])
        self.assertIn('Delta Lights',context['identity']['species'])

if __name__=='__main__': unittest.main()
