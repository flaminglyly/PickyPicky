"""Request pacing and persistent upstream cooldown; no automatic retries."""
import json
import math
import threading
import time
from email.utils import parsedate_to_datetime
from pathlib import Path

class Traffic:
    def __init__(self, path, interval=3, clock=time.time, sleep=time.sleep):
        self.path=Path(path); self.interval=interval; self.clock=clock; self.sleep=sleep
        self.lock=threading.Lock(); self.next_request=0
        self.until=0; self.strikes=0; self.source=''
        try:
            data=json.loads(self.path.read_text())
            self.until=float(data['until']); self.strikes=int(data['strikes']); self.source=str(data['source'])
        except (OSError,ValueError,TypeError,KeyError): pass
    def state(self):
        with self.lock:
            return {'retryAfter':max(0,math.ceil(self.until-self.clock())), 'source':self.source,
                    'interval':self.interval, 'strikes':self.strikes}
    def pace(self):
        # Caller holds its request lock. Recheck after waiting before sending anything.
        with self.lock:
            if self.until>self.clock(): return False
            wait=max(0,self.next_request-self.clock())
        if wait: self.sleep(wait)
        with self.lock:
            if self.until>self.clock(): return False
            self.next_request=self.clock()+self.interval
        return True
    def limited(self, retry_after, source):
        with self.lock:
            now=self.clock(); self.strikes=min(self.strikes+1,6)
            delay=300*(2**(self.strikes-1))
            if retry_after:
                try: requested=float(retry_after)
                except (ValueError,TypeError):
                    try: requested=parsedate_to_datetime(retry_after).timestamp()-now
                    except (ValueError,TypeError,OverflowError): requested=0
                if math.isfinite(requested): delay=max(delay,requested)
            self.until=max(self.until,now+delay); self.source=source
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps({'until':self.until,'strikes':self.strikes,'source':self.source}))
            tmp.replace(self.path)
        return self.state()
