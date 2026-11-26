"""Use the supervisor's loopback-only administrative interface."""
import argparse
import getpass
import http.client
import json
import os
import time
import sys
from pathlib import Path


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("action", choices=("eligibility","reload"))
    default_root=str(Path(__file__).resolve().parents[1]/"runtime"/"launcher-user-data")
    # The Windows launcher passes an extended-length path to Supervisor.
    # Use exactly the same representation for the DPAPI entropy binding.
    if os.name=="nt" and not default_root.startswith("\\\\?\\"):
        default_root=("\\\\?\\UNC\\"+default_root[2:] if default_root.startswith("\\\\") else "\\\\?\\"+default_root)
    ap.add_argument("--data-dir", default=default_root)
    args=ap.parse_args()
    status=json.loads((Path(args.data_dir)/"supervisor-status.json").read_text(encoding="utf-8"))
    port=status.get("admin_port")
    if type(port) is not int or not 1024 <= port <= 65535:
        ap.error("Supervisor admin endpoint is not yet running")
    key=os.environ.get("MIKUCHIN_GATEWAY_API_KEY")
    if not key and os.name=="nt":
        sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
        from backend.gateway.admin_credential import load
        try:
            key=load(args.data_dir,status.get("supervisor_pid"),port)
        except (OSError, ValueError, RuntimeError):
            ap.error("Local management credential unavailable; use the same authorized Windows account")
    if not key:
        if not sys.stdin.isatty():
            ap.error("Local management credential is not provisioned; explicit authentication required")
        key=getpass.getpass("Mikuchin API key: ")
    def call(method,path):
        conn=http.client.HTTPConnection("127.0.0.1",port,timeout=5)
        try:
            conn.request(method,path,body=b"" if method=="POST" else None,headers={"Authorization":"Bearer "+key})
            r=conn.getresponse();data=json.loads(r.read(65536));return r.status,data
        finally:conn.close()
    path="/admin/reload-image-api-stack"
    code,result=call("GET",path+"/eligibility")
    print(json.dumps(result,ensure_ascii=False),flush=True)
    if args.action=="eligibility":return 0 if code==200 and result.get("allowed") else 1
    if code!=200 or not result.get("allowed"):return 1
    code,result=call("POST",path);print(json.dumps(result),flush=True)
    if code!=202:return 1
    op=result["operation_id"];deadline=time.monotonic()+75
    while time.monotonic()<deadline:
        code,result=call("GET","/admin/operations/"+op)
        if code!=200 or result.get("done"):
            print(json.dumps(result),flush=True);return 0 if result.get("phase")=="done" else 1
        time.sleep(.5)
    print("Operation not confirmed; do not submit again automatically")
    return 1

if __name__=="__main__":raise SystemExit(main())
