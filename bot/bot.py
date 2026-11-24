import argparse
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import statistics
import threading
import time
from datetime import datetime
from pathlib import Path
from core import Store, MOSCOW, moisture, reminder_due
from adapters import Telegram, OpenAI, ServiceError
from sensors import start_sensors
from character import CharacterBrain, CharacterEvent
from character_gateway import start_character_gateway
from care import next_notice, notice_sent

WELCOME='''Кожаный, можешь просто со мной разговаривать или прислать портрет — желательно мой.
После полива жми «Я полил», мои условия проживания расскажи через /plant, а с землёй разберёмся через /calibrate.
Пока наша связь держится на твоём включённом компьютере: выключишь его — продолжим при встрече.'''

def stamp(at): return datetime.fromtimestamp(at,MOSCOW).strftime('%d.%m.%Y %H:%M МСК')

class PlantBot:
    def __init__(self,config,store,tg,brain): self.config=config; self.store=store; self.tg=tg; self.brain=brain
    def converse(self,text,ident,kind='dialogue',image=None,mime='image/jpeg'):
        self.tg.action()
        reply=self.brain.respond(CharacterEvent('telegram:'+str(ident),'bot_chat',text,kind),image,mime)
        self.tg.send(reply.text)
    def handle(self,update):
        ident=update['update_id']
        if ident<=self.store.get('last_update',-1): return
        callback=update.get('callback_query')
        msg=callback.get('message',{}) if callback else update.get('message',{})
        sender=callback.get('from',{}) if callback else msg.get('from',{})
        owner=self.config['owner_id']
        if sender.get('id')!=owner or msg.get('chat',{}).get('id')!=owner or msg.get('chat',{}).get('type')!='private':
            self.store.set('last_update',ident); return
        self.store.set('owner_started',True)
        if callback:
            self.tg.answer_callback(callback['id'])
            data=callback.get('data','')
            if data=='water:yes':
                self.record_water('confirm:'+str(msg.get('message_id',ident)))
            elif data=='water:no': self.tg.send('Лейку отставили, понял. Лишних подвигов мне не надо.')
        else:
            self.message(msg,ident)
        self.store.set('last_update',ident)
    def record_water(self,event,at=None):
        when=time.time() if at is None else at
        changed=self.store.water(event,when)
        if changed:
            self.brain.remember('watered',{'time_moscow':stamp(when)},event_id=event)
            answer='Так, полив запомнил: '+stamp(when)+'. Теперь дай корням спокойно пожить, хозяин. 💦'
            self.store.chat('assistant',answer); self.tg.send(answer)
        else: self.tg.send('Кожаный, этот полив я уже помню. Двойную награду за одну лейку не выдам.')
    def message(self,msg,ident):
        text=(msg.get('text') or msg.get('caption') or '').strip()
        command=text.split()[0].split('@')[0].lower() if text else ''
        if msg.get('photo'):
            try:
                self.tg.action()
                data,mime=self.tg.photo(msg['photo'][-1]['file_id'])
                self.converse(text or 'Вот твой свежий портрет. Как выглядишь, Стёпа?',ident,'photo',data,mime)
            except ServiceError as exc: self.service_error(exc)
            return
        if command=='/start':
            self.converse('Привет, Стёпа. Это Егор.',ident,'greeting'); return
        if command=='/help':
            welcome=WELCOME
            if self.store.get('runtime_mode','local')=='server':
                welcome=welcome.rsplit('\n',1)[0]+'\n\nМои разговоры живут на сервере. Сейчас горшок связан через USB: компьютер должен быть включён, подключён к интернету и не спать. 🌿'
            self.tg.send(welcome); return
        if command=='/cancel':
            self.store.set('awaiting_profile',False); self.tg.send('Анкету отложили. Давай просто поболтаем, кожаный.'); return
        if command=='/plant':
            description=text.partition(' ')[2].strip()
            if description: self.save_profile(description)
            else:
                self.store.set('awaiting_profile',True)
                self.tg.send('Расскажи, какого я вида, в каком горшке и грунте живу, есть ли отверстия снизу и где стою. Чего не знаешь — не выдумывай, хозяин; передумаешь заполнять моё досье — /cancel.')
            return
        if command=='/readings' or text in ('Показатели','Показания'):
            self.tg.send(self.readings()); return
        if self.store.get('awaiting_profile') and text and not text.startswith('/'):
            self.save_profile(text); return
        if command=='/status' or text=='Самочувствие':
            self.converse('Как ты себя чувствуешь сейчас?',ident,'health'); return
        if command=='/history' or text=='История поливов':
            rows=self.store.waters()
            self.tg.send('Помню водные процедуры. 💦\n\n'+'\n'.join(stamp(r['at']) for r in rows) if rows else 'Прошлых поливов в моей памяти пока нет, кожаный. 🌵\n\nПосле настоящего полива жми «Я полил».'); return
        if text.lower().rstrip('!.') in ('я полил','полил','полила','я полила') or command=='/watered':
            if command=='/watered' and len(text.split())>1:
                try:
                    at=datetime.strptime(text.partition(' ')[2],'%Y-%m-%d %H:%M').replace(tzinfo=MOSCOW).timestamp()
                    if not 0<at<=time.time()+60: raise ValueError()
                    self.record_water('tg:'+str(ident),at)
                except ValueError: self.tg.send('Формат: /watered 2026-11-22 18:30. Укажи московское время, не в будущем.')
            else: self.tg.send('Уже полил или пока только обещаешь, кожаный?',reply_markup={'inline_keyboard':[[{'text':'Да, полил','callback_data':'water:yes'},{'text':'Нет, отмена','callback_data':'water:no'}]]})
            return
        if text in ('О растении','О Стёпе'):
            self.converse('Расскажи немного о себе: откуда ты родом, где тебя купили, и добавь одну свою привычку. Бери биографию из памяти, не выдумывай.',ident); return
        if text=='Настройки':
            self.tg.send('Хочешь устроить мой быт, создатель?\n\nМоё досье: /plant\nРазобраться с землёй: /calibrate\nПорог просьбы о фото: /threshold 25\nПобыть без напоминаний: /pause\nВернуть напоминания: /resume\nВспомнить прошлый полив: /watered YYYY-MM-DD HH:MM\n\nОбычный портрет прошу раз в неделю. При сухой земле — отдельно, а о свете сужу по двум наблюдаемым дням. Ночью не дёргаю.'); return
        if command in ('/pause','/resume'):
            self.store.set('reminders_paused',command=='/pause')
            self.tg.send('Ладно, сам дёргать не буду. Но на разговор я всё ещё согласен.' if command=='/pause' else 'Вернул себе право пожаловаться, хозяин. Сначала убедимся, что с моим досье и землёй разобрались.'); return
        if command=='/threshold':
            try:
                value=int(text.split()[1]); assert 5<=value<=80
                self.store.set('threshold',value); self.tg.send('Договорились, порог просьбы о фото поменял. Это повод заглянуть в горшок, а не сразу хвататься за лейку.')
            except (ValueError,IndexError,AssertionError): self.tg.send('Укажи число от 5 до 80, например /threshold 25. Порог подбирается под растение и грунт.')
            return
        if command=='/calibrate':
            self.tg.send('Кожаный, различать сухую и влажную землю будем на моём грунте, не меняя глубину щупа; специально сушить меня до хруста не надо. Когда вручную убедишься, что пора поливать, подожди полминуты и отправь /dry; после обычного полива дай лишней воде стечь, дождись устойчивого состояния и отправь /wet. Верхнюю часть щупа с электроникой не мочи, а после смены грунта или глубины всё повторим.'); return
        if command in ('/dry','/wet'): self.calibrate(command[1:]); return
        if not text:
            self.tg.send('Кожаный, пока пиши буквами или присылай обычное фото. С голосом ещё разберёмся, когда Саймона подключишь.'); return
        if text.startswith('/'):
            self.tg.send('Таких заклинаний я не знаю, создатель. Загляни в «Настройки» или /help.'); return
        if len(text)>4000: self.tg.send('Раздели сообщение на части до 4000 символов.'); return
        try:
            self.converse(text,ident,'health' if text.lower() in ('как ты?','как ты','как дела?','как дела') else 'dialogue')
        except ServiceError as exc: self.service_error(exc)
    def save_profile(self,text):
        self.store.set('profile',text[:3000]); self.store.set('awaiting_profile',False)
        self.brain.remember('profile_updated',{'description':text[:500]})
        self.tg.send('Досье на мою персону запомнил. Если в нём были поливы, их запиши отдельно через «Я полил» — обещания с водой путать не будем.')
    def service_error(self,exc):
        logging.warning('AI/photo request failed: %s',str(exc))
        self.tg.send('Связь сегодня с характером похлеще моего. Попробуй ещё раз чуть позже, кожаный.')
    def status(self):
        return self.brain.health_without_generation()
    def readings(self,snapshot=None):
        snap=self.store.snapshot() if snapshot is None else snapshot; row=snap['reading']
        if not row: return 'Показатели 🌿\n\nПока нет измерений. Проверь питание платы и подключение.'
        def value(field,unit):
            number=row.get(field)
            return 'нет данных' if number is None else f'{number:.1f}'.rstrip('0').rstrip('.')+' '+unit
        raw=row.get('soil_raw'); index=snap['relative_moisture']
        if raw is None: soil='нет данных'
        elif raw<30 or raw>4065: soil='проверь датчик: показание у границы диапазона'
        elif index is None: soil='калибровка не настроена'
        else: soil=f'{index:g} % по калибровке'
        heading='Показатели 🌿'
        if snap['stale']: heading+='\n\nДанные устарели — свежих измерений нет.'
        lines=[heading,'',f'Почва: {soil}',f'Свет: {value("light_lux","лк")}',
               f'Температура воздуха: {value("temperature_C","°C")}',f'Влажность воздуха: {value("air_RH_pct","%")}',
               '',f'Измерено: {stamp(row["at"])}']
        if snap['last_watering']: lines.append('Последний полив: '+stamp(snap['last_watering'][0]['at']))
        if index is not None and raw is not None and 30<=raw<=4065:
            lines.extend(['','Почва: 0 % — сухая точка, 100 % — после полива. Это относительная шкала, не точный процент воды.'])
        return '\n'.join(lines)
    def calibrate(self,kind):
        now=time.time(); rows=self.store.samples(now-40)
        if self.store.snapshot(now)['stale'] or len(rows)<3 or rows[0]['at']>now-20:
            self.tg.send('Нужны хотя бы 30 секунд свежих устойчивых показаний. Пока точку калибровки не сохраняю.'); return
        values=[r['soil_raw'] for r in rows]
        if max(values)-min(values)>120:
            self.tg.send('Показания пока скачут. Подожди стабилизации и повтори команду.'); return
        candidate=dict(self.store.get('calibration',{})); candidate[kind]=statistics.median(values)
        if not 30<candidate[kind]<4065: self.tg.send('Показание близко к краю диапазона. Сначала нужно проверить датчик.'); return
        try: index=moisture(candidate[kind],candidate)
        except ValueError:
            self.tg.send('Не сходится, кожаный: сухая и влажная земля получились слишком похожими или перепутаны. Пока ничего не меняю — проверь грунт и положение щупа.'); return
        self.store.set('calibration',candidate)
        self.brain.remember('calibration_updated',{'point':kind,'complete':index is not None})
        self.tg.send(('Сухую' if kind=='dry' else 'Влажную')+' землю запомнил, хозяин.'+(' Теперь могу различать обе крайности, но здравый смысл не отменяем.' if index is not None else ' Осталось познакомиться со второй крайностью.'))
    def tick(self):
        notice=next_notice(self.store)
        if notice:
            self.tg.send(notice['text'])
            notice_sent(self.store,notice)

def acquire_lock(folder):
    handle=open(folder/'bot.lock','a+b')
    handle.seek(0); handle.write(b'0'); handle.flush(); handle.seek(0)
    try:
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        handle.close(); raise SystemExit('Bot already running')
    return handle

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); args=parser.parse_args()
    config=json.loads(Path(args.config).read_text('utf-8'))
    folder=Path(config['data_dir']); folder.mkdir(parents=True,exist_ok=True)
    lock=acquire_lock(folder)
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[RotatingFileHandler(folder/'bot.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')])
    store=Store(folder/'memory.sqlite'); tg=Telegram(config); ai=OpenAI(config)
    store.set('runtime_mode','local' if config.get('sensor_mode','serial')=='serial' else 'server')
    brain=CharacterBrain(store,ai,config.get('daily_ai_limit',60))
    me=tg.call('getMe')
    if me['username'].lower()!=config['bot_username'].lower(): raise SystemExit('Unexpected bot identity')
    if tg.call('getWebhookInfo').get('url'): raise SystemExit('Existing webhook: refusing to replace it')
    (folder/'bot.pid').write_text(str(os.getpid()))
    tg.call('setMyCommands',{'commands':[{'command':a,'description':b} for a,b in [('start','Позвать Стёпу'),('status','Как себя чувствует Стёпа'),('readings','Почва, свет, температура и влажность'),('plant','Досье на жителя подоконника'),('watered','Записать полив'),('history','Вспомнить поливы'),('calibrate','Разобраться с землёй'),('help','Как общаться со Стёпой')]]})
    stop=threading.Event(); server=start_sensors(store,config,stop)
    gateway=start_character_gateway(brain,config)
    bot=PlantBot(config,store,tg,brain)
    logging.info('Plant bot ready: @%s; mode=%s',me['username'],config.get('sensor_mode','serial'))
    try:
        while not stop.is_set():
            try:
                updates=tg.call('getUpdates',{'offset':store.get('last_update',-1)+1,'timeout':20,'allowed_updates':['message','callback_query']},timeout=30)
                for update in updates: bot.handle(update)
                bot.tick()
                store.set('heartbeat',time.time())
            except ServiceError as exc:
                logging.warning('Service retry: %s',str(exc)); stop.wait(5)
            except Exception as exc:
                logging.error('Update processing failed (%s)',type(exc).__name__); stop.wait(5)
    except KeyboardInterrupt: pass
    finally:
        stop.set()
        if server: server.shutdown(); server.server_close()
        if gateway: gateway.shutdown(); gateway.server_close()
        lock.close()

if __name__=='__main__': main()
