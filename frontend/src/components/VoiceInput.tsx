"use client";

import { useState, useRef, useCallback } from "react";
import { Mic, MicOff } from "lucide-react";

interface Props {
  onTranscript: (text: string) => void;
  disabled: boolean;
}

/**
 * Push-to-talk voice input using the Web Speech API.
 * When the browser does not support it, the button is hidden.
 */
export function VoiceInput({ onTranscript, disabled }: Props) {
  const [listening, setListening] = useState(false);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

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

    const SpeechRecognition =
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    const rec = new SpeechRecognition() as SpeechRecognition;
    rec.continuous = false;
    rec.interimResults = false;
    rec.lang = "en-US";

    rec.onresult = (event: SpeechRecognitionEvent) => {
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
