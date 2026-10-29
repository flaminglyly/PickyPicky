"""Per-task FFmpeg progress without shared state between worker threads."""
import contextvars
import selectors
import subprocess
import tempfile
import time

REPORT=contextvars.ContextVar('merge_report',default=None)
def emit(message,percent=None):
    callback=REPORT.get()
    if callback:callback(progress={'message':message,'percent':percent})

def run(command,duration,timeout,message,boundaries=None):
    emit(message,0)
    command=[command[0],'-progress','pipe:1','-nostats',*command[1:]]
    with tempfile.TemporaryFile() as errors:
        process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=errors)
        selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
        start=time.monotonic();buffer=b'';last=-1
        try:
            while True:
                if time.monotonic()-start>timeout:raise subprocess.TimeoutExpired(command,timeout)
                for key,_ in selector.select(.5):
                    import os
                    chunk=os.read(key.fd,8192)
                    if chunk:buffer+=chunk
                    else:selector.unregister(key.fileobj)
                    while b'\n' in buffer:
                        line,buffer=buffer.split(b'\n',1)
                        if line.startswith(b'out_time_us='):
                            try:seconds=max(0,int(line.split(b'=',1)[1])/1000000)
                            except ValueError:continue
                            percent=min(99,seconds/max(duration,.001)*100)
                            if int(percent)!=last:
                                last=int(percent);label=message
                                if boundaries:
                                    index=next((i+1 for i,end in enumerate(boundaries) if seconds<end),len(boundaries))
                                    label=f'{message} · 第 {index}/{len(boundaries)} 个文件'
                                emit(label,round(percent,1))
                if process.poll() is not None and not selector.get_map():break
            code=process.wait()
            if code==0:emit(message,100)
            return subprocess.CompletedProcess(command,code)
        finally:
            if process.poll() is None:process.kill();process.wait()
            selector.close();process.stdout.close()
