/**
 * Typed WebSocket client for ScreenPilot backend.
 * Handles reconnection, message queuing, and typed message parsing.
 */

export type ActionType =
  | "click" | "right_click" | "double_click" | "hover"
  | "type" | "clear_and_type" | "key_press"
  | "scroll" | "navigate" | "wait" | "screenshot"
  | "done" | "ask_user";

export interface AgentAction {
  type: ActionType;
  // click / hover
  x?: number;
  y?: number;
  // type / clear_and_type
  text?: string;
  // key_press
  key?: string;
  modifiers?: string[];
  // scroll
  delta_x?: number;
  delta_y?: number;
  // navigate
  url?: string;
  // wait
  ms?: number;
  // done
  summary?: string;
  // ask_user
  question?: string;
  description?: string;
}

export interface ServerMessage {
  session_id: string;
  type: "action" | "thinking" | "error" | "status" | "screenshot";
  action?: AgentAction;
  thinking?: string;
  error?: string;
  status?: string;
  image_b64?: string;   // Playwright screenshot forwarded from backend
}

export interface ClientMessage {
  session_id: string;
  type: "command" | "screenshot" | "voice_chunk" | "action_result";
  goal?: string;
  image_b64?: string;
  screen_width?: number;
  screen_height?: number;
  audio_b64?: string;
  action_success?: boolean;
  action_error?: string;
}

type MessageHandler = (msg: ServerMessage) => void;
type StatusHandler = (connected: boolean) => void;

export class ScreenPilotWebSocket {
  private ws: WebSocket | null = null;
  private sessionId: string;
  private url: string;
  private messageHandlers: MessageHandler[] = [];
  private statusHandlers: StatusHandler[] = [];
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelay = 2000;
  private shouldReconnect = true;

  constructor(sessionId: string) {
    this.sessionId = sessionId;
    const base =
      process.env.NEXT_PUBLIC_BACKEND_WS_URL ?? "ws://localhost:8000/ws";
    this.url = `${base}/${sessionId}`;
  }

  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) return;
    this.ws = new WebSocket(this.url);

    this.ws.onopen = () => {
      console.info("[WS] Connected to", this.url);
      this.reconnectDelay = 2000;
      this.statusHandlers.forEach((h) => h(true));
    };

    this.ws.onmessage = (ev: MessageEvent) => {
      try {
        const msg: ServerMessage = JSON.parse(ev.data as string);
        this.messageHandlers.forEach((h) => h(msg));
      } catch {
        console.warn("[WS] Failed to parse message", ev.data);
      }
    };

    this.ws.onerror = (err) => {
      console.warn("[WS] Error", err);
    };

    this.ws.onclose = () => {
      this.statusHandlers.forEach((h) => h(false));
      if (this.shouldReconnect) {
        this.reconnectTimer = setTimeout(() => {
          console.info("[WS] Reconnecting…");
          this.connect();
        }, this.reconnectDelay);
        this.reconnectDelay = Math.min(this.reconnectDelay * 1.5, 15000);
      }
    };
  }

  disconnect(): void {
    this.shouldReconnect = false;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.ws?.close();
  }

  send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg));
    } else {
      console.warn("[WS] Cannot send — not connected");
    }
  }

  onMessage(handler: MessageHandler): () => void {
    this.messageHandlers.push(handler);
    return () => {
      this.messageHandlers = this.messageHandlers.filter((h) => h !== handler);
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.push(handler);
    return () => {
      this.statusHandlers = this.statusHandlers.filter((h) => h !== handler);
    };
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }
}
