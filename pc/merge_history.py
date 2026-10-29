"""Persistent local merge history, separate from rotating diagnostic logs."""
import json
import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

def now():return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')

def connect(root):
    folder=Path(root)/'.runtime';folder.mkdir(parents=True,exist_ok=True)
    connection=sqlite3.connect(str(folder/'merge-history.sqlite3'),timeout=10)
    connection.execute('CREATE TABLE IF NOT EXISTS merges (id INTEGER PRIMARY KEY, created TEXT, status TEXT, sources TEXT, path TEXT, duration REAL, bytes INTEGER, error TEXT)')
    return connection

def record(root,files,result=None,error=None):
    with connect(root) as db:
        if result:
            db.execute("DELETE FROM merges WHERE path=? AND sources='[]'",(result['path'],))
        db.execute('INSERT INTO merges(created,status,sources,path,duration,bytes,error) VALUES(?,?,?,?,?,?,?)',
                   (now(),'success' if result else 'failure',json.dumps([Path(p).name for p in files],ensure_ascii=False),
                    (result or {}).get('path'),(result or {}).get('duration'),(result or {}).get('bytes'),
                    type(error).__name__ if error else None))

def list_records(root):
    with connect(root) as db:
        # Index earlier outputs once. Their original source order was not saved.
        downloads=Path(root)/'downloads'
        known={str(Path(r[0]).resolve()) for r in db.execute('SELECT path FROM merges WHERE path IS NOT NULL')}
        candidates=list((downloads/'合并视频').glob('*.mp4'))+list(downloads.glob('*/合并-*.mp4'))
        for path in candidates:
            if path.is_symlink() or not path.is_file() or path.name.endswith('.part.mp4'):continue
            absolute=str(path.resolve())
            if absolute in known:continue
            if not path.resolve().is_relative_to(downloads.resolve()):continue
            stat=path.stat()
            created=datetime.fromtimestamp(stat.st_mtime,ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')
            db.execute('INSERT INTO merges(created,status,sources,path,duration,bytes,error) VALUES(?,?,?,?,?,?,?)',
                       (created,'success','[]',absolute,None,stat.st_size,None))
            known.add(absolute)
        rows=db.execute('SELECT id,created,status,sources,path,duration,bytes,error FROM merges ORDER BY created DESC,id DESC LIMIT 100').fetchall()
    return [{'id':r[0],'createdAt':r[1],'status':r[2],'sources':json.loads(r[3]),'path':r[4],
             'duration':r[5],'bytes':r[6],'errorType':r[7],'exists':bool(r[4] and Path(r[4]).is_file())} for r in rows]
