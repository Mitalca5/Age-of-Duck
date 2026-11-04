"""Read only valid, complete PCM clips; no audio device is needed."""
import wave

def clip_duration(path):
    with wave.open(str(path),'rb') as clip:
        frames=clip.getnframes();rate=clip.getframerate()
        if frames<=0 or rate<=0:
            raise ValueError('Empty voice clip')
        clip.setpos(frames-1)
        if len(clip.readframes(1))!=clip.getnchannels()*clip.getsampwidth():
            raise ValueError('Truncated voice clip')
        return frames/rate

def prepare_cache(folder,count):
    """Remove damaged cached files so the synthesizer can regenerate them."""
    complete=True
    for i in range(count):
        path=folder/f'{i}.wav'
        try:clip_duration(path)
        except (OSError,ValueError,wave.Error,EOFError):
            complete=False
            path.unlink(missing_ok=True)
    return complete
