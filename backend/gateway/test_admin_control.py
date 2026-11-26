import http.client
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from backend.gateway.supervisor import NativeSupervisor
from backend.gateway.test_supervisor import spare_port
from backend.gateway.admin_control import RELOAD, OPERATIONS


class LocalAdminTest(unittest.TestCase):
    def test_live_mock_reload(self):
        with tempfile.TemporaryDirectory() as d:
            import os
            # Use the real Windows launcher path representation, not a normal
            # temp path, to cover both credential binding and strict SQLite URI.
            data = Path("\\\\?\\"+str(Path(d).resolve())) if os.name=="nt" else Path(d)
            upstream, gateway = spare_port(), spare_port()
            while upstream == gateway:
                gateway = spare_port()
            s = NativeSupervisor(data_dir=data, api_key="local-test-admin-key",
                                 upstream_port=upstream, gateway_port=gateway,
                                 startup_timeout=20)
            errors=[]
            def run():
                try: s.run()
                except Exception as exc: errors.append(repr(exc))
            th=threading.Thread(target=run, daemon=True); th.start()
            def wait_for(fn, seconds=30):
                until=time.monotonic()+seconds
                while time.monotonic()<until:
                    value=fn()
                    if value: return value
                    time.sleep(.15)
                self.fail("timed out: "+str(errors))
            def request(port, method, path, key=None, extra=None):
                conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
                try:
                    headers=dict(extra or {})
                    if key: headers["Authorization"]="Bearer "+key
                    conn.request(method,path,body=b"" if method=="POST" else None,headers=headers)
                    res=conn.getresponse(); return res.status,json.loads(res.read())
                finally: conn.close()
            try:
                admin=wait_for(lambda: s.admin if s.admin and len(s.children)==3 else None)
                port=admin.server_port; key=s.api_key
                self.assertEqual(admin.server_address[0],"127.0.0.1")
                self.assertEqual(request(port,"POST",RELOAD)[0],401)
                import os, sys, subprocess
                if os.name == "nt":
                    from backend.gateway import admin_credential
                    dedicated=admin_credential.load(data,os.getpid(),port)
                    self.assertTrue(dedicated)
                    self.assertNotEqual(dedicated,key)
                    self.assertEqual(request(port,"GET",RELOAD+"/eligibility",dedicated)[0],200)
                    self.assertEqual(request(gateway,"GET","/health",dedicated)[0],401)
                    self.assertEqual(request(port,"GET",RELOAD+"/eligibility",dedicated,{"Origin":"https://example.test"})[0],403)
                    with self.assertRaises(ValueError):admin_credential.load(data,os.getpid(),port+1)
                    env=os.environ.copy();env.pop("MIKUCHIN_GATEWAY_API_KEY",None)
                    root=Path(__file__).resolve().parents[2]

                self.assertEqual(request(port,"POST",RELOAD,key,{"X-Forwarded-For":"192.0.2.1"})[0],403)
                self.assertEqual(request(gateway,"POST","/internal/admin/drain",key)[0],403)
                self.assertEqual(request(gateway,"POST","/internal/admin/drain",s.upstream_key)[0],200)
                self.assertEqual(request(gateway,"POST","/v1/images/generations",key)[0],503)
                self.assertEqual(request(gateway,"POST","/internal/admin/resume",s.upstream_key)[0],200)
                old={k:v.pid for k,v in s.children.items()}
                wait_for(lambda:request(port,"GET",RELOAD+"/eligibility",key)[1].get("allowed"))
                if os.name == "nt":
                    result=subprocess.run([sys.executable,str(root/"scripts/native-admin.py"),"eligibility","--data-dir",str(data)],env=env,capture_output=True,text=True,timeout=15)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertTrue(json.loads(result.stdout)["allowed"])

                # The real GPU gate must block a reload before any STOP.
                from backend.gateway.gpu_gate import gpu_turn
                with gpu_turn(data,exclusive=True):
                    self.assertFalse(request(port,"GET",RELOAD+"/eligibility",key)[1]["allowed"])
                    code,op=request(port,"POST",RELOAD,key);self.assertEqual(code,202)
                    ident=op["operation_id"]
                    result=wait_for(lambda: (v if (v:=request(port,"GET",OPERATIONS+ident,key)[1]).get("done") else None))
                    self.assertEqual(result["phase"],"blocked")
                    self.assertEqual(old,{k:v.pid for k,v in s.children.items()})
                # Bypass cooldown only in this isolated test, never production.
                admin.last_request=0
                code,op=request(port,"POST",RELOAD,dedicated if os.name=="nt" else key);self.assertEqual(code,202)
                ident=op["operation_id"]
                result=wait_for(lambda: (v if (v:=request(port,"GET",OPERATIONS+ident,key)[1]).get("done") else None))
                self.assertEqual(result["phase"],"done",result)
                self.assertEqual(old["official"],s.children["official"].pid)
                self.assertNotEqual(old["gateway"],s.children["gateway"].pid)
                self.assertNotEqual(old["image-worker"],s.children["image-worker"].pid)
                self.assertTrue(list((data/"recovery-backups").glob("*.sqlite3")))
            finally:
                s.stop.set();th.join(35)
                self.assertFalse(th.is_alive())
            self.assertEqual(errors,[])
