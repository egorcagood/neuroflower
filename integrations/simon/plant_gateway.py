"""Explicit Simon -> Stepa route. No microphone, player, arbitrary URL or secret logs."""
import json
from pathlib import Path
import re
import urllib.request
import uuid
import time,os
from .plant_audio import CancellableCall, CallCancelled

NAME=r'(?:семен(?:а|у|ом|е)?|степ(?:а|е|у|ы|ой)|степан(?:а|у|ом|е)?|цвет(?:ок|ка|ку|ком|ке))'

def plant_question(text):
    text=' '.join(text.casefold().replace('ё','е').split()).strip(' ,.!?')
    # Observed Vosk transcription of "спроси у цветка": "спросил цветка".
    # Accept that phonetic error only for questions, never state-changing orders.
    heard=re.fullmatch(r'спросил\s+(?:у\s+)?'+NAME+r'\b\s*[,,:-]?\s*(.*)',text)
    if heard:
        question=heard[1]
        return question if re.match(r'(?:как|что|когда|сколько|почему|зачем|кто|где|расскажи|привет|показания|показатели)\b',question) else None
    match=re.fullmatch(r'(?:спроси|скажи|попроси|передай)\s+(?:у\s+)?'+NAME+r'\b\s*[,,:-]?\s*(.*)',text)
    if not match: match=re.fullmatch(NAME+r'\b\s*[,,:-]?\s*(.*)',text)
    if match: return match[1] or 'как ты себя чувствуешь?'
    if re.fullmatch(r'(?:как(?: там)?|что с|что со)\s+'+NAME,text): return 'как ты себя чувствуешь?'
    if re.fullmatch(r'(?:какие |покажи )?(?:показания|показатели)(?: у)?\s+'+NAME,text): return 'показания'
    if re.fullmatch(r'когда (?:поливали|был полив у)\s+'+NAME,text): return 'история поливов'
    return None

class PlantGateway:
    def __init__(self,send): self.send=send; self._call=CancellableCall()
    def answer(self,text,guard=lambda:True):
        diagnostic_once(text)
        question=plant_question(text)
        if question is None or not guard(): return None
        body={'request_id':'simon-'+uuid.uuid4().hex,'source':'simon_bridge','text':question,
              'metadata':{'speaker':'Егор','room':'Яндекс Станция'}}
        try:
            response=self._call.run(lambda:self.send(body),guard)
            speech=response.get('speech_text') if isinstance(response,dict) else None
            if not isinstance(speech,str) or not speech.strip() or len(speech)>600: raise ValueError('invalid_reply')
        except CallCancelled:
            return None
        except Exception:
            speech='Не удалось связаться со Стёпой. Попробуй спросить его чуть позже или напиши в Telegram.'
        return speech if guard() else None

def diagnostic_once(text,root=Path('/run/steve-voice')):
    """Opt-in one test phrase in private no-swap RAM; never audio or journal text."""
    flag=root/'plant-debug-once.json'; result=root/'plant-debug-result.json'
    try:
        if result.exists() and time.time()-result.stat().st_mtime>180: result.unlink()
        if not flag.exists(): return
        expires=json.loads(flag.read_text('utf-8'))['expires']
        if not time.time()<expires<=time.time()+180:
            flag.unlink(); return
        folded=text.casefold().replace('ё','е')
        if len(text)>160 or 'спрос' not in folded or 'дел' not in folded: return
        flag.unlink()
        fd=os.open(result,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f: json.dump({'text':text,'at':time.time()},f,ensure_ascii=False)
    except (OSError,ValueError,KeyError,TypeError): pass

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs): return None

def load_plant(path=Path('/etc/steve/plant-gateway.json')):
    if not path.exists(): return None
    config=json.loads(path.read_text('utf-8'))
    endpoint=config['endpoint']; token=config['token']
    # The two services live on the same server. Never forward this bearer elsewhere.
    if endpoint!='http://127.0.0.1:8798/v1/character/events': raise ValueError('local_plant_endpoint_required')
    if not isinstance(token,str) or not 32<=len(token)<=256 or any(c.isspace() for c in token): raise ValueError('invalid_plant_token')
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
    def send(body):
        request=urllib.request.Request(endpoint,json.dumps(body,ensure_ascii=False).encode('utf-8'),
            {'Authorization':'Bearer '+token,'Content-Type':'application/json'})
        with opener.open(request,timeout=25) as response:
            raw=response.read(16385)
            if len(raw)>16384: raise ValueError('plant_reply_too_large')
            return json.loads(raw)
    return PlantGateway(send)
