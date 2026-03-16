"use client";

import { useState, KeyboardEvent } from "react";
import { Send, RotateCcw, Square, ChevronRight } from "lucide-react";

interface Props {
  onSubmit: (goal: string) => void;
  onStop: () => void;
  running: boolean;
  disabled: boolean;
  canContinue?: boolean;
}

const EXAMPLE_GOALS = [
  "Go to google.com and search for 'best coffee shops near me'",
  "Open YouTube and search for 'Gemini AI demo'",
  "Navigate to Wikipedia and look up 'Large Language Model'",
  "Go to github.com and find the trending repositories today",
];

export function CommandPanel({ onSubmit, onStop, running, disabled, canContinue }: Props) {
  const [goal, setGoal] = useState("");

  const handleSubmit = () => {
    const trimmed = goal.trim();
    if (!trimmed || disabled) return;
    onSubmit(trimmed);
    setGoal("");
  };

  const handleContinue = () => {
    if (disabled) return;
    onSubmit("");  // Empty goal signals to reuse previous goal
    setGoal("");
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="relative">
        <textarea
          value={goal}
          onChange={(e) => setGoal(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            disabled
              ? "Share your screen first to get started…"
              : "What would you like me to do? (e.g. 'Find flights from NYC to LA next Friday')"
          }
          disabled={disabled || running}
          rows={3}
          className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm
                     text-white placeholder-white/30 resize-none outline-none
                     focus:border-brand-500/60 focus:ring-1 focus:ring-brand-500/30
                     disabled:opacity-40 disabled:cursor-not-allowed transition-all"
        />
        <div className="absolute bottom-2.5 right-2.5 text-xs text-white/20">
          Enter to send · Shift+Enter for newline
        </div>
      </div>

      <div className="flex gap-2">
        {running ? (
          <button
            onClick={onStop}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-500/20
                       border border-red-500/40 text-red-300 hover:bg-red-500/30
                       transition-all text-sm font-medium"
          >
            <Square size={14} />
            Stop Agent
          </button>
        ) : canContinue ? (
          <button
            onClick={handleContinue}
            disabled={disabled}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-500/20
                       border border-brand-500/40 text-brand-300 hover:bg-brand-500/30
                       disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all text-sm font-medium flex-1"
          >
            <ChevronRight size={14} />
            Continue Step
          </button>
        ) : (
          <button
            onClick={handleSubmit}
            disabled={disabled || !goal.trim()}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-brand-500/20
                       border border-brand-500/40 text-brand-300 hover:bg-brand-500/30
                       disabled:opacity-40 disabled:cursor-not-allowed
                       transition-all text-sm font-medium flex-1"
          >
            <Send size={14} />
            Run Agent
          </button>
        )}
      </div>

      {/* Quick examples */}
      {!running && !disabled && (
        <div className="flex flex-col gap-1.5">
          <p className="text-xs text-white/30 font-medium uppercase tracking-wider">
            Examples
          </p>
          <div className="flex flex-col gap-1">
            {EXAMPLE_GOALS.map((eg) => (
              <button
                key={eg}
                onClick={() => setGoal(eg)}
                className="text-left text-xs text-white/40 hover:text-white/70
                           px-2 py-1 rounded hover:bg-white/5 transition-all"
              >
                → {eg}
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
