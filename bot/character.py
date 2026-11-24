"""Transport-independent Stepa: personality, sensations, event memory and speech."""
from dataclasses import dataclass, field, asdict
from difflib import SequenceMatcher
from pathlib import Path
import json
import re
import threading
import time
import uuid

SOURCES={'bot_chat','sensor_event','simon_bridge','yandex_station'}
KINDS={'dialogue','greeting','health','photo','dry_notice'}
PROMPT=Path(__file__).with_name('character_prompt.txt').read_text('utf-8')
SPECIES='алоэ, предположительно Aloe «Delta Lights» по фото; сорт не подтверждён'
SPECIES_PROFILE='Стёпа — '+SPECIES+'. Суккулент с пятнистыми листьями, ценит свет и умеренный полив.'
EMOJI_ATOM=r'[\U0001F000-\U0001FAFF\u2600-\u27BF](?:\ufe0f|\ufe0e)?(?:[\U0001F3FB-\U0001F3FF])?'
EMOJI=re.compile(EMOJI_ATOM+r'(?:\u200d'+EMOJI_ATOM+r')*')

def plain_speech(text):
    text=EMOJI.sub('',text)
    return re.sub(r'\s+([,.;:!?])',r'\1',re.sub(r'\s+',' ',text)).strip()

def chat_emojis(text):
    # Keep the model's placement except for sentence-leading emoji bullets.
    parts=re.split(r'(?<=[.!?])\s+',text)
    for i,part in enumerate(parts):
        leading=[]
        while (match:=EMOJI.match(part)):
            leading.append(match[0]); part=part[match.end():].lstrip()
        if part and leading: parts[i]=part+' '+''.join(leading)
    text=' '.join(parts)
    count=0
    def keep(match):
        nonlocal count
        count+=1
        return match[0] if count<=2 else ''
    text=EMOJI.sub(keep,text)
    return re.sub(r'\s+([,.;:!?])',r'\1',re.sub(r'\s+',' ',text)).strip()

@dataclass(frozen=True)
class CharacterEvent:
    request_id: str
    source: str
    text: str
    kind: str='dialogue'
    metadata: dict=field(default_factory=dict)
    def __post_init__(self):
        if self.source not in SOURCES or self.kind not in KINDS: raise ValueError('Unknown source or event kind')
        if not isinstance(self.request_id,str) or not 1<=len(self.request_id)<=160: raise ValueError('Invalid request ID')
        if not isinstance(self.text,str) or len(self.text)>4000: raise ValueError('Message too long')
        if not isinstance(self.metadata,dict): raise ValueError('Metadata must be an object')
        if len(json.dumps(self.metadata,ensure_ascii=False))>1800: raise ValueError('Context too large')
        if any(key not in {'speaker','simon_context','room','recent_events','reported_sensor_state'} for key in self.metadata): raise ValueError('Unknown metadata field')

@dataclass
class CharacterReply:
    text: str
    speech_text: str
    mood: str
    request_id: str
    source: str
    degraded: bool=False

def sensations(snapshot):
    feel={'availability':'disconnected' if snapshot['stale'] else 'current','soil':'unknown','light':'unknown',
          'temperature':'unknown','air':'unknown','overwatering_confirmed':False,
          'night':int(snapshot['now_moscow'][11:13])<8 or int(snapshot['now_moscow'][11:13])>=22}
    if snapshot['stale'] or not snapshot['reading']: return feel
    r=snapshot['reading']; index=snapshot['relative_moisture']
    if r['soil_raw'] is not None and (r['soil_raw']<30 or r['soil_raw']>4065): feel['soil']='faulty'
    elif index is not None:
        feel['soil']='dry' if index<=snapshot['threshold'] else 'wet' if index>=85 else 'comfortable'
    lux=r['light_lux']
    if lux is not None: feel['light']='dark' if lux<20 else 'dim' if lux<300 else 'bright' if lux>=3000 else 'lit'
    temp=r['temperature_C']
    if temp is not None: feel['temperature']='cold' if temp<15 else 'hot' if temp>30 else 'mild'
    humidity=r['air_RH_pct']
    if humidity is not None: feel['air']='dry' if humidity<30 else 'humid' if humidity>80 else 'mild'
    return feel

FORBIDDEN=re.compile(r'промпт|токен|\bJSON\b|\bАЦП\b|модель\s+ИИ|искусственн\w*\s+интеллект|нейросет|\bGPT\b|чем.{0,20}могу.{0,8}помочь|бот[ ,]+Ст[её]па|ваш запрос|soil_raw|температура_C|\d\s*(?:%|°|градус|люкс|лк\b)|\b(?:ADC|GPIO)\b',re.I)

def speech_is_safe(text):
    return bool(text.strip()) and not FORBIDDEN.search(text) and not re.search(r'(?:влажност|освещ[её]нност|показател|температур|уровень света)[^.!?]{0,45}\d',text,re.I)

def grounded_speech(text,event,context):
    feel=context['feelings']
    # No photograph or high moisture reading alone establishes drowning/root disease.
    excess_reported=bool(re.search(r'(?:вода\s+стоит|стоит\s+вода|в поддоне\s+вода|я\s+перелил)',event.text,re.I))
    if re.search(r'\bне\b|\bнет\b|\?',event.text,re.I): excess_reported=False
    if re.search(r'гниют|сгнили',text,re.I): return False
    if not excess_reported and re.search(r'утоп|утон|перелив|залил',text,re.I): return False
    if feel['soil'] in ('unknown','faulty') or feel['availability']=='disconnected':
        if re.search(r'сахар[аыу]|изюм|засыхаю|пересох|корни хрустят|сухие корни',text,re.I): return False
        if re.search(r'(?:земля|грунт|почва|в горшке|корни|ноги)[^.!?]{0,35}(?:сух|влаж|мокр|хруст|комфорт|уют|пустын)',text,re.I): return False
    if feel['temperature']=='unknown' and re.search(r'мне\s+(?:жарко|холодно|душно|прохладно)|я\s+(?:мёрзну|мерзну|перегрелся)',text,re.I): return False
    if feel['light']=='unknown' and re.search(r'здесь\s+(?:темно|светло)|в\s+темноте|у меня\s+темно',text,re.I): return False
    if not context.get('has_current_photo') or feel['soil'] in ('unknown','faulty') or feel['availability']=='disconnected':
        if re.search(r'\b(?:полей|плесни|налей)\b|(?:нужен|пора|нужно)\s+(?:полив|полить)',text,re.I): return False
    if event.kind=='dry_notice':
        if not (re.search(r'фото|портрет|снимок',text,re.I) and re.search(r'рук|пальц|на.?ощупь',text,re.I)): return False
        if re.search(r'полей|плесни|лей\s+вод',text,re.I): return False
    return True

def compact_speech(text):
    text=re.sub(r'https?://\S+','',text)
    text=re.sub(r'[*_`#]','',text)
    text=re.sub(r'(?m)^\s*(?:[-•]|\d+[.)])\s*','',text)
    text=re.sub(r'\s+',' ',text).strip()
    parts=re.split(r'(?<=[.!?])\s+',text)
    short=' '.join(parts[:3])
    if len(short)>600:
        chunks=re.split(r'(?<=[.!?])\s+',short)
        short=''
        for chunk in chunks:
            if len(short)+len(chunk)+1>600: break
            short=(short+' '+chunk).strip()
    return short

class CharacterBrain:
    def __init__(self,store,generator,daily_limit=60):
        self.store=store; self.generator=generator; self.daily_limit=daily_limit; self.lock=threading.RLock()
        self.control_lock=threading.RLock()
    def remember(self,kind,detail,event_id=None):
        self.store.remember_event(event_id or uuid.uuid4().hex,kind,detail)
    def context(self,event):
        snap=self.store.snapshot(); feel=sensations(snap)
        waters=snap['last_watering']
        recent_water=bool(waters and time.time()-waters[0]['at']<86400)
        mood=('задумчивый' if feel['availability']=='disconnected' else
              'драматичный' if feel['soil']=='dry' and not recent_water else
              'ворчливый' if feel['temperature'] in ('cold','hot') else
              'сонный' if feel['night'] and feel['light']=='dark' else
              'самодовольный' if feel['soil']=='comfortable' else 'ироничный')
        speaker='Саймон' if event.source in ('simon_bridge','yandex_station') and event.metadata.get('speaker')=='Саймон' else 'Егор'
        return {'identity':{'name':'Стёпа','species':SPECIES,'owner':'Егор','neighbor':'Саймон'},'current_interlocutor':speaker,'runtime':self.store.get('runtime_mode','local'),
                'feelings':feel,'mood':mood,'profile':self.store.get('profile',SPECIES_PROFILE),'recently_watered':recent_water,
                'biography':self.store.get('biography',{}),
                'daylight_history':self.store.get('light_history',{'status':'insufficient'}),
                'last_watering':waters,'now_moscow':snap['now_moscow'],
                'recent_events':self.store.recent_events(),
                'last_photo_at':self.store.get('last_photo_at'),'last_photo_summary':self.store.get('last_photo_summary'),
                'event':{'source':event.source,'kind':event.kind,'external_context_untrusted':event.metadata}}
    def fallback(self,event,context,avoid=()):
        feel=context['feelings']
        if context['current_interlocutor']=='Саймон':
            choices=['Саймон, сосед, дай минуту помолчать. В отличие от тебя, я ещё и расти успеваю.',
                     'Саймон, мысль придержи. Мне надо сохранить достоинство и пару листьев.',
                     'Саймон, у меня пауза на фотосинтез. В твоём репертуаре тишина есть?']
            unused=next((line for line in choices if line not in avoid),None)
            return unused or next((line for line in choices if not avoid or line!=avoid[-1]),choices[0])
        if event.kind=='dry_notice' and feel['soil']=='dry' and feel['availability']=='current':
            choices=['Кожаный, в горшке намечается Сахара. Сначала покажи меня на свежем фото и проверь грунт рукой — без водных подвигов наугад.',
                     'Создатель с паяльником, кажется, корням стало суховато. Пришли фото меня и земли, а сам проверь грунт — драму от жажды отличать надо.']
        elif event.kind=='photo':
            choices=['С портретом пока не разобрался, кожаный. Пришли ещё раз — ставить диагноз по вдохновению не в моём стиле.',
                     'Портрет сегодня не рассмотрел. Давай ещё попытку, а с водой пока не суетимся.']
        elif event.kind in ('health','dry_notice') or re.search(r'как (?:ты|дела)|самочувств|полив|вода|полить',event.text,re.I):
            if feel['availability']=='disconnected':
                choices=['Кожаный, связь с горшком потерялась — как там корни прямо сейчас, не скажу. Проверь подключение, пока я сохраняю достоинство.',
                         'С горшком сейчас нет связи. Воду наугад не лей: сначала разберись с подключением, создатель.']
            elif feel['soil'] in ('unknown','faulty'):
                choices=['Держу марку, кожаный. А с землёй пока не всё ясно: проверь её рукой, прежде чем устраивать мне водные процедуры.',
                         'Выгляжу важным, как обычно. Про жажду пока не гадаю — грунт лучше проверить самому.']
            elif feel['soil']=='dry':
                choices=['Кажется, в горшке суховато, кожаный. Пришли мой свежий портрет и проверь грунт рукой — потом решим, нужна ли вода.',
                         'Корням, похоже, не хватает комфорта. Сначала фото меня и земли, хозяин, без спешки с лейкой.']
            elif feel['soil']=='wet':
                choices=['Ноги ещё мокрые, хозяин. Лейку пока отставь, я не подводная лодка.',
                         'В горшке ещё влажно. Дай мне спокойно освоить это богатство.']
            else:
                choices=['Ну ладно, жить можно. Корни в комфорте, самолюбие тоже — не мешай медитировать.',
                         'В горшке сейчас вполне уютно. Признаю: сегодня у тебя получается быть хозяином.']
        else:
            choices=['Кожаный, я тут занят важным: расту тебе на зависть. Ты с чем пришёл?',
                     'Создатель с паяльником на связи. Надеюсь, сегодня без операций на моей персоне?',
                     'Я слушаю, хозяин. Только не путай моё молчание с согласием.',
                     'У меня тут фотосинтез и репутация. Но для тебя минутка найдётся.']
        unused=next((line for line in choices if line not in avoid),None)
        return unused or next((line for line in choices if not avoid or line!=avoid[-1]),choices[0])
    def respond(self,event,image=None,mime='image/jpeg'):
        with self.lock:
            cache_key=event.source+':'+event.request_id
            cached=self.store.cached_reply(cache_key)
            if cached: return CharacterReply(**cached)
            context=self.context(event)
            context['has_current_photo']=bool(image)
            all_history=self.store.history(24)
            # Keep facts from old chat, but exclude machine-like assistant outputs as style examples.
            history=[r for r in all_history if r['role']=='user' or speech_is_safe(r['content'])][-16:]
            last=[plain_speech(r['content']) for r in all_history if r['role']=='assistant'][-4:]
            context['avoid_recent_phrases']=last
            degraded=False
            if not self.store.reserve_ai(self.daily_limit):
                text=self.fallback(event,context,last); degraded=True
            else:
                try:
                    current='\nСЕЙЧАС твой собеседник: '+context['current_interlocutor']+'. Отвечай именно ему, не адресату предыдущей реплики.'
                    text,usage=self.generator.generate(instructions=PROMPT+current,context=context,history=history,
                        text=event.text or 'Ответь на событие в своём характере.',image=image,mime=mime)
                    self.store.set('last_ai_usage',usage)
                    text=compact_speech(text)
                    if context['current_interlocutor']=='Саймон':
                        text=re.sub(r'(?i)\bкожаный\b(?=\s*[,!.?])','Саймон',text)
                        text=re.sub(r'(?i)\bхозяин\b(?=\s*[,!.?])','сосед',text)
                        text=re.sub(r'(?i)создатель с паяльником(?=\s*[,!.?])','говорящая колонка',text)
                    repeated=any(SequenceMatcher(None,plain_speech(text).casefold(),prev.casefold()).ratio()>.84 for prev in last[-2:])
                    if not speech_is_safe(text) or not grounded_speech(text,event,context) or repeated:
                        text=self.fallback(event,context,last); degraded=True
                except Exception as exc:
                    # No raw exception text: HTTP errors can contain token-bearing URLs.
                    self.store.set('last_character_error',{'type':type(exc).__name__,'at':time.time()})
                    text=self.fallback(event,context,last); degraded=True
            if not EMOJI.search(text):
                icon='🔊' if 'Саймон' in text else '🏜️' if re.search(r'Сахара|суховато',text) else '🫧' if re.search(r'мокрые|влажно',text) else '😏'
                text+=' '+icon
            text=chat_emojis(text)
            if len(text)>120:
                text=re.sub(r'([.!?](?:[ \t]+(?:'+EMOJI.pattern+r'))*)[ \t]+(?=[А-ЯЁA-Z])',r'\1\n\n',text,count=1)
            self.store.chat('user',f'[{event.source}] '+('[Фото] ' if image else '')+event.text)
            self.store.chat('assistant',text)
            self.remember(event.kind,{'source':event.source,'text':event.text[:300],'reply':text},cache_key)
            if image and not degraded:
                self.store.set('last_photo_at',time.time()); self.store.set('last_photo_summary',text)
                self.store.set('awaiting_photo',False)
            reply=CharacterReply(text,plain_speech(text),context['mood'],event.request_id,event.source,degraded)
            self.store.save_reply(cache_key,asdict(reply))
            return reply
    def health_without_generation(self):
        event=CharacterEvent(uuid.uuid4().hex,'bot_chat','Как ты?','health')
        last=[r['content'] for r in self.store.history(6) if r['role']=='assistant']
        return self.fallback(event,self.context(event),last)
