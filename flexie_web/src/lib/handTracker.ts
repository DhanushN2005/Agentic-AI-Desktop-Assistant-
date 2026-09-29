import {
  FilesetResolver,
  HandLandmarker,
  type NormalizedLandmark,
} from "@mediapipe/tasks-vision";

const WASM_CDN =
  "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.35/wasm";
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

// Landmark indices
const WRIST = 0;
const THUMB_TIP = 4;
const INDEX_TIP = 8;
const MIDDLE_MCP = 9;

// Pinch hysteresis thresholds
const PINCH_ON = 0.32;
const PINCH_OFF = 0.45;

// Gesture detection thresholds
const SWIPE_THRESHOLD = 0.08;
const SWIPE_COOLDOWN_MS = 800;

export type GestureType =
  | "pinch_left"
  | "pinch_right"
  | "pinch_up"
  | "pinch_down"
  | "open_palm"
  | "fist"
  | "wave"
  | "point"
  | "none";

export interface GestureEvent {
  gesture: GestureType;
  confidence: number;
  timestamp: number;
}

export interface HandTrackerCallbacks {
  onGesture(gesture: GestureEvent): void;
  onStatus(status: string): void;
  onHandCount(count: number): void;
}

interface Point {
  x: number;
  y: number;
}

interface HandState {
  pinching: boolean;
  grab: Point;
  prevGrab: Point | null;
}

export class HandTracker {
  private video: HTMLVideoElement;
  private overlay: HTMLCanvasElement;
  private callbacks: HandTrackerCallbacks;
  private landmarker: HandLandmarker | null = null;
  private stream: MediaStream | null = null;
  private rafId = 0;
  private running = false;
  private lastVideoTime = -1;
  private lastGestureTime = 0;

  private handStates = new Map<string, HandState>();

  constructor(
    video: HTMLVideoElement,
    overlay: HTMLCanvasElement,
    callbacks: HandTrackerCallbacks
  ) {
    this.video = video;
    this.overlay = overlay;
    this.callbacks = callbacks;
  }

  async start(): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      video: { width: 640, height: 480, facingMode: "user" },
      audio: false,
    });
    this.video.srcObject = this.stream;
    await this.video.play();

    const fileset = await FilesetResolver.forVisionTasks(WASM_CDN);
    const options = {
      baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" as const },
      runningMode: "VIDEO" as const,
      numHands: 2,
      minHandDetectionConfidence: 0.6,
      minHandPresenceConfidence: 0.6,
      minTrackingConfidence: 0.6,
    };

    try {
      this.landmarker = await HandLandmarker.createFromOptions(fileset, options);
    } catch {
      this.landmarker = await HandLandmarker.createFromOptions(fileset, {
        ...options,
        baseOptions: { ...options.baseOptions, delegate: "CPU" as const },
      });
    }

    this.running = true;
    this.callbacks.onStatus("Hand tracking active");
    this.loop();
  }

  stop(): void {
    this.running = false;
    cancelAnimationFrame(this.rafId);
    this.landmarker?.close();
    this.landmarker = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.handStates.clear();
    const ctx = this.overlay.getContext("2d");
    ctx?.clearRect(0, 0, this.overlay.width, this.overlay.height);
    this.callbacks.onStatus("Hand tracking off");
    this.callbacks.onHandCount(0);
  }

  private loop = () => {
    if (!this.running) return;
    this.rafId = requestAnimationFrame(this.loop);

    if (!this.landmarker || this.video.readyState < 2) return;
    if (this.video.currentTime === this.lastVideoTime) return;
    this.lastVideoTime = this.video.currentTime;

    const result = this.landmarker.detectForVideo(this.video, performance.now());
    this.processHands(
      result.landmarks,
      result.handedness.map((h) => h[0]?.categoryName ?? "?")
    );
    this.drawOverlay(result.landmarks);
  };

  private processHands(
    landmarks: NormalizedLandmark[][],
    labels: string[]
  ): void {
    this.callbacks.onHandCount(landmarks.length);

    if (landmarks.length === 0) {
      this.handStates.clear();
      return;
    }

    const now = performance.now();
    const seen = new Set<string>();

    // Process each hand
    const pinchPositions: Point[] = [];
    let openPalmCount = 0;
    let fistCount = 0;
    let pointingCount = 0;

    landmarks.forEach((lm, i) => {
      const label = labels[i];
      seen.add(label);

      const handScale = dist2d(lm[WRIST], lm[MIDDLE_MCP]);
      if (handScale < 1e-6) return;

      // Calculate pinch state
      const pinchRatio = dist2d(lm[THUMB_TIP], lm[INDEX_TIP]) / handScale;
      const raw: Point = {
        x: 1 - (lm[THUMB_TIP].x + lm[INDEX_TIP].x) / 2,
        y: (lm[THUMB_TIP].y + lm[INDEX_TIP].y) / 2,
      };

      let state = this.handStates.get(label);
      if (!state) {
        state = { pinching: false, grab: raw, prevGrab: null };
        this.handStates.set(label, state);
      }

      // Hysteresis for pinch detection
      if (state.pinching && pinchRatio > PINCH_OFF) state.pinching = false;
      else if (!state.pinching && pinchRatio < PINCH_ON) state.pinching = true;

      state.grab = {
        x: state.grab.x + (raw.x - state.grab.x) * 0.4,
        y: state.grab.y + (raw.y - state.grab.y) * 0.4,
      };

      if (state.pinching) {
        pinchPositions.push(state.grab);
      }

      // Detect hand pose: open palm vs fist vs pointing
      const fingerTips = [8, 12, 16, 20]; // index, middle, ring, pinky tips
      const fingerPips = [6, 10, 14, 18]; // PIP joints

      let extendedFingers = 0;
      fingerTips.forEach((tip, idx) => {
        const pip = fingerPips[idx];
        if (lm[tip].y < lm[pip].y) extendedFingers++;
      });

      // Thumb extended check
      const isRightHand = labels[i] === "Right";
      const thumbExtended = isRightHand
        ? lm[THUMB_TIP].x > lm[WRIST].x
        : lm[THUMB_TIP].x < lm[WRIST].x;
      if (thumbExtended) {
        extendedFingers++;
      }

      if (extendedFingers >= 4) openPalmCount++;
      else if (extendedFingers <= 1) fistCount++;

      // Pointing: only index finger extended
      if (
        lm[8].y < lm[6].y &&
        lm[12].y > lm[10].y &&
        lm[16].y > lm[14].y &&
        lm[20].y > lm[18].y
      ) {
        pointingCount++;
      }

      state.prevGrab = { ...state.grab };
    });

    // Drop state for hands that left
    for (const key of this.handStates.keys()) {
      if (!seen.has(key)) this.handStates.delete(key);
    }

    // Detect gestures (with cooldown)
    if (now - this.lastGestureTime < SWIPE_COOLDOWN_MS) return;

    // Priority: wave > pinch gestures > open palm > fist > pointing
    if (landmarks.length >= 2 && this.isWaving(landmarks)) {
      this.emitGesture({ gesture: "wave", confidence: 0.9, timestamp: now });
    } else if (pinchPositions.length === 1) {
      const gesture = this.detectPinchDirection(pinchPositions[0]);
      if (gesture) {
        this.emitGesture({ gesture, confidence: 0.85, timestamp: now });
      }
    } else if (openPalmCount > 0) {
      this.emitGesture({ gesture: "open_palm", confidence: 0.8, timestamp: now });
    } else if (fistCount > 0) {
      this.emitGesture({ gesture: "fist", confidence: 0.8, timestamp: now });
    } else if (pointingCount > 0) {
      this.emitGesture({ gesture: "point", confidence: 0.8, timestamp: now });
    }
  }

  private detectPinchDirection(grab: Point): GestureType | null {
    // Get current state to check prev position
    for (const state of this.handStates.values()) {
      if (state.prevGrab) {
        const dx = grab.x - state.prevGrab.x;
        const dy = grab.y - state.prevGrab.y;

        if (Math.abs(dx) > SWIPE_THRESHOLD) {
          return dx > 0 ? "pinch_right" : "pinch_left";
        }
        if (Math.abs(dy) > SWIPE_THRESHOLD) {
          return dy > 0 ? "pinch_down" : "pinch_up";
        }
      }
    }
    return null;
  }

  private isWaving(landmarks: NormalizedLandmark[][]): boolean {
    // Simple wave detection: both hands visible, open palms, moving horizontally
    if (landmarks.length < 2) return false;

    const avgX =
      landmarks.reduce((sum, lm) => {
        const palmX = (lm[0].x + lm[5].x + lm[17].x) / 3;
        return sum + palmX;
      }, 0) / landmarks.length;

    // Check if hands are roughly at same height (wave-like motion)
    const yPositions = landmarks.map(
      (lm) => (lm[0].y + lm[5].y + lm[17].y) / 3
    );
    const yDiff = Math.abs(yPositions[0] - yPositions[1]);

    return yDiff < 0.15 && avgX > 0.3 && avgX < 0.7;
  }

  private emitGesture(gesture: GestureEvent): void {
    this.lastGestureTime = gesture.timestamp;
    this.callbacks.onGesture(gesture);
  }

  private drawOverlay(landmarks: NormalizedLandmark[][]): void {
    const ctx = this.overlay.getContext("2d");
    if (!ctx) return;
    const { width, height } = this.overlay;
    ctx.clearRect(0, 0, width, height);

    for (const lm of landmarks) {
      const thumb = lm[THUMB_TIP];
      const index = lm[INDEX_TIP];
      const tx = (1 - thumb.x) * width;
      const ty = thumb.y * height;
      const ix = (1 - index.x) * width;
      const iy = index.y * height;

      const handScale = dist2d(lm[WRIST], lm[MIDDLE_MCP]);
      const pinched =
        handScale > 1e-6 && dist2d(thumb, index) / handScale < PINCH_ON;

      ctx.strokeStyle = pinched ? "#00ff88" : "rgba(0,210,255,0.5)";
      ctx.lineWidth = pinched ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(tx, ty);
      ctx.lineTo(ix, iy);
      ctx.stroke();

      ctx.fillStyle = pinched ? "#00ff88" : "rgba(0,210,255,0.7)";
      for (const [x, y] of [
        [tx, ty],
        [ix, iy],
      ]) {
        ctx.beginPath();
        ctx.arc(x, y, pinched ? 5 : 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }
}

function dist2d(a: NormalizedLandmark, b: NormalizedLandmark): number {
  return Math.hypot(a.x - b.x, a.y - b.y);
}
