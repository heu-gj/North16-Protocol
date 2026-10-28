"""Extraction progress on stderr; stdout remains a machine-readable report."""
import sys
import time


class ExtractionProgress:
    def __init__(self, stream=None):
        self.stream=stream if stream is not None else sys.stderr
        self.tty=self.stream.isatty()
        self.last_time=0
        self.last_token=None
        self.width=0

    def __call__(self, event):
        phase=event['phase']
        total=event.get('total')
        done=event.get('done',0)
        percent=min(99,int(done*100/total)) if total and phase=='decode' else (
            min(99,int(done*100/total)) if total and phase=='verify' else None)
        token=(event.get('stream_index'),phase,percent//10 if percent is not None else done//100)
        now=time.monotonic()
        final=phase in ('stream_done','done','failed')
        if not final and token==self.last_token and (not self.tty or now-self.last_time<.2):return
        if self.tty and not final and now-self.last_time<.2 and token[:2]==(self.last_token or ())[:2]:return
        self.last_time=now;self.last_token=token
        if phase=='done':
            text=f"[####################] 100% 完成：{event['streams']} 路 / {event['images']} 张图片"
        elif phase=='failed':text='抽帧失败；详见错误信息，未完成镜头不标记为成功。'
        else:
            scope=f"[{event['stream_index']}/{event['streams']}] {event['sequence']}/{event['sensor']}/{event['camera']}"
            if phase=='preflight':detail='预检：校验原视频与容量'
            elif phase=='stream_start':detail='开始处理'
            elif phase=='decode':
                bar='?'*20 if percent is None else '#'*int(percent/5)+'-'*(20-int(percent/5))
                detail=f"[{bar}] "+(f"约 {percent}% " if percent is not None else '')+f"已解码 {done} 帧 / 已选输出 {event.get('selected',0)} 帧"
            elif phase=='verify':detail=f"校验图片与生成元信息 {done}/{total}"
            elif phase=='publish':detail='校验原视频并提交镜头'
            else:detail=f"{'复用' if event.get('reused') else '完成'} {event.get('images',0)} 张"
            text=scope+' · '+detail
        if self.tty:
            self.stream.write('\r'+text+' '*max(0,self.width-len(text)))
            self.width=len(text)
            if final:self.stream.write('\n');self.width=0
        else:self.stream.write(text+'\n')
        self.stream.flush()
