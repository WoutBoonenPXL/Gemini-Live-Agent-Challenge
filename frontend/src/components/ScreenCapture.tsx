"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { Monitor, MonitorOff } from "lucide-react";
import { ScreenCapture as ScreenCaptureLib } from "@/lib/screenCapture";

interface Props {
  onFrame: (imageB64: string, width: number, height: number) => void;
  onStop: () => void;
  active: boolean;
  onStart: () => void;
}

export function ScreenCapture({ onFrame, onStop, active, onStart }: Props) {
  const captureRef = useRef<ScreenCaptureLib | null>(null);
  const frameIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const previewRef = useRef<HTMLCanvasElement>(null);
  const [capturing, setCapturing] = useState(false);

  const startCapture = useCallback(async () => {
    try {
      const lib = new ScreenCaptureLib();
      captureRef.current = lib;
      const dims = await lib.start();

      lib.onEnded(() => {
        stopCapture();
      });

      setCapturing(true);
      onStart();

      // Send frames every 500ms (agent requests on-demand too)
      frameIntervalRef.current = setInterval(() => {
        const frame = lib.captureFrame();
        if (frame) {
          onFrame(frame, dims.width, dims.height);
          // Draw preview
          if (previewRef.current) {
            const canvas = previewRef.current;
            const ctx = canvas.getContext("2d");
            if (ctx) {
              const img = new Image();
              img.onload = () => {
                canvas.width = img.width;
                canvas.height = img.height;
                ctx.drawImage(img, 0, 0);
              };
              img.src = `data:image/jpeg;base64,${frame}`;
            }
          }
        }
      }, 500);
    } catch (err) {
      console.error("Screen capture failed:", err);
    }
  }, [onFrame, onStart]);

  const stopCapture = useCallback(() => {
    if (frameIntervalRef.current) {
      clearInterval(frameIntervalRef.current);
      frameIntervalRef.current = null;
    }
    captureRef.current?.stop();
    captureRef.current = null;
    setCapturing(false);
    onStop();
  }, [onStop]);

  useEffect(() => {
    if (!active && capturing) stopCapture();
  }, [active, capturing, stopCapture]);

  useEffect(() => () => stopCapture(), [stopCapture]);

  return (
    <div className="flex flex-col gap-3">
      <button
        onClick={capturing ? stopCapture : startCapture}
        className={`flex items-center gap-2 px-4 py-2.5 rounded-lg font-medium transition-all ${
          capturing
            ? "bg-red-500/20 border border-red-500/40 text-red-300 hover:bg-red-500/30"
            : "bg-brand-500/20 border border-brand-500/40 text-brand-300 hover:bg-brand-500/30"
        }`}
      >
        {capturing ? (
          <>
            <MonitorOff size={16} className="animate-pulse" />
            Stop Sharing
          </>
        ) : (
          <>
            <Monitor size={16} />
            Share Screen
          </>
        )}
      </button>

      {capturing && (
        <div className="relative rounded-lg overflow-hidden border border-white/10 bg-black/30">
          <canvas
            ref={previewRef}
            className="w-full h-auto max-h-40 object-contain"
          />
          <div className="absolute top-2 right-2 flex items-center gap-1.5 bg-black/60 rounded px-2 py-1 text-xs text-green-400">
            <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Live
          </div>
        </div>
      )}
    </div>
  );
}
