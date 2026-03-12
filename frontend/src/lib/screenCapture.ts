/**
 * Screen capture utilities.
 *
 * Uses the browser's `getDisplayMedia()` API to capture the user's screen
 * (or a specific window/tab), draws frames to a hidden <canvas>, and exports
 * them as base64-encoded JPEG images for sending to the backend.
 */

export interface ScreenDimensions {
  width: number;
  height: number;
}

export class ScreenCapture {
  private stream: MediaStream | null = null;
  private video: HTMLVideoElement | null = null;
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private captureQuality = 0.7;   // JPEG quality [0–1]
  private maxDimension = 1280;    // downscale if larger (saves tokens)

  /** Request screen share permission and start the capture stream. */
  async start(): Promise<ScreenDimensions> {
    this.stream = await navigator.mediaDevices.getDisplayMedia({
      video: {
        frameRate: { ideal: 5, max: 10 },
        width: { ideal: this.maxDimension },
      },
      audio: false,
    });

    // Create hidden video element to receive frames
    this.video = document.createElement("video");
    this.video.srcObject = this.stream;
    this.video.muted = true;
    await this.video.play();

    // Create canvas for frame extraction
    this.canvas = document.createElement("canvas");
    this.canvas.width = this.video.videoWidth;
    this.canvas.height = this.video.videoHeight;
    this.ctx = this.canvas.getContext("2d")!;

    return { width: this.canvas.width, height: this.canvas.height };
  }

  /** Capture a single frame and return as base64 JPEG. */
  captureFrame(): string | null {
    if (!this.video || !this.canvas || !this.ctx) return null;
    if (this.video.readyState < 2) return null;  // not ready

    // Scale down if oversized
    let { videoWidth: w, videoHeight: h } = this.video;
    if (w > this.maxDimension) {
      h = Math.round((h * this.maxDimension) / w);
      w = this.maxDimension;
    }
    this.canvas.width = w;
    this.canvas.height = h;
    this.ctx.drawImage(this.video, 0, 0, w, h);

    const dataUrl = this.canvas.toDataURL("image/jpeg", this.captureQuality);
    // Strip "data:image/jpeg;base64," prefix
    return dataUrl.split(",")[1] ?? null;
  }

  /** Get the current stream dimensions. */
  get dimensions(): ScreenDimensions {
    return {
      width: this.canvas?.width ?? 0,
      height: this.canvas?.height ?? 0,
    };
  }

  /** Whether a capture stream is active. */
  get active(): boolean {
    return this.stream !== null && this.stream.active;
  }

  /** Stop all tracks and clean up. */
  stop(): void {
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video = null;
  }

  /** Subscribe to stream-ended events (e.g. user clicks "Stop sharing"). */
  onEnded(callback: () => void): void {
    this.stream?.getVideoTracks().forEach((t) => {
      t.addEventListener("ended", callback);
    });
  }
}
