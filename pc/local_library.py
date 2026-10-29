"""Native folder consent; browser receives opaque file IDs, never supplies paths."""
import json
import subprocess
import uuid
from pathlib import Path

LIBRARIES={}

def choose_folder():
    script='const app=Application.currentApplication(); app.includeStandardAdditions=true; JSON.stringify(app.chooseFolder({withPrompt:"选择包含 MP4 剧集的文件夹"}).toString());'
    result=subprocess.run(['osascript','-l','JavaScript','-e',script],capture_output=True,text=True,timeout=180)
    if result.returncode:
        if '-128' in result.stderr:return {'cancelled':True}
        raise ValueError('无法打开文件夹选择器，请检查系统自动化权限。')
    folder=Path(json.loads(result.stdout)).resolve()
    entries={}
    for path in sorted(folder.iterdir(),key=lambda p:p.name):
        if path.is_file() and not path.is_symlink() and path.suffix.lower()=='.mp4':
            entries[uuid.uuid4().hex]=path.resolve()
    if not entries:raise ValueError('该文件夹没有 MP4 文件（不包含子文件夹）。')
    library=uuid.uuid4().hex
    if len(LIBRARIES)>=10:LIBRARIES.pop(next(iter(LIBRARIES)))
    LIBRARIES[library]=entries
    return {'libraryId':library,'folderName':folder.name,'files':[{'id':key,'name':p.name,'bytes':p.stat().st_size} for key,p in entries.items()]}

def choose_files(library_id=None):
    if library_id is not None and library_id not in LIBRARIES: raise ValueError("文件列表已失效，请重新选择视频。")
    script='const app=Application.currentApplication(); app.includeStandardAdditions=true; const files=app.chooseFile({withPrompt:"选择需要合并的 MP4 视频（Command 多选，Shift 连选）",ofType:["mp4"],multipleSelectionsAllowed:true}); JSON.stringify(files.map(file=>file.toString()));'
    result=subprocess.run(['osascript','-l','JavaScript','-e',script],capture_output=True,text=True,timeout=180)
    if result.returncode:
        if '-128' in result.stderr:return {'cancelled':True}
        raise ValueError('无法打开视频文件选择器，请检查系统自动化权限。')
    values=json.loads(result.stdout)
    if not isinstance(values,list) or not values or not all(isinstance(v,str) for v in values):
        raise ValueError('请选择需要合并的 MP4 视频文件。')
    paths=[]
    for value in values:
        path=Path(value)
        if path.is_symlink() or not path.is_file() or path.suffix.lower()!='.mp4':
            raise ValueError('请选择有效的 MP4 视频文件，不支持快捷链接。')
        resolved=path.resolve()
        if resolved not in paths: paths.append(resolved)
    entries=dict(LIBRARIES[library_id]) if library_id else {}
    existing=set(entries.values())
    for path in paths:
        if path not in existing:
            entries[uuid.uuid4().hex]=path
            existing.add(path)
    library=library_id or uuid.uuid4().hex
    if not library_id and len(LIBRARIES)>=10:LIBRARIES.pop(next(iter(LIBRARIES)))
    LIBRARIES[library]=entries
    return {'libraryId':library,'folderName':next(iter(entries.values())).parent.name,'selectionMode':'files',
            'files':[{'id':key,'name':p.name,'sourceFolder':str(p.parent),'bytes':p.stat().st_size} for key,p in entries.items()]}

def selected(library,ids):
    if not isinstance(ids,list) or not all(isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):
        raise ValueError('合并列表无效。')
    entries=LIBRARIES.get(library)
    if entries is None:raise ValueError('文件夹会话已失效，请重新选择文件夹。')
    if not all(i in entries for i in ids):raise ValueError('合并列表包含未授权的文件。')
    paths=[entries[i] for i in ids]
    if any(p.is_symlink() or not p.is_file() for p in paths):raise ValueError('源文件已移动或无法访问，请重新选择文件夹。')
    return paths
