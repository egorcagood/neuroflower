"""Read pending private-chat sender IDs without logging the bot token."""
from getpass import getpass
import requests

def main():
    token=getpass('Telegram bot token (hidden): ').strip()
    try:
        response=requests.get('https://api.telegram.org/bot'+token+'/getUpdates',params={'timeout':0,'allowed_updates':'["message"]'},timeout=20)
        data=response.json()
        if not response.ok or not data.get('ok'):
            print('Could not read updates. Check token and stop other bot instances.'); return
        ids=sorted({u['message']['from']['id'] for u in data['result'] if u.get('message',{}).get('chat',{}).get('type')=='private'})
        print('Private sender IDs:', ', '.join(map(str,ids)) if ids else 'none; send /start to your bot and retry')
    except (requests.RequestException,ValueError,KeyError):
        print('Could not read updates. Check network and token.')

if __name__=='__main__':main()
