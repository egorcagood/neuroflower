"""Temporary USB-to-VPS bridge. Use HTTPS and a dedicated ingestion token."""
import argparse
import json
import logging
import threading
import time
from pathlib import Path
import requests
from sensors import serial_loop

class Forwarder:
    def __init__(self,config):
        self.url=config['ingest_url']; self.token=config['ingest_token']
        if not self.url.startswith('https://'): raise ValueError('Verified HTTPS is required')
        self.session=requests.Session()
        self.lock=threading.Lock(); self.pending=None
    def add_reading(self,row):
        with self.lock: self.pending=dict(row)
    def take_latest(self):
        with self.lock:
            row=self.pending; self.pending=None; return row
    def run(self,stop):
        while not stop.wait(1):
            row=self.take_latest()
            if row is not None and 0<=time.time()-row['at']<=30: self.send(row)
    def send(self,row):
        try:
            r=self.session.post(self.url,json=row,headers={'Authorization':'Bearer '+self.token},timeout=(5,10))
            if r.status_code!=200: logging.warning('VPS rejected measurement (HTTP %s)',r.status_code)
        except requests.RequestException:
            logging.warning('VPS connection unavailable; next fresh reading will retry')

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); args=parser.parse_args()
    config=json.loads(Path(args.config).read_text('utf-8'))
    logging.basicConfig(level=logging.INFO)
    stop=threading.Event(); forwarder=Forwarder(config)
    threading.Thread(target=forwarder.run,args=(stop,),daemon=True).start()
    try: serial_loop(forwarder,config,stop)
    except KeyboardInterrupt: stop.set()
