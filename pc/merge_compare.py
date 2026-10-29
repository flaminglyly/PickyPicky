"""Inspect selected files and normalize only outliers to the largest format group."""
import json, subprocess, tempfile
import merge_progress
from pathlib import Path
from fractions import Fraction

KEYS=('codec_name','profile','width','height','pix_fmt','sample_aspect_ratio','color_range','color_space','color_transfer','color_primaries','sample_rate','channels','channel_layout')
def inspect(path):
    r=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,timeout=30)
    if r.returncode: raise ValueError(f'无法读取文件：{Path(path).name}')
    d=json.loads(r.stdout); streams=d.get('streams',[])
    if len(streams)!=2 or {x['codec_type'] for x in streams}!={'video','audio'}:raise ValueError('要求一个视频轨和一个音频轨。')
    v=next(x for x in streams if x['codec_type']=='video');a=next(x for x in streams if x['codec_type']=='audio')
    result={f'{prefix}.{k}':s[k] for prefix,s in [('video',v),('audio',a)] for k in KEYS if k in s}
    try: result['video.fps']=str(Fraction(v['avg_frame_rate']))
    except (ValueError,KeyError,ZeroDivisionError):raise ValueError('无法确定源视频帧率。')
    return result

def compare(files):
    if len(files)<2:raise ValueError('请至少选择两个文件。')
    formats=[inspect(p) for p in files];groups={}
    for i,fmt in enumerate(formats):groups.setdefault(json.dumps(fmt,sort_keys=True),[]).append(i)
    ranked=sorted(groups.values(),key=lambda x:(-len(x),x[0]));indices=ranked[0];target=formats[indices[0]]
    return {'target':target,'reference':Path(files[indices[0]]).name,'majorityCount':len(indices),'total':len(files),'tied':len(ranked)>1 and len(ranked[0])==len(ranked[1]),'files':[{'name':Path(p).name,'index':i+1,'different':i not in indices,'format':f,'differences':[{'field':k,'value':f.get(k),'target':target.get(k)} for k in sorted(set(f)|set(target)) if f.get(k)!=target.get(k)]} for i,(p,f) in enumerate(zip(files,formats))]}

def selective(root,files,output_name,merge_module):
    files=[Path(p).resolve() for p in files];report=compare(files);t=report['target']
    codec=t['video.codec_name'];audio=t['audio.codec_name']
    if codec not in ('h264','hevc') or audio!='aac':raise ValueError('仅重编码差异文件目前支持 H.264/HEVC + AAC；请使用全量兼容模式。')
    if t.get('video.sample_aspect_ratio','1:1') not in ('1:1','0:1'):raise ValueError('多数文件使用非方形像素，请使用全量兼容模式。')
    if t.get('video.pix_fmt')!='yuv420p':raise ValueError('多数文件不是 8 位 YUV420；请使用全量兼容模式。')
    target=files[0].parent/merge_module.output_filename(files[0].parent.name,output_name)
    if target.exists():raise ValueError('同名文件已存在，请修改名称。')
    with tempfile.TemporaryDirectory(prefix='.selective-',dir=str(target.parent)) as folder:
        segments=[]
        for i,(path,row) in enumerate(zip(files,report['files'])):
            out=Path(folder)/f'{i}.ts';cmd=['ffmpeg','-v','error','-nostdin','-n','-i',str(path),'-map','0:v:0','-map','0:a:0']
            if row['different']:
                w,h=t['video.width'],t['video.height'];fps=t['video.fps']
                cmd+=['-vf',f'scale={w}:{h}:force_original_aspect_ratio=decrease:force_divisible_by=2,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps},format=yuv420p','-c:v','libx264' if codec=='h264' else 'libx265','-crf','18','-preset','medium']
                profiles={'High':'high','Main':'main','Constrained Baseline':'baseline'}
                if t.get('video.profile') in profiles:cmd+=['-profile:v',profiles[t['video.profile']]]
                if codec=='hevc':cmd+=['-x265-params','log-level=error']
                for field,flag in [('color_range','-color_range'),('color_space','-colorspace'),('color_transfer','-color_trc'),('color_primaries','-color_primaries')]:
                    value=t.get('video.'+field)
                    if value and value!='unknown':cmd += [flag,str(value)]
                cmd+=['-c:a','aac','-ar',str(t['audio.sample_rate']),'-ac',str(t['audio.channels']),'-b:a','192k']
            else:cmd+=['-c','copy']
            cmd+=['-bsf:v','h264_mp4toannexb' if codec=='h264' else 'hevc_mp4toannexb','-f','mpegts',str(out)]
            seconds=merge_module.probe(path)[1]
            r=merge_progress.run(cmd,seconds,max(600,int(seconds*30)),f"{'正在转码' if row['different'] else '正在复制原编码'}第 {i+1}/{len(files)} 个文件：{path.name}")
            if r.returncode:raise ValueError(f'第 {i+1} 项处理失败，请选择全量兼容模式。')
            segments.append(out)
        # Transport streams carry per-segment codec headers, avoiding one MP4 header
        # being incorrectly reused for independently encoded segments.
        result=merge_module._merge_files(root,segments,target=target,selective=True)
        result.update(mode='majority',reencoded=sum(x['different'] for x in report['files']))
        return result
