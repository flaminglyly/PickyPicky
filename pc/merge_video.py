"""Lossless concatenation of consecutive local episodes; never transcode."""
import json
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from fractions import Fraction
from pathlib import Path
import diagnostics
import merge_history
import merge_compare
import merge_progress
from datetime import datetime
from zoneinfo import ZoneInfo

FIELDS=('codec_type','codec_name','profile','codec_tag_string','width','height','pix_fmt',
        'level','sample_rate','channels','channel_layout','time_base','extradata_hash',
        'color_range','color_space','color_transfer','color_primaries','sample_aspect_ratio')

def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-show_data_hash','sha256','-of','json',str(path)],capture_output=True,timeout=30)
    if result.returncode:raise ValueError('源文件无法读取，请重新下载对应剧集。')
    info=json.loads(result.stdout)
    streams=info.get('streams',[])
    if len(streams)!=2 or {s.get('codec_type') for s in streams}!={'audio','video'}:
        raise ValueError('无损合并要求每集包含一个视频轨和一个音频轨。')
    return [{k:s.get(k) for k in FIELDS} for s in streams],float(info['format']['duration'])

def merge(root,title,episodes):
    started=time.monotonic()
    if len(episodes)<2:raise ValueError('请至少选择两集已下载的连续剧集。')
    ordered=sorted(episodes,key=lambda e:e['number'])
    numbers=[e['number'] for e in ordered]
    if numbers!=list(range(numbers[0],numbers[-1]+1)):
        raise ValueError('所选剧集编号不连续，请补齐缺失剧集后再合并。')
    if not all(shutil.which(tool) for tool in ('ffmpeg','ffprobe')):raise ValueError('需要安装 FFmpeg 和 ffprobe。')
    folder=(Path(root)/'downloads'/title).resolve()
    if not folder.is_relative_to((Path(root)/'downloads').resolve()):raise ValueError('下载目录无效。')
    files=[];signature=None;duration=0
    for episode in ordered:
        number=episode['number']
        saved=episode.get('download') or {}
        candidates=[Path(saved['path'])] if saved.get('path') else sorted(folder.glob(f'第{number:03d}集-*.mp4'),key=lambda p:p.stat().st_mtime,reverse=True)
        path=next((p for p in candidates if p.is_file() and re.fullmatch(r'第[0-9]+集-[0-9a-f]{6}\.mp4',p.name)),None)
        if path is None:raise ValueError(f'第 {number} 集尚未下载，请先完成下载。')
        path=path.resolve()
        if path.parent!=folder:raise ValueError('源文件不在当前剧集目录。')
        files.append(path)
    target=folder/f'合并-第{numbers[0]:03d}-{numbers[-1]:03d}集-{uuid.uuid4().hex[:6]}.mp4'
    return {**merge_files(root,files,target),'episodes':numbers}

def _merge_files(root,files,target=None,output_name=None,selective=False):
    started=time.monotonic()
    if len(files)<2:raise ValueError('请至少添加两个视频文件。')
    if not all(shutil.which(tool) for tool in ('ffmpeg','ffprobe')):raise ValueError('需要安装 FFmpeg 和 ffprobe。')
    signature=None;duration=0;boundaries=[]
    files=[Path(p).resolve() for p in files]
    for index,path in enumerate(files):
        if not path.is_file() or path.suffix.lower() not in (('.mp4','.ts') if selective else ('.mp4',)):raise ValueError(f'列表第 {index+1} 项不是可读取的 MP4 文件。')
        merge_progress.emit(f"检查文件 {index+1}/{len(files)}：{path.name}")
        current,seconds=probe(path)
        if selective and signature is not None:
            keys=('codec_type','codec_name','width','height','pix_fmt','sample_rate','channels')
            if [{k:x.get(k) for k in keys} for x in current]!=[{k:x.get(k) for k in keys} for x in signature]: raise ValueError('差异文件未能匹配多数格式，请使用全量兼容模式。')
        if signature is not None and current!=signature and not selective:
            raise ValueError(f'列表第 {index+1} 项的编码、分辨率或音频参数不一致，无法无损合并。')
        if seconds<=0:raise ValueError(f'列表第 {index+1} 项时长无效。')
        signature=current;duration+=seconds;boundaries.append(duration)
    if target is None:
        folder=files[0].parent
        target=folder/output_filename(files[0].parent.name,output_name)
    folder=target.parent
    if target.exists():raise ValueError('同名文件已存在，请修改输出名称后重试。')
    partial=target.with_name(target.stem+'.'+uuid.uuid4().hex[:8]+'.part.mp4')
    diagnostics.event(root,'无损合并','start',bytes=sum(p.stat().st_size for p in files),duration=duration)
    try:
        # A private temporary directory supplies simple relative names to ffconcat,
        # so quotes/newlines in the drama title cannot alter its manifest.
        with tempfile.TemporaryDirectory(prefix='.merge-',dir=str(folder)) as temp:
            workspace=Path(temp)
            for i,path in enumerate(files):(workspace/f'{i}.mp4').symlink_to(path)
            listing=workspace/'list.txt'
            listing.write_text(''.join(f"file '{i}.mp4'\n" for i in range(len(files))),encoding='utf-8')
            command=['ffmpeg','-v','error','-nostdin','-n','-f','concat','-auto_convert','0','-safe','0','-i',str(listing),'-map','0','-c','copy','-movflags','+faststart',str(partial)]
            result=merge_progress.run(command,duration,max(180,int(duration)),"正在合并",boundaries)
            if result.returncode:raise ValueError('源文件无法直接拼接，未进行转码；请检查各集参数。')
        output,actual=probe(partial)
        if selective:
            keys=('codec_type','codec_name','width','height','pix_fmt','sample_rate','channels')
            if [{k:x.get(k) for k in keys} for x in output]!=[{k:x.get(k) for k in keys} for x in signature]: raise ValueError('合并后参数不匹配，未保存结果。')
        if output!=signature and not selective:raise ValueError('合并后媒体参数发生变化，未保存结果。')
        if abs(actual-duration)>max(2,len(files)*.1):raise ValueError('合并文件时长与源文件总时长不符。')
        check=merge_progress.run(['ffmpeg','-v','error','-xerror','-nostdin','-i',str(partial),'-f','null','-'],actual,max(180,int(duration*2)),"正在完整解码校验")
        if check.returncode:raise ValueError('合并文件未通过完整解码校验，未保存结果。')
        # Create the final name atomically without overwriting an existing file.
        import os
        os.link(partial,target);partial.unlink()
        diagnostics.event(root,'无损合并','complete',duration=actual,bytes=target.stat().st_size,elapsedMs=round((time.monotonic()-started)*1000))
        return {'path':str(target),'bytes':target.stat().st_size,'duration':actual,'count':len(files),'mode':'stream-copy'}
    except Exception as error:
        partial.unlink(missing_ok=True)
        diagnostics.record(root,error,'无损合并')
        raise


def _compatible_merge(root, files, output_name, mode):
    if len(files)<2: raise ValueError('请至少添加两个视频文件。')
    files=[Path(p).resolve() for p in files]
    if not all(shutil.which(tool) for tool in ('ffmpeg','ffprobe')): raise ValueError('需要安装 FFmpeg 和 ffprobe。')
    profiles=[]; rates=[]
    for path in files:
        if not path.is_file() or path.suffix.lower()!='.mp4': raise ValueError('源文件不是可读取的 MP4。')
        streams,seconds=probe(path)
        if seconds<=0: raise ValueError('源文件时长无效。')
        video=next(x for x in streams if x['codec_type']=='video')
        profiles.append((video,seconds))
        result=subprocess.run(['ffprobe','-v','error','-select_streams','v:0','-show_entries','stream=avg_frame_rate','-of','json',str(path)],capture_output=True,check=True,timeout=30)
        try: rate=Fraction(json.loads(result.stdout)['streams'][0]['avg_frame_rate'])
        except (ValueError,KeyError,IndexError,ZeroDivisionError): rate=Fraction(30)
        rates.append(rate if 0<rate<=120 else Fraction(30))
    fps=str(rates[0]) if all(r==rates[0] for r in rates) else '30'
    first=profiles[0][0]
    width,height=(1080,1920) if first['height']>=first['width'] else (1920,1080)
    target=files[0].parent/output_filename(files[0].parent.name,output_name)
    if target.exists(): raise ValueError('同名文件已存在，请修改输出名称后重试。')
    encoder=['-c:v','libx264','-crf','18','-preset','medium']
    if mode=='compatible-fast':
        encoder=['-c:v','h264_videotoolbox','-b:v','8M','-allow_sw','0']
    # Normalize each input separately to bound open files and memory for large lists.
    with tempfile.TemporaryDirectory(prefix='.compatible-',dir=str(target.parent)) as temp:
        normalized=[]
        for i,(path,(_,seconds)) in enumerate(zip(files,profiles)):
            output=Path(temp)/f'{i}.mp4'
            filters=f'scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p,setpts=PTS-STARTPTS'
            command=['ffmpeg','-v','error','-nostdin','-n','-i',str(path),'-map','0:v:0','-map','0:a:0','-map_metadata','-1','-vf',filters,'-af','aresample=48000,asetpts=PTS-STARTPTS,apad',*encoder,'-pix_fmt','yuv420p','-tag:v','avc1','-video_track_timescale','90000','-c:a','aac','-ar','48000','-ac','2','-b:a','192k','-t',str(seconds),str(output)]
            diagnostics.event(root,'兼容合并编码','start',episodeId=str(i+1),duration=seconds)
            try: result=merge_progress.run(command,seconds,max(600,int(seconds*30)),f"正在转码第 {i+1}/{len(files)} 个文件：{path.name}")
            except subprocess.TimeoutExpired: raise ValueError(f'第 {i+1} 个文件兼容编码超时，源文件保留。') from None
            if result.returncode:
                raise ValueError(f'第 {i+1} 个文件兼容编码失败。'+('硬件编码可能不可用，请选择画质优先。' if mode=='compatible-fast' else '请检查文件和磁盘空间。'))
            normalized.append(output)
        result=_merge_files(root,normalized,target=target)
        result['mode']=mode
        return result


def output_filename(folder_name,requested=None):
    if requested is None or requested=='':
        base=re.sub(r'[\\/:*?"<>|\x00-\x1f]', '_', folder_name).strip('. ') or '视频'
        while len(base.encode('utf-8'))>160:base=base[:-1]
        return base+'-'+datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H%M%S')+'.mp4'
    if not isinstance(requested,str):raise ValueError('输出名称必须为文字。')
    name=requested.strip()
    if name.lower().endswith('.mp4'):name=name[:-4]
    if not name or name in ('.','..') or re.search(r'[\\/:*?"<>|\x00-\x1f]',name) or len(name.encode('utf-8'))>220:
        raise ValueError('输出名称无效，请勿使用路径、特殊符号或过长名称。')
    return name+'.mp4'

def merge_files(root,files,target=None,output_name=None,mode="stream-copy"):
    try:
        if mode not in ("stream-copy","majority","compatible-quality","compatible-fast"): raise ValueError("未知合并模式。")
        result=merge_compare.selective(root,files,output_name,__import__(__name__)) if mode=="majority" else _merge_files(root,files,target,output_name) if mode=="stream-copy" else _compatible_merge(root,files,output_name,mode)
    except Exception as error:
        try:merge_history.record(root,files,error=error)
        except Exception as logging_error:diagnostics.record(root,logging_error,'合并历史保存')
        raise
    try:merge_history.record(root,files,result=result)
    except Exception as error:
        diagnostics.record(root,error,'合并历史保存')
        result['historyWarning']='文件已保存，但历史记录写入失败。'
    return result
