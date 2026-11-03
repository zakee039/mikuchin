"""Isolated, authenticated UI language smoke test; no GPU load, no user data changes."""
import json,os,subprocess,time,tempfile,urllib.request,urllib.error
from pathlib import Path
root=Path(__file__).resolve().parents[2];engine=root/'backend/polystrata'
TEST_TEMP = root / 'test' / 'temp'
TEST_TEMP.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix='mk-i18n-test-',dir=TEST_TEMP,ignore_cleanup_errors=True) as work:
    language_file=Path(work)/'ui-language.json';logs=Path(work)/'server.log'
    env={**os.environ,'MIKUCHIN_LANGUAGE_FILE':str(language_file),'MIKUCHIN_WEB_DIR':str(root/'frontend/web'),'STRATA_API_KEY':'ephemeral-test'}
    with logs.open('wb') as output:
        proc=subprocess.Popen([str(engine/'.venv/Scripts/python.exe'),str(engine/'serve/server.py'),'--engine','mock','--port','18085','--host','127.0.0.1'],cwd=engine,env=env,stdout=output,stderr=subprocess.STDOUT)
        def request(path,data=None,origin=None,auth=True):
            h={}
            if auth:h['Authorization']='Bearer ephemeral-test'
            if origin:h['Origin']=origin
            if data is not None:h['Content-Type']='application/json'
            with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18085'+path,headers=h,data=json.dumps(data).encode() if data is not None else None),timeout=6) as response:
                return response.status,response.read()
        try:
            for i in range(60):
                if proc.poll() is not None:raise RuntimeError('mock server quit: '+logs.read_text(errors='replace')[-1500:])
                try:request('/health');break
                except OSError:time.sleep(0.4)
            else:raise RuntimeError('mock service did not become ready')
            assert json.loads(request('/v1/mikuchin/ui-language')[1])['language']=='zh-CN'
            status,body=request('/v1/mikuchin/ui-language',{'language':'ja-JP'},'http://127.0.0.1:18085')
            assert status==200 and json.loads(body)['language']=='ja-JP'
            assert json.loads(request('/v1/mikuchin/ui-language')[1])['language']=='ja-JP'
            assert json.loads(language_file.read_text(encoding='utf8'))['language']=='ja-JP'
            for path in ('/','/web/i18n.js','/web/i18n-data.js','/web/dropdown.js'):
                assert request(path)[0]==200,path
            for payload in ({'language':'invalid'},):
                try:request('/v1/mikuchin/ui-language',payload,'http://127.0.0.1:18085')
                except urllib.error.HTTPError as exc:assert exc.code==400
                else:raise AssertionError('invalid locale unexpectedly accepted')
            try:request('/v1/mikuchin/ui-language',{'language':'en-US'},'http://127.0.0.1:18085',auth=False)
            except urllib.error.HTTPError as exc:assert exc.code==401
            else:raise AssertionError('missing authentication accepted')
            print('PASS: GET/POST global locale, validation, unauth rejection, Web assets',flush=True)
        finally:
            subprocess.run(['taskkill','/T','/F','/PID',str(proc.pid)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=20)
            try: proc.wait(timeout=10)
            except subprocess.TimeoutExpired: proc.kill();proc.wait(timeout=10)
            time.sleep(0.5)
