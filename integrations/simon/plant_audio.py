"""Plant-only bounded waits and PCM packing. No playback or network side effects."""
from array import array
from threading import Event, Lock, Thread
import sys
from .core import Audio

class CallCancelled(Exception):pass
class CallBusy(Exception):pass

class CancellableCall:
    """At most one outstanding operation, even after the caller cancels.

    A remote operation already accepted may complete; its late result is dropped.
    Callers must not retry writes on cancellation. The operation owns its timeout.
    """
    def __init__(self):self._lock=Lock()
    @property
    def busy(self):return self._lock.locked()
    def run(self,operation,guard):
        if not guard():raise CallCancelled()
        if not self._lock.acquire(False):raise CallBusy()
        done=Event();result=[]
        def work():
            try:result.append((True,operation()))
            except Exception as exc:result.append((False,exc))
            finally:self._lock.release();done.set()
        try:Thread(target=work,daemon=True).start()
        except BaseException:self._lock.release();raise
        while not done.wait(.02):
            if not guard():raise CallCancelled()
        if not guard():raise CallCancelled()
        ok,value=result[0]
        if not ok:raise value
        return value

def phrase_frames(parts):
    """Reassemble first, then split only inside >=100ms quiet PCM runs.

    Exact sample conservation; <=30s total, <=15s per existing native frame.
    No synthesis retries, fades, rate change, clipping or per-chunk normalization.
    If speech has no usable pause, refuse before playing rather than cut a word.
    """
    if type(parts) is not tuple or not 1<=len(parts)<=6:raise ValueError('bounded_parts_required')
    if any(not isinstance(a,Audio) or not a.pcm or len(a.pcm)%2 for a in parts):raise ValueError('bounded_parts_required')
    if sum(len(a.pcm) for a in parts)>30*32000:raise ValueError('bounded_parts_required')
    raw=b''.join(a.pcm for a in parts)
    if len(raw)<=480000:return (Audio(raw),)
    samples=array('h');samples.frombytes(raw)
    if sys.byteorder!='little':samples.byteswap()
    quiet=[];start=None
    for i,value in enumerate(samples):
        if abs(value)<=160:
            if start is None:start=i
        else:
            if start is not None and i-start>=1600:quiet.append((start,i))
            start=None
    if start is not None and len(samples)-start>=1600:quiet.append((start,len(samples)))
    frames=[];offset=0;limit=240000
    while len(samples)-offset>limit:
        cuts=[]
        for a,b in quiet:
            lo=max(a+800,offset+16000);hi=min(b-800,offset+limit)
            if lo<=hi:cuts.append(max(lo,min((a+b)//2,hi)))
        if not cuts:raise ValueError('no_safe_speech_pause')
        cut=max(cuts);frames.append(Audio(raw[offset*2:cut*2]));offset=cut
    frames.append(Audio(raw[offset*2:]))
    return tuple(frames)
