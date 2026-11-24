"""Explicit voice controls share the same store as Telegram; never actuate hardware."""
from dataclasses import asdict
from datetime import datetime
import re
import time
from character import CharacterReply, plain_speech
from core import MOSCOW
from spoken import readings_speech, watering_speech

def voice_control(brain,event,now=None):
    text=re.sub(r'[,.!?;:—–-]+',' ',event.text.casefold().replace('ё','е'))
    text=' '.join(text.split())
    read={'показатели','показания','какие показатели','какие показания','сколько света','какая влажность почвы'}
    exact={'точные показания','показания точно','показания подробно'}
    read |= exact
    history={'история поливов','когда тебя поливали','когда был последний полив','когда меня поливали','когда был полив'}
    pause={'пауза','поставь напоминания на паузу','отключи напоминания','замолчи с напоминаниями'}
    resume={'верни напоминания','включи напоминания','возобнови напоминания'}
    watered={'я полил','я тебя полил','я полил растение','полил'}
    confirm={'подтверждаю полив'}
    cancel={'отмена','отмени полив'}
    pump={'полей','полей растение','полей себя','включи полив'}
    if text not in read|history|pause|resume|watered|confirm|cancel|pump: return None
    key='voice-control:'+event.source+':'+event.request_id
    with brain.control_lock:
        now=time.time() if now is None else now
        cached=brain.store.cached_reply(key)
        if cached: return CharacterReply(**cached)
        store=brain.store; pending_key='voice_water_pending:'+event.source
        speech=None
        if text in read:
            from bot import PlantBot
            snapshot=store.snapshot(now)
            answer=PlantBot({},store,None,brain).readings(snapshot)
            speech=readings_speech(snapshot,precise=text in exact)
        elif text in history:
            waters=store.waters(1)
            speech=watering_speech(waters,now)
            answer=('Последний полив помню: '+datetime.fromtimestamp(waters[0]['at'],MOSCOW).strftime('%d.%m.%Y в %H:%M')+' по Москве. Лейку пока можно отставить.' if waters else 'Прошлых поливов в памяти пока нет, кожаный.')
        elif text in pump:
            answer='Насоса у меня нет, кожаный. Сам себя полить не могу; сначала проверь грунт и пришли фото в Telegram.'
        elif event.metadata.get('speaker')!='Егор':
            answer='Такие распоряжения оставим Егору. Саймон, ты пока за разговор отвечаешь.'
        elif text in pause|resume:
            store.set('reminders_paused',text in pause)
            answer='Ладно, сам напоминать пока не буду. На разговор я всё ещё согласен.' if text in pause else 'Вернул себе право напомнить об уходе, хозяин.'
            brain.remember('reminders_changed',{'paused':text in pause,'source':event.source},key)
        elif text in watered:
            store.set(pending_key,{'request_id':event.request_id,'expires':now+60})
            answer='Уже полил, кожаный? Тогда скажи: «Саймон, Стёпа, подтверждаю полив». Пока только уточняю, в историю не записал.'
        elif text in cancel:
            store.set(pending_key,None); answer='Отменили запись, понял. Лейку в историю не вписываю.'
        else:
            pending=store.get(pending_key)
            if not pending or not now<=pending['expires']:
                store.set(pending_key,None); answer='Подтверждать сейчас нечего. После настоящего полива скажи: «Саймон, Стёпа, я полил».'
            else:
                water_id='voice-water:'+event.source+':'+pending['request_id']
                changed=store.water(water_id,now); store.set(pending_key,None)
                brain.remember('watered',{'source':event.source,'at':now},water_id)
                answer='Полив запомнил, хозяин. Теперь дай корням спокойно пожить.' if changed else 'Этот полив уже помню. Второй раз одну лейку не считаем.'
        store.chat('user','['+event.source+'] '+event.text); store.chat('assistant',answer)
        reply=CharacterReply(answer,speech if speech is not None else plain_speech(answer),'деловитый',event.request_id,event.source)
        store.save_reply(key,asdict(reply))
        return reply
