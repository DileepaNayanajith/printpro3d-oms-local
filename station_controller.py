"""Paired computer launcher. Only two fixed local worker commands are allowed."""
import json,os,subprocess,sys,time
from pathlib import Path
from home_worker import station_root,lock
from oms.station_client import API

ALLOWED={'fde','whatsapp'}
def launch(kind,root,children):
 if kind not in ALLOWED:raise ValueError('Unsupported worker')
 if kind in children and children[kind].poll() is None:return
 # home_worker takes its own OS lock, including workers launched outside this controller.
 with (root/(kind+'-worker.log')).open('ab') as log:
  children[kind]=subprocess.Popen([sys.executable,'-u',str(Path(__file__).with_name('home_worker.py')),'--kind',kind],cwd=Path(__file__).parent,stdout=log,stderr=log,env=os.environ.copy())
def main():
 root=station_root();root.mkdir(parents=True,exist_ok=True);children={}
 with lock(root/'controller.lock'):
  print('Home PC controller ready. Use Open FDE / Open WhatsApp in OMS. Keep this window open.',flush=True)
  while True:
   try:
    settings=json.loads((root/'settings.json').read_text());api=API(settings['url'],settings['token'])
    for command in api.post('control',{})['commands']:
     if command.get('kind') in ALLOWED:launch(command['kind'],root,children)
   except Exception as error:print('Controller connection needs attention:',type(error).__name__,flush=True)
   time.sleep(4)
if __name__=='__main__':main()
