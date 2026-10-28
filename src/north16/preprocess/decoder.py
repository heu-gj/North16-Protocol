"""Monitor the existing showinfo log without changing FFmpeg outputs or PTS."""
import re
import subprocess
import time

FRAME=re.compile(r'\bn:\s*(\d+)\s+pts:')


def run_decoder(command, log, *, progress=None, sampled=False, timeout=3600):
    if progress is None:
        with log.open('wb') as handle:
            return subprocess.run(command,stdout=subprocess.DEVNULL,stderr=handle,timeout=timeout).returncode
    decoded=selected=0
    remainder=b''
    def consume(reader, final=False):
        nonlocal remainder,decoded,selected
        chunk=reader.read()
        if not chunk and not final:return
        lines=(remainder+chunk).split(b'\n')
        remainder=lines.pop()
        if final and remainder:lines.append(remainder);remainder=b''
        changed=False
        for raw in lines:
            line=raw.decode('utf-8',errors='replace')
            match=FRAME.search(line)
            if not match:continue
            n=int(match[1])+1
            if not sampled or 'showinfo@source' in line:decoded=max(decoded,n);changed=True
            if not sampled or 'showinfo@selected' in line:selected=max(selected,n);changed=True
        if changed:progress(dict(phase='decode',done=decoded,selected=selected))
    with log.open('wb') as handle, log.open('rb') as reader:
        process=subprocess.Popen(command,stdout=subprocess.DEVNULL,stderr=handle)
        started=time.monotonic()
        try:
            while True:
                consume(reader)
                remaining=timeout-(time.monotonic()-started)
                if remaining<=0:raise subprocess.TimeoutExpired(command,timeout)
                try:
                    code=process.wait(timeout=min(.2,remaining))
                    consume(reader,final=True)
                    return code
                except subprocess.TimeoutExpired:
                    if time.monotonic()-started>=timeout:raise
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
