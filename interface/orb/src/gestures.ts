// Separate bundle: MediaPipe hand tracking. Loaded on demand by entry.ts (only when gestures are switched on).
import { HandTracker } from "./handTracker";

(window as unknown as { FlexieOrbGestures: { HandTracker: typeof HandTracker } }).FlexieOrbGestures = { HandTracker };
