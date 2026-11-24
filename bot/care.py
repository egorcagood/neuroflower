"""Conservative, persistent care scheduling. Missing readings are not darkness."""
from datetime import datetime, timedelta
from statistics import median
import time
from core import MOSCOW, reminder_due

def light_history(store,now=None):
    now=time.time() if now is None else now
    midnight=datetime.fromtimestamp(now,MOSCOW).replace(hour=0,minute=0,second=0,microsecond=0)
    days=[]
    rows=store.samples((midnight-timedelta(days=2)).timestamp())
    for offset in (2,1):
        start=(midnight-timedelta(days=offset)).replace(hour=9).timestamp()
        bins={}
        for row in rows:
            at=row['at']; lux=row.get('light_lux')
            if lux is not None and start<=at<start+9*3600:
                bins.setdefault(int((at-start)//600),[]).append((at,lux))
        # Six distinct minutes spanning five minutes; bursts/duplicates cannot fill a day.
        valid={k:median(v for _,v in points) for k,points in bins.items()
               if len({int(t//60) for t,_ in points})>=6 and max(t for t,_ in points)-min(t for t,_ in points)>=300}
        gaps=[]; previous=-1
        for index in sorted(valid): gaps.append(index-previous-1); previous=index
        gaps.append(54-previous-1)
        covered=len(valid)>=44 and max(gaps)<=6
        dim=covered and median(valid.values())<300 and sum(v>=3000 for v in valid.values())<6
        days.append({'date':datetime.fromtimestamp(start,MOSCOW).date().isoformat(),
                     'covered':covered,'observed_minutes':len(valid)*10,'low':bool(dim)})
    status='insufficient' if not all(d['covered'] for d in days) else 'low' if all(d['low'] for d in days) else 'not_low'
    return {'status':status,'days':days,'evaluated_at':now,'rule':'preliminary_daylight_check_v1'}

def next_notice(store,now=None):
    now=time.time() if now is None else now
    if not store.get('owner_started') or store.get('reminders_paused',False): return None
    if not 8<=datetime.fromtimestamp(now,MOSCOW).hour<22: return None
    if now-max(store.get('last_care_notice',0),store.get('last_reminder',0))<86400: return None
    if reminder_due(store,now):
        return {'kind':'dry_notice','text':'Кожаный, в горшке намечается Сахара. Пришли свежее фото меня и грунта, а землю проверь рукой — прежде чем хвататься за лейку. 🏜️'}
    if not store.snapshot(now)['stale']:
        report=store.get('light_history',{})
        if now-report.get('evaluated_at',0)>900:
            report=light_history(store,now); store.set('light_history',report)
        if report.get('status')=='low' and now-store.get('last_light_notice',0)>=3*86400:
            return {'kind':'light_notice','text':'Кожаный, два последних дня даже днём было подозрительно сумрачно. Проверь, не закрыто ли окно, и покажи на фото, где я стою — роль подвального философа мне тесновата. ☀️', 'evidence':report}
    started=store.get('care_started_at')
    if started is None:
        store.set('care_started_at',now); started=now
    interval=store.get('photo_interval_days',7)
    if interval and now-max(started,store.get('last_photo_at',0),store.get('last_photo_request',0))>=interval*86400:
        return {'kind':'photo_notice','text':'Кожаный, пора обновить мой парадный портрет. Пришли в Telegram фото целиком и поближе листья с грунтом — посмотрим, как я выгляжу; лейка в комплект не входит. 🌵'}
    return None

def notice_sent(store,notice,now=None):
    now=time.time() if now is None else now
    store.set('last_care_notice',now)
    store.set('last_photo_request',now); store.set('awaiting_photo',True)
    if notice['kind']=='dry_notice': store.set('last_reminder',now)
    if notice['kind']=='light_notice': store.set('last_light_notice',now)
    store.chat('assistant',notice['text'],now)
    store.remember_event('care:'+notice['kind']+':'+str(int(now)),notice['kind'],notice,now)

