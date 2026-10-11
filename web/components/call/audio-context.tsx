"use client";
// One <audio> element per call page. It drives the playhead in the audio lanes and the transcript click-to-play.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

interface Ctx {
  available: boolean;       // false in fixtures mode (no audio) or after a load error
  error: string | null;
  time: number;
  playing: boolean;
  seek: (t: number) => void;
  play: (from?: number, loop?: { start: number; end: number } | null) => void;
  pause: () => void;
  loop: { start: number; end: number } | null;
  setLoop: (l: { start: number; end: number } | null) => void;
}

const AudioCtx = createContext<Ctx | null>(null);
export const useCallAudio = () => {
  const c = useContext(AudioCtx);
  if (!c) throw new Error("useCallAudio outside provider");
  return c;
};

export function CallAudioProvider({ src, children }: { src: string | null; children: React.ReactNode }) {
  const ref = useRef<HTMLAudioElement>(null);
  const [time, setTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [error, setError] = useState<string | null>(src ? null : "no audio in fixtures mode (*.wav is gitignored)");
  const [loop, setLoop] = useState<{ start: number; end: number } | null>(null);
  const loopRef = useRef(loop);
  useEffect(() => { loopRef.current = loop; }, [loop]);

  // Animation-frame clock while playing, so the playhead moves smoothly.
  useEffect(() => {
    const a = ref.current;
    if (!a || !playing) return;
    let raf = 0;
    const tick = () => {
      const l = loopRef.current;
      if (l && a.currentTime >= l.end) a.currentTime = l.start;
      setTime(a.currentTime);
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [playing]);

  const seek = useCallback((t: number) => {
    const a = ref.current;
    if (a && !error) a.currentTime = t;
    setTime(t);
  }, [error]);
  const play = useCallback((from?: number, l?: { start: number; end: number } | null) => {
    const a = ref.current;
    if (!a || error) return;
    if (l !== undefined) setLoop(l);
    if (from != null) a.currentTime = from;
    // a rejected play() (autoplay policy, a click without user activation) is not a broken file: keep audio usable
    void a.play().catch((e) => { if (e?.name !== "NotAllowedError" && e?.name !== "AbortError") setError(String(e?.message ?? e)); });
  }, [error]);
  const pause = useCallback(() => ref.current?.pause(), []);

  const value = useMemo<Ctx>(() => ({ available: !error && !!src, error, time, playing, seek, play, pause, loop, setLoop }),
    [error, src, time, playing, seek, play, pause, loop]);

  return (
    <AudioCtx.Provider value={value}>
      {src && (
        <audio ref={ref} src={src} preload="metadata" onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)} onSeeked={(e) => setTime(e.currentTarget.currentTime)}
          onError={() => setError("Audio could not be loaded (404 or unsupported).")} />
      )}
      {children}
    </AudioCtx.Provider>
  );
}
