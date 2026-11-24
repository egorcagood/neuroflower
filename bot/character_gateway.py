"""Optional authenticated HTTP adapter for Simon. No Yandex account integration."""
from collections import deque
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac
import json
import threading
import time
from character import CharacterEvent
from voice import voice_control

def create_character_server(brain,token,address=('127.0.0.1',8788)):
    if not isinstance(token,str) or len(token)<32: raise ValueError('Use a separate gateway token, at least 32 characters')
    rate=deque(); gate=threading.Lock()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def setup(self):
            super().setup(); self.connection.settimeout(10)
        def respond(self,status,body):
            raw=json.dumps(body,ensure_ascii=False).encode('utf-8')
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(raw))); self.end_headers()
            try: self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError): pass
        def do_POST(self):
            if self.path!='/v1/character/events': return self.respond(404,{'error':'not_found'})
            if not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+token): return self.respond(401,{'error':'unauthorized'})
            try:
                size=int(self.headers.get('Content-Length',0))
                if not 0<size<=8192: return self.respond(413,{'error':'too_large'})
                body=json.loads(self.rfile.read(size))
                if not isinstance(body,dict) or set(body)-{'request_id','source','text','kind','metadata'}: raise ValueError()
                if body.get('source') not in ('simon_bridge','yandex_station'): raise ValueError()
                if body.get('kind','dialogue') not in ('dialogue','greeting','health'): raise ValueError()
                event=CharacterEvent(**body)
            except (ValueError,TypeError,UnicodeError): return self.respond(400,{'error':'invalid_event'})
            if not gate.acquire(blocking=False): return self.respond(429,{'error':'busy'})
            try:
                now=time.monotonic()
                while rate and now-rate[0]>60: rate.popleft()
                if len(rate)>=12: return self.respond(429,{'error':'rate_limit'})
                rate.append(now)
                reply=voice_control(brain,event)
                if reply is None:
                    if not brain.lock.acquire(blocking=False): return self.respond(429,{'error':'character_busy'})
                    try: reply=brain.respond(event)
                    finally: brain.lock.release()
                self.respond(200,asdict(reply))
            except Exception:
                self.respond(503,{'error':'temporarily_unavailable'})
            finally: gate.release()
    return ThreadingHTTPServer(address,Handler)

def start_character_gateway(brain,config):
    if not config.get('character_gateway_enabled',False): return None
    server=create_character_server(brain,config.get('character_gateway_token',''),
             (config.get('character_gateway_host','127.0.0.1'),config.get('character_gateway_port',8788)))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    return server
