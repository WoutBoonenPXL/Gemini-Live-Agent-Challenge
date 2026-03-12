"use client";

import { useEffect, useRef } from "react";
import type { AgentAction } from "@/lib/websocket";

interface Props {
  action: AgentAction | null;
  screenWidth: number;
  screenHeight: number;
}

/**
 * Transparent overlay rendered on top of the screen preview.
 * Shows a ripple indicator where the agent clicked, and a bounding box
 * for text-input actions.
 */
export function ActionOverlay({ action, screenWidth, screenHeight }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    if (!action || !canvasRef.current) return;
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const w = canvas.width;
    const h = canvas.height;

    const drawClick = (x: number, y: number, color: string) => {
      const px = x * w;
      const py = y * h;
      // Outer ring
      ctx.beginPath();
      ctx.arc(px, py, 20, 0, Math.PI * 2);
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();
      // Inner dot
      ctx.beginPath();
      ctx.arc(px, py, 5, 0, Math.PI * 2);
      ctx.fillStyle = color;
      ctx.fill();
      // Crosshair lines
      ctx.strokeStyle = color;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(px - 28, py);
      ctx.lineTo(px + 28, py);
      ctx.moveTo(px, py - 28);
      ctx.lineTo(px, py + 28);
      ctx.stroke();
    };

    if (
      action.type === "click" ||
      action.type === "double_click" ||
      action.type === "hover"
    ) {
      drawClick(action.x ?? 0, action.y ?? 0, "rgba(14,165,233,0.9)");
    } else if (action.type === "right_click") {
      drawClick(action.x ?? 0, action.y ?? 0, "rgba(168,85,247,0.9)");
    } else if (action.type === "clear_and_type") {
      drawClick(action.x ?? 0, action.y ?? 0, "rgba(34,197,94,0.9)");
      // Text box
      const px = (action.x ?? 0) * w;
      const py = (action.y ?? 0) * h;
      ctx.strokeStyle = "rgba(34,197,94,0.6)";
      ctx.lineWidth = 1.5;
      ctx.strokeRect(px - 60, py - 14, 120, 28);
    } else if (action.type === "scroll") {
      const px = (action.x ?? 0) * w;
      const py = (action.y ?? 0) * h;
      const down = (action.delta_y ?? 0) > 0;
      ctx.beginPath();
      ctx.arc(px, py, 18, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(251,191,36,0.8)";
      ctx.lineWidth = 2;
      ctx.stroke();
      // Arrow
      ctx.beginPath();
      ctx.moveTo(px, down ? py - 10 : py + 10);
      ctx.lineTo(px, down ? py + 10 : py - 10);
      ctx.lineTo(px - 6, down ? py + 4 : py - 4);
      ctx.moveTo(px, down ? py + 10 : py - 10);
      ctx.lineTo(px + 6, down ? py + 4 : py - 4);
      ctx.strokeStyle = "rgba(251,191,36,0.8)";
      ctx.lineWidth = 2;
      ctx.stroke();
    }

    // Fade out after 1.2s
    const handle = setTimeout(() => {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }, 1200);

    return () => clearTimeout(handle);
  }, [action]);

  return (
    <canvas
      ref={canvasRef}
      width={screenWidth || 1280}
      height={screenHeight || 720}
      className="absolute inset-0 w-full h-full pointer-events-none"
      style={{ zIndex: 10 }}
    />
  );
}
