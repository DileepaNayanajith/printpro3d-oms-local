"""Outbound HTTPS client and durable no-replay journal for the Windows station."""
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise RuntimeError('Cloud URL redirected. Update station settings; token was not forwarded.')

class API:
    def __init__(self,url,token):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ('','/'):
            raise ValueError('Use the HTTPS origin of your OMS, without a path.')
        self.url=url.rstrip('/');self.token=token
        self.opener=urllib.request.build_opener(NoRedirect())
    def post(self,path,data):
        request=urllib.request.Request(self.url+'/api/station/'+path,
          data=json.dumps(data).encode(),headers={'Authorization':'Bearer '+self.token,'Content-Type':'application/json'},method='POST')
        with self.opener.open(request,timeout=30) as response:
            return json.load(response)


def save(path,data):
    temp=path.with_suffix('.tmp')
    with temp.open('w',encoding='utf-8') as f:
        json.dump(data,f);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)


def recover(api,journal):
    """Retry acknowledgements, never courier/print/message writes."""
    if not journal.exists():return
    data=json.loads(journal.read_text(encoding='utf-8'))
    result=data.get('result') or {'outcome':'uncertain'}
    try:
        api.post(data['id']+'/result',result)
    except urllib.error.HTTPError as exc:
        if exc.code!=409:raise
        status=api.post(data['id']+'/status',{})
        if status['state']!='expired':raise
        # Server has quarantined the source job. Keep local evidence but allow other jobs.
        os.replace(journal,journal.with_name(data['id']+'-review.json'))
        print('An expired job needs review in OMS. It will not be automatically repeated.',flush=True)
        return
    journal.unlink()


def execute(api,task,journal,prepare,perform):
    # A journal must be reconciled before a new task is started.
    if journal.exists():raise RuntimeError('Previous attempt must be reconciled first.')
    save(journal,{'id':task['id']})
    try:
        context=prepare(task)
    except Exception as exc:
        from .fde_browser import SignInRequired
        from .whatsapp_browser import LoginRequired
        result={'outcome':'login_required' if isinstance(exc,(SignInRequired,LoginRequired)) else 'blocked'}
    else:
        # If start acknowledgement is lost, leave journal and STOP. No perform call.
        api.post(task['id']+'/start',{})
        try:
            details=perform(task,context) or {}
            result={'outcome':'success',**details}
        except Exception:
            result={'outcome':'uncertain'}
    save(journal,{'id':task['id'],'result':result})
    recover(api,journal)
