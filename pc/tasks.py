"""Bounded, process-local background jobs, one active job per feature."""
import copy
import threading
import uuid

LANES = {'search': 'search', 'parse': 'download', 'batch': 'download',
         'resolve': 'download', 'download': 'download', 'merge': 'merge',
         'local-compare': 'merge', 'local-folder': 'merge', 'local-merge': 'merge'}

class Conflict(ValueError):
    pass

class Tasks:
    def __init__(self):
        self.lock = threading.Lock()
        self.locks = {lane: threading.Lock() for lane in set(LANES.values())}
        self.jobs = {}

    def submit(self, action, data, execute):
        if action not in LANES: raise ValueError('未知任务。')
        lane = LANES[action]
        gate = self.locks[lane]
        if not gate.acquire(False): raise Conflict('此功能已有任务运行，其他功能仍可使用。')
        job = {'id': uuid.uuid4().hex, 'lane': lane, 'action': action,
               'state': 'running', 'progress': {}, 'cancelRequested': False}
        with self.lock:
            # Keep only the latest job per lane; at most three results in memory.
            self.jobs[lane] = job
        def update(**values):
            with self.lock: job.update(copy.deepcopy(values))
        def cancelled():
            with self.lock: return job['cancelRequested']
        def run():
            try:
                value = execute(action, copy.deepcopy(data), update, cancelled)
                with self.lock:
                    if job['state']=='running': job.update(value=copy.deepcopy(value),state='done')
            except Exception as error:
                update(error=str(error), state='failed')
            finally:
                gate.release()
        try:
            threading.Thread(target=run, daemon=True).start()
        except Exception:
            gate.release()
            with self.lock: self.jobs.pop(lane, None)
            raise
        return self.get(job['id'])

    def list(self):
        with self.lock: return copy.deepcopy(list(self.jobs.values()))

    def get(self, job_id):
        with self.lock:
            for job in self.jobs.values():
                if job['id'] == job_id: return copy.deepcopy(job)
        raise ValueError('任务已被后续任务替换或服务已重启。')

    def cancel(self, job_id):
        with self.lock:
            for job in self.jobs.values():
                if job['id'] == job_id and job['action'] == 'batch':
                    job['cancelRequested'] = True
                    return {'cancelRequested': True}
        raise ValueError('没有可停止的下载队列。')
