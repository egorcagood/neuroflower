"""USB sensor input and optional server ingress; no ESP firmware dependency on Telegram."""
import hmac
import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import serial
from serial.tools import list_ports
from core import parse_reading, validate_reading

def serial_loop(store,config,stop):
    while not stop.is_set():
        try:
            port=config.get('serial_port','auto')
            if port=='auto':
                found=[p.device for p in list_ports.comports() if (p.vid,p.pid) in ((0x303A,0x1001),(0x1A86,0x55D3))]
                if len(found)!=1: raise RuntimeError('Connect exactly one ESP32 port')
                port=found[0]
            conn=serial.Serial()
            conn.port=port; conn.baudrate=115200; conn.timeout=1; conn.dtr=False; conn.rts=False
            conn.open()
            logging.info('ESP32 connected on %s',port)
            with conn:
                conn.reset_input_buffer()
                last=0
                while not stop.is_set():
                    line=conn.read_until(b'\n',2048).decode('utf-8','replace').strip()
                    row=parse_reading(line)
                    if row and time.monotonic()-last>=9:
                        store.add_reading(row); last=time.monotonic()
                        logging.info('Sensors: soil=%s light=%s temp=%s RH=%s',row['soil_raw'],row['light_lux'],row['temperature_C'],row['air_RH_pct'])
        except Exception as exc:
            logging.warning('Sensor input unavailable (%s); retrying',type(exc).__name__)
            stop.wait(5)

def create_ingest_server(store,token,address=('127.0.0.1',8787)):
    if not token: raise ValueError('Ingest token required')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def setup(self):
            super().setup(); self.connection.settimeout(10)
        def respond(self,code):
            data=json.dumps({'ok':code==200}).encode()
            self.send_response(code); self.send_header('Content-Type','application/json')
            self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
        def do_POST(self):
            if self.path!='/v1/readings': return self.respond(404)
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token): return self.respond(401)
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=8192: return self.respond(413)
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict): raise ValueError('Object required')
                row=validate_reading(data)
                now=time.time()
                if abs(row['at']-now)>90: raise ValueError('Stale remote sample')
                row['at']=now
                store.add_reading(row)
                self.respond(200)
            except (ValueError,TypeError,UnicodeError): self.respond(400)
    return ThreadingHTTPServer(address,Handler)

def start_sensors(store,config,stop):
    mode=config.get('sensor_mode','serial')
    if mode=='serial':
        thread=threading.Thread(target=serial_loop,args=(store,config,stop),daemon=True)
        thread.start(); return None
    if mode=='remote':
        server=create_ingest_server(store,config['ingest_token'],(config.get('ingest_host','127.0.0.1'),config.get('ingest_port',8787)))
        threading.Thread(target=server.serve_forever,daemon=True).start(); return server
    if mode!='none': raise ValueError('Unknown sensor mode')
