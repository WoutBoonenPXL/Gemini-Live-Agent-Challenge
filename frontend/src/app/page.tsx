"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { Zap } from "lucide-react";
import { ScreenCapture } from "@/components/ScreenCapture";
import { ActionOverlay } from "@/components/ActionOverlay";
import { CommandPanel } from "@/components/CommandPanel";
import { SessionLog } from "@/components/SessionLog";
import { VoiceInput } from "@/components/VoiceInput";
import { ScreenPilotWebSocket, type ServerMessage, type AgentAction } from "@/lib/websocket";

const BACKEND_HTTP =
  process.env.NEXT_PUBLIC_BACKEND_HTTP_URL ??
  (typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "http://localhost:8000"
    : "https://screenpilot-backend-950824668815.us-central1.run.app");

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [wsClient, setWsClient] = useState<ScreenPilotWebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const [capturing, setCapturing] = useState(false);
  const [running, setRunning] = useState(false);
  const [messages, setMessages] = useState<ServerMessage[]>([]);
  const [uiError, setUiError] = useState<string | null>(null);
  const [currentAction, setCurrentAction] = useState<AgentAction | null>(null);
  const [screenDims, setScreenDims] = useState({ w: 1280, h: 720 });
  const [pendingFrame, setPendingFrame] = useState<{
    b64: string; w: number; h: number
  } | null>(null);
  // Playwright browser screenshot from backend
  const [pilotFrame, setPilotFrame] = useState<string | null>(null);

  const wsRef = useRef<ScreenPilotWebSocket | null>(null);
  const activeSessionIdRef = useRef<string | null>(null);
  const connectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ---------------------------------------------------------------------------
  // Create session + connect WebSocket
  // ---------------------------------------------------------------------------
  const startSession = useCallback(async (goal: string) => {
    try {
      if (
        wsRef.current &&
        activeSessionIdRef.current &&
        wsRef.current.connected
      ) {
        setUiError(null);
        setRunning(true);
        setCurrentAction(null);
        wsRef.current.send({
          session_id: activeSessionIdRef.current,
          type: "command",
          goal,
        });
        return;
      }

      if (connectTimeoutRef.current) {
        clearTimeout(connectTimeoutRef.current);
        connectTimeoutRef.current = null;
      }

      wsRef.current?.disconnect();
      wsRef.current = null;
      activeSessionIdRef.current = null;
      setMessages([]);
      setCurrentAction(null);
      setPilotFrame(null);
      setUiError(null);

      const res = await fetch(`${BACKEND_HTTP}/session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal }),
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(`Session request failed (${res.status}): ${errorText}`);
      }

      const { session_id } = await res.json() as { session_id: string };
      setSessionId(session_id);
      activeSessionIdRef.current = session_id;

      const ws = new ScreenPilotWebSocket(session_id);
      wsRef.current = ws;
      setWsClient(ws);

      ws.onStatus((isConnected) => {
        setConnected(isConnected);
        if (isConnected) {
          if (connectTimeoutRef.current) {
            clearTimeout(connectTimeoutRef.current);
            connectTimeoutRef.current = null;
          }
          setUiError(null);
          return;
        }

        if (running) {
          setUiError("Connection to backend was lost. Click Run Agent to retry.");
          setRunning(false);
        }
      });

      ws.onMessage((msg) => {
        if (msg.session_id !== activeSessionIdRef.current) {
          return;
        }

        setMessages((prev) => [...prev, msg]);

        // Backend forwards Playwright screenshot for display
        if (msg.type === "screenshot" && msg.image_b64) {
          setPilotFrame(msg.image_b64);
          return;
        }

        if (msg.type === "action" && msg.action) {
          setCurrentAction(msg.action);

          if (msg.action.type === "screenshot") {
            // Legacy: backend requesting a client screenshot (no-op now; Playwright handles this)
          } else if (
            msg.action.type === "done" ||
            msg.action.type === "ask_user"
          ) {
            setRunning(false);
          }
          // No need to send action_result — Playwright handles execution server-side
        }

        if (msg.type === "error") {
          setUiError(msg.error ?? "Agent returned an error.");
          setRunning(false);
        }

        if (
          msg.type === "status" &&
          msg.status &&
          msg.status.includes("Reached maximum steps")
        ) {
          setRunning(false);
        }
      });

      ws.connect();
      setRunning(true);
      connectTimeoutRef.current = setTimeout(() => {
        if (!ws.connected) {
          setUiError("Could not connect to backend websocket. Please retry.");
          setRunning(false);
        }
      }, 10000);
    } catch (err) {
      console.error("Failed to start session:", err);
      setUiError(
        err instanceof Error
          ? err.message
          : "Failed to start session. Please retry."
      );
      setRunning(false);
    }
  }, [running]);

  // ---------------------------------------------------------------------------
  // Screen capture callbacks
  // ---------------------------------------------------------------------------
  const handleFrame = useCallback(
    (b64: string, w: number, h: number) => {
      setPendingFrame({ b64, w, h });
      setScreenDims({ w, h });
    },
    [],
  );

  const handleCaptureStart = useCallback(() => setCapturing(true), []);
  const handleCaptureStop = useCallback(() => {
    setCapturing(false);
    setRunning(false);
  }, []);

  const handleStop = useCallback(() => {
    if (connectTimeoutRef.current) {
      clearTimeout(connectTimeoutRef.current);
      connectTimeoutRef.current = null;
    }
    wsRef.current?.disconnect();
    wsRef.current = null;
    activeSessionIdRef.current = null;
    setRunning(false);
    setConnected(false);
    setSessionId(null);
    setCurrentAction(null);
  }, []);

  // ---------------------------------------------------------------------------
  // Cleanup
  // ---------------------------------------------------------------------------
  useEffect(() => {
    return () => {
      if (connectTimeoutRef.current) {
        clearTimeout(connectTimeoutRef.current);
      }
      wsRef.current?.disconnect();
    };
  }, []);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------
  return (
    <main className="min-h-screen p-4 md:p-8">
      {/* Header */}
      <header className="flex items-center gap-3 mb-8">
        <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-brand-500/20 border border-brand-500/30">
          <Zap size={20} className="text-brand-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-white tracking-tight">ScreenPilot</h1>
          <p className="text-xs text-white/40">AI UI Navigator · Gemini 2.0 Flash</p>
        </div>
        {/* Connection indicator */}
        <div className="ml-auto flex items-center gap-2 text-xs">
          <span
            className={`w-2 h-2 rounded-full ${
              connected ? "bg-green-400 animate-pulse" : "bg-white/20"
            }`}
          />
          <span className="text-white/40">
            {connected ? "Connected" : capturing ? "Ready" : "Offline"}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 max-w-7xl mx-auto">
        {/* Left column — Screen preview */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          {uiError && (
            <section className="bg-red-500/10 border border-red-500/30 rounded-2xl p-3 text-sm text-red-200">
              {uiError}
            </section>
          )}
          <section className="bg-white/3 border border-white/8 rounded-2xl p-4">
            <h2 className="text-sm font-medium text-white/60 mb-3">
              Browser View (Playwright)
            </h2>

            {/* Playwright-controlled browser screenshot */}
            {pilotFrame ? (
              <div className="relative rounded-xl overflow-hidden border border-white/10 bg-black">
                <img
                  src={`data:image/png;base64,${pilotFrame}`}
                  alt="Playwright browser"
                  className="w-full h-auto"
                />
                <ActionOverlay
                  action={currentAction}
                  screenWidth={screenDims.w}
                  screenHeight={screenDims.h}
                />
              </div>
            ) : (
              <div className="flex items-center justify-center h-48 rounded-xl border border-white/10 bg-black/30 text-white/30 text-sm">
                {running ? "Waiting for browser screenshot…" : "Enter a goal to start the agent"}
              </div>
            )}

            {/* Optional: user screen capture section */}
            <details className="mt-3">
              <summary className="text-xs text-white/30 cursor-pointer hover:text-white/50 select-none">
                Optional: Share your own screen with the agent
              </summary>
              <div className="mt-2">
                <ScreenCapture
                  onFrame={handleFrame}
                  onStop={handleCaptureStop}
                  onStart={handleCaptureStart}
                  active={capturing}
                />
                {pendingFrame && (
                  <div className="relative mt-3 rounded-xl overflow-hidden border border-white/10 bg-black">
                    <img
                      src={`data:image/jpeg;base64,${pendingFrame.b64}`}
                      alt="User screen capture"
                      className="w-full h-auto"
                    />
                  </div>
                )}
              </div>
            </details>
          </section>
        </div>

        {/* Right column — Controls + Log */}
        <div className="flex flex-col gap-4">
          {/* Command panel */}
          <section className="bg-white/3 border border-white/8 rounded-2xl p-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-medium text-white/60">Command</h2>
              <VoiceInput
                onTranscript={(text) => {
                  if (!running) startSession(text);
                }}
                disabled={running}
              />
            </div>
            <CommandPanel
              onSubmit={(goal) => startSession(goal)}
              onStop={handleStop}
              running={running}
              disabled={false}
            />
          </section>

          {/* Session log */}
          <section className="bg-white/3 border border-white/8 rounded-2xl p-4 flex-1">
            <h2 className="text-sm font-medium text-white/60 mb-3">
              Agent Activity
              {running && (
                <span className="ml-2 inline-flex items-center gap-1 text-brand-400">
                  <span className="w-1.5 h-1.5 rounded-full bg-brand-400 animate-ping" />
                  <span className="text-xs font-normal">Running</span>
                </span>
              )}
            </h2>
            <SessionLog messages={messages} />
          </section>

          {/* Current action card */}
          {currentAction && currentAction.type !== "screenshot" && (
            <div className="bg-brand-500/10 border border-brand-500/20 rounded-xl p-3">
              <p className="text-xs text-brand-300/70 mb-1 font-medium uppercase tracking-wider">
                Last Action
              </p>
              <p className="text-sm text-brand-200 font-mono">
                {currentAction.type}
                {currentAction.description && (
                  <span className="text-white/40 font-sans font-normal ml-2">
                    {currentAction.description}
                  </span>
                )}
              </p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
