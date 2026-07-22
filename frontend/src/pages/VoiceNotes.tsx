import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "../api";
import { Icon } from "../icons";
import { mdComponents, mdRehypePlugins, mdRemarkPlugins } from "../markdown";
import type { VoiceNoteResult, VoiceNoteStatus } from "../types";

type RecorderState = "idle" | "recording";

export function VoiceNotesPage({ onOpenNote }: { onOpenNote: (path: string) => void }) {
  const [status, setStatus] = useState<VoiceNoteStatus | null>(null);
  const [source, setSource] = useState<{ blob: Blob; filename: string } | null>(null);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const [recorderState, setRecorderState] = useState<RecorderState>("idle");
  const [title, setTitle] = useState("");
  const [course, setCourse] = useState("");
  const [folder, setFolder] = useState("Voice Notes");
  const [write, setWrite] = useState(true);
  const [transcribing, setTranscribing] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [transcript, setTranscript] = useState("");
  const [whisperModel, setWhisperModel] = useState<string | null>(null);
  const [result, setResult] = useState<VoiceNoteResult | null>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    api.voiceNoteStatus()
      .then((next) => alive && setStatus(next))
      .catch((e) => alive && setError((e as Error).message));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    if (!source) {
      setAudioUrl(null);
      return;
    }
    const url = URL.createObjectURL(source.blob);
    setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [source]);

  const pickFile = (file: File | null) => {
    if (!file) return;
    setSource({ blob: file, filename: file.name });
    setTranscript("");
    setWhisperModel(null);
    setResult(null);
    setError(null);
  };

  const startRecording = async () => {
    setError(null);
    setResult(null);
    setTranscript("");
    setWhisperModel(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const preferred = "audio/webm";
      const mimeType = MediaRecorder.isTypeSupported(preferred) ? preferred : "";
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      chunksRef.current = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((track) => track.stop());
        const blob = new Blob(chunksRef.current, { type: mimeType || "audio/webm" });
        setSource({ blob, filename: `voice-note-${Date.now()}.webm` });
        setRecorderState("idle");
      };
      recorderRef.current = recorder;
      recorder.start();
      setRecorderState("recording");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const stopRecording = () => {
    recorderRef.current?.stop();
  };

  const transcribe = async () => {
    if (!source) return;
    setTranscribing(true);
    setError(null);
    try {
      const next = await api.transcribeVoiceNote({
        audio: source.blob,
        filename: source.filename,
      });
      setTranscript(next.transcript);
      setWhisperModel(next.whisper_model_path);
      setResult(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setTranscribing(false);
    }
  };

  const generate = async () => {
    if (!transcript.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      const next = await api.generateVoiceNoteFromTranscript({
        transcript: transcript.trim(),
        title: title.trim() || null,
        course: course.trim() || null,
        folder: folder.trim() || "Voice Notes",
        write,
      });
      setResult(next);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setGenerating(false);
    }
  };

  const transcribeBlockers = [
    status && !status.enabled ? "Voice notes are disabled." : null,
    status && !status.model_exists ? "Whisper model is missing or still empty." : null,
    status?.model_is_partial ? "Whisper model download is still incomplete." : null,
    status && !status.whisper_cli_available ? "whisper-cli is not available." : null,
    status && !status.ffmpeg_available ? "ffmpeg is not available." : null,
  ].filter(Boolean);

  return (
    <div className="voice-page">
      <section className="voice-panel">
        <div className="section-head">
          <div>
            <h2>Voice Notes</h2>
            <div className="muted small">
              Model: {status?.model_path ?? "not configured"}
            </div>
          </div>
          <button
            className="icon-btn"
            title="Refresh status"
            onClick={() => api.voiceNoteStatus().then(setStatus).catch((e) => setError((e as Error).message))}
          >
            <Icon name="refresh-cw" size={16} />
          </button>
        </div>

        {transcribeBlockers.length > 0 && (
          <div className="warn-banner">{transcribeBlockers.join(" ")}</div>
        )}
        {error && <div className="warn-banner">{error}</div>}

        <div className="voice-actions">
          {recorderState === "recording" ? (
            <button className="primary" onClick={stopRecording}>
              <Icon name="stop" size={16} /> Stop
            </button>
          ) : (
            <button onClick={startRecording}>
              <Icon name="mic" size={16} /> Record
            </button>
          )}
          <button onClick={() => fileRef.current?.click()}>
            <Icon name="upload" size={16} /> Upload
          </button>
          <input
            ref={fileRef}
            type="file"
            accept="audio/*,.m4a,.webm,.mp3,.wav,.ogg,.opus,.flac"
            hidden
            onChange={(event) => pickFile(event.target.files?.[0] ?? null)}
          />
          {source && (
            <button
              className="icon-btn"
              title="Clear audio"
              onClick={() => {
                setSource(null);
                setTranscript("");
                setWhisperModel(null);
                setResult(null);
              }}
            >
              <Icon name="trash" size={16} />
            </button>
          )}
        </div>

        {audioUrl && (
          <div className="voice-audio">
            <audio controls src={audioUrl} />
            <span className="muted small">{source?.filename}</span>
          </div>
        )}

        <div className="voice-form">
          <label>
            <span>Title</span>
            <input value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            <span>Course</span>
            <input value={course} onChange={(event) => setCourse(event.target.value)} />
          </label>
          <label>
            <span>Folder</span>
            <input value={folder} onChange={(event) => setFolder(event.target.value)} />
          </label>
          <label className="voice-check">
            <input
              type="checkbox"
              checked={write}
              onChange={(event) => setWrite(event.target.checked)}
            />
            <span>Save note</span>
          </label>
        </div>

        <button
          className="primary voice-generate"
          disabled={!source || transcribing || transcribeBlockers.length > 0}
          onClick={transcribe}
        >
          <Icon name="mic" size={16} />
          {transcribing ? "Transcribing..." : "1. Transcribe speech"}
        </button>

        <div className="voice-transcript">
          <div className="section-head compact">
            <div>
              <h2>Transcript</h2>
              {whisperModel && <div className="muted small">Whisper: {whisperModel}</div>}
            </div>
          </div>
          <textarea
            value={transcript}
            onChange={(event) => {
              setTranscript(event.target.value);
              setResult(null);
            }}
            placeholder="Transcript appears here after step 1."
          />
        </div>

        <button
          className="primary voice-generate"
          disabled={!transcript.trim() || generating}
          onClick={generate}
        >
          <Icon name="sparkles" size={16} />
          {generating ? "Generating..." : "2. Turn text into notes"}
        </button>
      </section>

      <section className="voice-output">
        {!result ? (
          <div className="empty-state">Transcribe audio, review the text, then generate notes.</div>
        ) : (
          <>
            <div className="section-head">
              <div>
                <h2>{result.title}</h2>
                <div className="muted small">LLM: {result.model}</div>
              </div>
              {result.target_path && (
                <button onClick={() => onOpenNote(result.target_path!)}>
                  <Icon name="file-text" size={16} /> Open
                </button>
              )}
            </div>
            {result.written && result.target_path && (
              <div className="note-banner">Saved to {result.target_path}</div>
            )}
            <div className="voice-preview md">
              <ReactMarkdown
                components={mdComponents}
                remarkPlugins={mdRemarkPlugins}
                rehypePlugins={mdRehypePlugins}
              >
                {result.markdown}
              </ReactMarkdown>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
