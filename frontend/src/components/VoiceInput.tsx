"use client";

import { useState, useRef, useCallback } from "react";
import { Mic, MicOff } from "lucide-react";

interface Props {
  onTranscript: (text: string) => void;
  disabled: boolean;
}

// Minimal local types for the Web Speech API (not in every TS lib configuration)
interface ISpeechRecognition {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start(): void;
  stop(): void;
  onresult: ((event: ISpeechRecognitionEvent) => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}
interface ISpeechRecognitionEvent {
  results: { [index: number]: { [index: number]: { transcript: string } } };
}

/**
 * Push-to-talk voice input using the Web Speech API.
 * When the browser does not support it, the button is hidden.
 */
export function VoiceInput({ onTranscript, disabled }: Props) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<ISpeechRecognition | null>(null);

  const supported =
    typeof window !== "undefined" &&
    ("SpeechRecognition" in window || "webkitSpeechRecognition" in window);

  const toggle = useCallback(() => {
    if (!supported) return;

    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return;
    }

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const SpeechRecognitionCtor = (window as any).SpeechRecognition ||
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).webkitSpeechRecognition;
    const rec = new SpeechRecognitionCtor() as ISpeechRecognition;
    rec.continuous = false;
    rec.interimResults = false;
    rec.lang = "en-US";

    rec.onresult = (event: ISpeechRecognitionEvent) => {
      const transcript = event.results[0]?.[0]?.transcript ?? "";
      if (transcript) onTranscript(transcript);
    };

    rec.onend = () => {
      setListening(false);
      recognitionRef.current = null;
    };

    rec.onerror = () => {
      setListening(false);
      recognitionRef.current = null;
    };

    recognitionRef.current = rec;
    rec.start();
    setListening(true);
  }, [listening, onTranscript, supported]);

  if (!supported) return null;

  return (
    <button
      onClick={toggle}
      disabled={disabled}
      title={listening ? "Stop listening" : "Speak a command (push to talk)"}
      className={`p-2.5 rounded-lg border transition-all disabled:opacity-40 disabled:cursor-not-allowed ${
        listening
          ? "bg-red-500/20 border-red-500/40 text-red-300 animate-pulse"
          : "bg-white/5 border-white/10 text-white/40 hover:text-white/70 hover:bg-white/10"
      }`}
    >
      {listening ? <MicOff size={16} /> : <Mic size={16} />}
    </button>
  );
}
