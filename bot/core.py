"""Sensor validation, persistent memory and deterministic care rules."""
import json
import math
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from pathlib import Path

MOSCOW = timezone(timedelta(hours=3))
FIELDS = {'soil_raw':(0,4095),'soil_mV':(0,3600),'light_lux':(0,200000),
          'temperature_C':(-40,125),'air_RH_pct':(0,100)}

def validate_reading(row):
    result = {}
    for name,(low,high) in FIELDS.items():
        val = row.get(name)
        if val is not None and (type(val) not in (int,float) or not math.isfinite(val) or not low <= val <= high):
            raise ValueError('Invalid sensor field: '+name)
        result[name] = val
    if result['soil_raw'] is None: raise ValueError('Soil sample missing')
    at = row.get('at',time.time())
    if type(at) not in (int,float) or not math.isfinite(at) or at < 0: raise ValueError('Invalid timestamp')
    result['at'] = at
    return result

def parse_reading(line, now=None):
    if not line.startswith('uptime_s=') or 'soil_raw=' not in line: return None
    row = {'at':time.time() if now is None else now}
    for name in FIELDS:
        match = re.search(r'\b'+name+r'=(-?\d+(?:\.\d+)?)',line)
        row[name] = float(match[1]) if match else None
    if 'I2C_BUS_NOT_IDLE' in line:
        for name in ('light_lux','temperature_C','air_RH_pct'): row[name] = None
    try: return validate_reading(row)
    except ValueError: return None

def moisture(raw, calibration):
    if raw is None or not all(k in calibration for k in ('dry','wet')): return None
    dry,wet = calibration['dry'],calibration['wet']
    if type(dry) not in (int,float) or type(wet) not in (int,float) or not 0 <= wet < dry <= 4095 or dry-wet < 150:
        raise ValueError('Dry reading must exceed wet reading by at least 150')
    return round(max(0,min(100,100*(dry-raw)/(dry-wet))),1)

class Store:
    def __init__(self,path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY,at REAL NOT NULL,data TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS samples_time ON samples(at);
            CREATE TABLE IF NOT EXISTS waters (event_id TEXT PRIMARY KEY,at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY,at REAL,role TEXT,content TEXT);
            CREATE TABLE IF NOT EXISTS ai_usage (day TEXT PRIMARY KEY,count INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS character_events (event_id TEXT PRIMARY KEY,at REAL,kind TEXT,data TEXT);
            CREATE TABLE IF NOT EXISTS character_replies (request_id TEXT PRIMARY KEY,at REAL,data TEXT);
            ''')
    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path,timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally: db.close()
    def get(self,key,default=None):
        with self.connect() as db: row = db.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else default
    def set(self,key,value):
        with self.connect() as db: db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,json.dumps(value,ensure_ascii=False)))
    def add_reading(self,row):
        row = validate_reading(row)
        with self.connect() as db:
            db.execute('INSERT INTO samples(at,data) VALUES (?,?)',(row['at'],json.dumps(row)))
            db.execute('DELETE FROM samples WHERE at<?',(row['at']-30*86400,))
    def samples(self,since):
        with self.connect() as db: rows=db.execute('SELECT data FROM samples WHERE at>=? ORDER BY at',(since,)).fetchall()
        return [json.loads(r['data']) for r in rows]
    def snapshot(self,now=None):
        now = time.time() if now is None else now
        with self.connect() as db: row=db.execute('SELECT data FROM samples ORDER BY at DESC LIMIT 1').fetchone()
        reading=json.loads(row['data']) if row else None
        age = max(0,now-reading['at']) if reading else None
        cal=self.get('calibration',{})
        return {'reading':reading,'age_seconds':age,'stale':age is None or age>90,
                'relative_moisture':moisture(reading['soil_raw'],cal) if reading else None,
                'calibrated':all(k in cal for k in ('dry','wet')),
                'profile':self.get('profile','Вид и имя пока не указаны'),
                'last_watering':self.waters(1),'threshold':self.get('threshold',25),
                'awaiting_photo':self.get('awaiting_photo',False),
                'now_moscow':datetime.fromtimestamp(now,MOSCOW).isoformat()}
    def water(self,event_id,at=None):
        at=time.time() if at is None else at
        with self.connect() as db:
            cur=db.execute('INSERT OR IGNORE INTO waters VALUES (?,?)',(event_id,at))
            changed=cur.rowcount==1
            if changed: db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',('awaiting_photo','false'))
        return changed
    def waters(self,limit=10):
        with self.connect() as db: return [dict(row) for row in db.execute('SELECT event_id,at FROM waters ORDER BY at DESC LIMIT ?',(limit,))]
    def chat(self,role,content,at=None):
        with self.connect() as db:
            db.execute('INSERT INTO messages(at,role,content) VALUES (?,?,?)',(time.time() if at is None else at,role,content[:6000]))
            db.execute('DELETE FROM messages WHERE id NOT IN (SELECT id FROM messages ORDER BY id DESC LIMIT 200)')
    def history(self,limit=16):
        with self.connect() as db: rows=db.execute('SELECT role,content FROM messages ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [dict(row) for row in reversed(rows)]
    def reserve_ai(self,limit,now=None):
        day=datetime.fromtimestamp(time.time() if now is None else now,MOSCOW).date().isoformat()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('INSERT OR IGNORE INTO ai_usage VALUES (?,0)',(day,))
            return db.execute('UPDATE ai_usage SET count=count+1 WHERE day=? AND count<?',(day,limit)).rowcount==1
    def remember_event(self,event_id,kind,data,at=None):
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO character_events VALUES (?,?,?,?)',(event_id,time.time() if at is None else at,kind,json.dumps(data,ensure_ascii=False)))
            db.execute('DELETE FROM character_events WHERE event_id NOT IN (SELECT event_id FROM character_events ORDER BY at DESC LIMIT 100)')
    def recent_events(self,limit=12):
        with self.connect() as db: rows=db.execute('SELECT at,kind,data FROM character_events ORDER BY at DESC LIMIT ?',(limit,)).fetchall()
        return [{'at':r['at'],'kind':r['kind'],'detail':json.loads(r['data'])} for r in reversed(rows)]
    def cached_reply(self,request_id):
        with self.connect() as db: row=db.execute('SELECT data FROM character_replies WHERE request_id=?',(request_id,)).fetchone()
        return json.loads(row['data']) if row else None
    def save_reply(self,request_id,data):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO character_replies VALUES (?,?,?)',(request_id,time.time(),json.dumps(data,ensure_ascii=False)))
            db.execute('DELETE FROM character_replies WHERE request_id NOT IN (SELECT request_id FROM character_replies ORDER BY at DESC LIMIT 500)')

def reminder_due(store,now=None):
    now=time.time() if now is None else now
    snap=store.snapshot(now)
    if snap['stale'] or not snap['calibrated'] or not store.get('profile'): return False
    if store.get('reminders_paused',False): return False
    last=store.get('last_reminder')
    if last is not None and now-last<86400: return False
    if snap['last_watering'] and now-snap['last_watering'][0]['at']<86400: return False
    readings=store.samples(now-600)
    if len(readings)<20 or readings[0]['at']>now-540: return False
    if any(b['at']-a['at']>90 for a,b in zip(readings,readings[1:])): return False
    cal=store.get('calibration')
    return all(moisture(row['soil_raw'],cal)<=snap['threshold'] and 30<row['soil_raw']<4065 for row in readings)
