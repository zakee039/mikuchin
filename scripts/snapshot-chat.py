"""Snapshot a PolyStrata chat store without mutating the source.

Run after stopping the OLD manager for a final snapshot before cutover.
Always uses SQLite backup API for database consistency.
"""
import argparse, shutil, sqlite3
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--destination', type=Path, required=True)
    ap.add_argument('--kv-source', type=Path)
    ap.add_argument('--final', action='store_true', help='include KV and reconcile all files after old service has stopped')
    args=ap.parse_args()
    src,dst=args.source,args.destination
    dst.mkdir(parents=True,exist_ok=True)
    for name in ('conversations.sqlite3','character_cards.sqlite3'):
        if not (src/name).is_file(): continue
        with sqlite3.connect(f'file:{(src/name).as_posix()}?mode=ro',uri=True,timeout=20) as db:
            with sqlite3.connect(dst/name) as target: db.backup(target)
        with sqlite3.connect(dst/name) as db:
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok', name
    for folder in ('images','attachments','generated-images'):
        if (src/folder).is_dir():
            shutil.copytree(src/folder,dst/folder,dirs_exist_ok=True)
    if args.final:
        if args.kv_source is None: ap.error('--final requires --kv-source')
        if args.kv_source.is_dir(): shutil.copytree(args.kv_source,dst/'kv-cache',dirs_exist_ok=True)
    print('Snapshot complete: '+str(dst))

if __name__=='__main__':main()
