"use client";

import { useEffect, useRef } from "react";
import type { ServerMessage } from "@/lib/websocket";
import { Brain, MousePointer, AlertCircle, CheckCircle, Info } from "lucide-react";
import { clsx } from "clsx";

interface Props {
  messages: ServerMessage[];
}

function ActionBadge({ type }: { type: string }) {
  return (
    <span className="text-[10px] font-mono bg-white/10 text-white/50 px-1.5 py-0.5 rounded">
      {type}
    </span>
  );
}

export function SessionLog({ messages }: Props) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  if (messages.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-32 text-white/20 text-sm">
        <Info size={20} className="mb-2" />
        Agent activity will appear here
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 overflow-y-auto max-h-80 pr-1">
      {messages.map((msg, i) => (
        <div
          key={i}
          className={clsx("flex gap-2.5 text-sm rounded-lg p-2.5 border", {
            "bg-blue-500/5 border-blue-500/20": msg.type === "thinking",
            "bg-green-500/5 border-green-500/20":
              msg.type === "action" && msg.action?.type === "done",
            "bg-white/3 border-white/8": msg.type === "action" && msg.action?.type !== "done",
            "bg-red-500/5 border-red-500/20": msg.type === "error",
            "bg-white/3 border-white/5": msg.type === "status",
          })}
        >
          <div className="mt-0.5 shrink-0">
            {msg.type === "thinking" && <Brain size={14} className="text-blue-400" />}
            {msg.type === "action" && msg.action?.type !== "done" && (
              <MousePointer size={14} className="text-white/40" />
            )}
            {msg.type === "action" && msg.action?.type === "done" && (
              <CheckCircle size={14} className="text-green-400" />
            )}
            {msg.type === "error" && <AlertCircle size={14} className="text-red-400" />}
            {msg.type === "status" && <Info size={14} className="text-white/30" />}
          </div>

          <div className="flex flex-col gap-1 min-w-0">
            {msg.type === "thinking" && (
              <p className="text-blue-200/80 text-xs leading-relaxed">{msg.thinking}</p>
            )}
            {msg.type === "action" && msg.action && (
              <div className="flex items-center gap-2 flex-wrap">
                <ActionBadge type={msg.action.type} />
                {msg.action.description && (
                  <span className="text-white/50 text-xs">{msg.action.description}</span>
                )}
                {msg.action.type === "done" && (
                  <span className="text-green-300 text-xs">{msg.action.summary}</span>
                )}
                {msg.action.type === "navigate" && (
                  <span className="text-white/40 text-xs truncate max-w-[200px]">{msg.action.url}</span>
                )}
                {msg.action.type === "type" && (
                  <span className="text-white/40 text-xs">"{msg.action.text}"</span>
                )}
              </div>
            )}
            {msg.type === "error" && (
              <p className="text-red-300 text-xs">{msg.error}</p>
            )}
            {msg.type === "status" && (
              <p className="text-white/40 text-xs">{msg.status}</p>
            )}
          </div>
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
