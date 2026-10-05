"""Package unmodified actual JPEG captures as a clearly labeled stage playback.

Standard-library Motion-JPEG AVI, 3s per capture, and an accessible HTML timeline.
This is capture playback, not continuous real-time screen recording.
"""
import argparse
import html
import json
from pathlib import Path
import shutil
import struct
import subprocess

def jpeg_size(data):
    if data[:2]!=b'\xff\xd8':raise ValueError('Expected actual JPEG screenshot')
    i=2
    while i<len(data):
        if data[i]!=255:raise ValueError('Malformed JPEG header')
        while data[i]==255:i+=1
        marker=data[i];i+=1
        if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7:continue
        length=int.from_bytes(data[i:i+2],'big');start=i+2
        if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
            return int.from_bytes(data[start+3:start+5],'big'),int.from_bytes(data[start+1:start+3],'big')
        i+=length
    raise ValueError('JPEG dimensions missing')

def chunk(kind,data):return kind+struct.pack('<I',len(data))+data+(b'\0' if len(data)%2 else b'')
def listing(kind,data):return chunk(b'LIST',kind+data)

def avi(frames):
    sizes=[jpeg_size(f) for f in frames]
    if len(set(sizes))!=1:raise ValueError('Native capture dimensions differ; preserve captures rather than silently resize')
    width,height=sizes[0];maximum=max(map(len,frames));count=len(frames)
    avih=struct.pack('<14I',1000000,maximum,0,0x10,count,0,1,maximum,width,height,0,0,0,0)
    strh=struct.pack('<4s4sIHHIIIIIIIIhhhh',b'vids',b'MJPG',0,0,0,0,1,1,0,count,maximum,0xffffffff,0,0,0,width,height)
    strf=struct.pack('<IiiHH4sIiiII',40,width,height,1,24,b'MJPG',width*height*3,0,0,0,0)
    header=listing(b'hdrl',chunk(b'avih',avih)+listing(b'strl',chunk(b'strh',strh)+chunk(b'strf',strf)))
    movi=b'';index=b'';offset=4
    for frame in frames:
        block=chunk(b'00dc',frame);index+=struct.pack('<4sIII',b'00dc',0x10,offset,len(frame));movi+=block;offset+=len(block)
    body=b'AVI '+header+listing(b'movi',movi)+chunk(b'idx1',index)
    return b'RIFF'+struct.pack('<I',len(body))+body,(width,height)

def validate(data,frame_count):
    assert data[:4]==b'RIFF' and data[8:12]==b'AVI ' and int.from_bytes(data[4:8],'little')==len(data)-8
    offset=12;frames=0;index_count=0
    while offset<len(data):
        kind=data[offset:offset+4];size=int.from_bytes(data[offset+4:offset+8],'little');body=offset+8
        assert body+size<=len(data)
        if kind==b'LIST' and data[body:body+4]==b'movi':
            position=body+4
            while position<body+size:
                assert data[position:position+4]==b'00dc'
                length=int.from_bytes(data[position+4:position+8],'little');jpeg_size(data[position+8:position+8+length]);frames+=1;position+=8+length+length%2
            assert position==body+size
        if kind==b'idx1':assert size%16==0;index_count=size//16
        offset+=8+size+size%2
    assert offset==len(data) and frames==index_count==frame_count

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('evidence',type=Path);parser.add_argument('output',type=Path);parser.add_argument('--mp4',action='store_true',help='Also convert with the optional macOS built-in avconvert');args=parser.parse_args()
    proof=json.loads((args.evidence/'browser-proof.json').read_text());captures=proof['captures'];args.output.mkdir(parents=True,exist_ok=True)
    images=[];copied=[]
    for record in captures:
        name=record['file'];source=args.evidence/name
        if Path(name).name!=name or source.suffix!='.jpg':raise ValueError('Expected local capture filename')
        image=source.read_bytes();jpeg_size(image);shutil.copyfile(source,args.output/name);images.extend([image]*3);copied.append(record)
    data,size=avi(images);validate(data,len(images));(args.output/'s09-stage-playback.avi').write_bytes(data)
    if args.mp4:
        converter=shutil.which('avconvert')
        if not converter:raise RuntimeError('Optional MP4 conversion requires macOS avconvert; AVI and original captures remain available')
        subprocess.run([converter,'--source',str(args.output/'s09-stage-playback.avi'),'--preset','PresetHighestQuality','--output',str(args.output/'s09-stage-playback.mp4'),'--replace'],check=True)
    metadata=dict(runId=proof['runId'],type='Actual capture stage playback',secondsPerCapture=3,framesPerSecond=1,
                  durationSeconds=len(images),nativePixels=list(size),unmodifiedJpegFrames=True,captures=copied,
                  aviStructureValidated=True,continuousRealtimeRecording=False,mp4Available=args.mp4,mp4Method='Optional macOS avconvert PresetHighestQuality; encoded derivative, original JPEG/AVI preserved' if args.mp4 else None)
    (args.output/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    rows=''.join(f'<li><button data-index="{n}">{html.escape(r["stage"])}</button> · {html.escape(r["capturedAt"])}<p>{html.escape(r["caption"])}</p></li>' for n,r in enumerate(copied))
    encoded=json.dumps(copied,ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>S09 실제 관제 단계 캡처</title><style>body{margin:30px auto;padding:0 20px;max-width:1100px;background:white;color:#102950;font:16px/1.6 system-ui}button,a{color:#315db2}button{background:#eef4fd;border:1px solid #c2d3ed;border-radius:8px;padding:8px 14px;cursor:pointer}img{display:block;max-width:100%;border:1px solid #d6e1f2}li{margin:12px 0}#caption{min-height:3em}small{color:#475b7a}</style><h1>실제 관제 화면의 단계별 기록</h1><p>같은 새 실행의 실제 캡처를 각 3초씩 재생합니다.</p><p><small>실행: RUN_ID</small></p><button id="play">단계 재생</button> <a href="s09-stage-playback.avi" download>MJPEG 단계 영상 다운로드</a><p id="caption" aria-live="polite"></p><img id="frame" alt="현재 단계의 실제 관제 캡처"><ol>ROWS</ol><script>const captures=CAPTURES;let index=0,timer;const frame=document.getElementById('frame'),caption=document.getElementById('caption'),play=document.getElementById('play');function show(n){index=n;frame.src=captures[n].file;frame.alt=captures[n].caption;caption.textContent=captures[n].stage+' · '+captures[n].caption}function stop(){clearInterval(timer);timer=null;play.textContent='단계 재생'}play.onclick=()=>{if(timer){stop();return}show(0);play.textContent='재생 멈춤';timer=setInterval(()=>{if(index+1===captures.length){stop();return}show(index+1)},3000)};document.querySelectorAll('[data-index]').forEach(button=>button.onclick=()=>{stop();show(Number(button.dataset.index))});show(0)</script></html>'''
    page=page.replace('RUN_ID',html.escape(proof['runId'])).replace('ROWS',rows).replace('CAPTURES',encoded)
    if metadata['mp4Available']:
        page=page.replace('<ol>', f'<p><a href="s09-stage-playback.mp4" download>MP4 단계 영상 다운로드</a></p><video controls preload="metadata" style="max-width:100%" src="s09-stage-playback.mp4" aria-label="실제 캡처 {len(copied)}장의 단계 재생 영상"></video><ol>')
    (args.output/'index.html').write_text(page)
    print('Packaged',len(copied),'actual captures;',len(images),'seconds; AVI RIFF/frame/index counts verified')

if __name__=='__main__':main()
