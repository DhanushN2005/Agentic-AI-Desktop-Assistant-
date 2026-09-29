import { type GestureType } from "./handTracker";

export interface GestureCommand {
  gesture: GestureType;
  command: string;
  description: string;
}

// Default gesture mapping - can be customized by user
export const DEFAULT_GESTURE_MAP: GestureCommand[] = [
  // Swipe gestures for navigation
  { gesture: "pinch_left", command: "open chrome", description: "Open browser" },
  { gesture: "pinch_right", command: "open notepad", description: "Open notepad" },
  { gesture: "pinch_up", command: "what is the time", description: "Check time" },
  { gesture: "pinch_down", command: "what is the weather", description: "Check weather" },

  // Web-related gestures
  { gesture: "open_palm", command: "hello", description: "Greet Flexie" },
  { gesture: "fist", command: "stop", description: "Stop current task" },
  { gesture: "wave", command: "daily briefing", description: "Morning briefing" },
  { gesture: "point", command: "analyze screen", description: "Analyze screen" },

  // Additional web commands
  { gesture: "pinch_left", command: "open chrome", description: "Open browser" },
  { gesture: "open_palm", command: "open web", description: "Open web interface" },
];

export class GestureMapper {
  private gestureMap: GestureCommand[];
  private enabled = true;
  private lastExecuted = new Map<string, number>();
  private cooldownMs = 1500; // 1.5s cooldown per command

  constructor(customMap?: GestureCommand[]) {
    this.gestureMap = customMap || DEFAULT_GESTURE_MAP;
  }

  setEnabled(enabled: boolean): void {
    this.enabled = enabled;
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  setCooldown(ms: number): void {
    this.cooldownMs = ms;
  }

  // Update a specific gesture mapping
  updateMapping(gesture: GestureType, command: string): void {
    const existing = this.gestureMap.find((m) => m.gesture === gesture);
    if (existing) {
      existing.command = command;
    } else {
      this.gestureMap.push({
        gesture,
        command,
        description: `Custom: ${command}`,
      });
    }
  }

  // Get command for a gesture
  getCommand(gesture: GestureType): string | null {
    if (!this.enabled) return null;

    const mapping = this.gestureMap.find((m) => m.gesture === gesture);
    if (!mapping) return null;

    // Check cooldown
    const now = Date.now();
    const lastTime = this.lastExecuted.get(gesture) || 0;
    if (now - lastTime < this.cooldownMs) {
      return null; // Still in cooldown
    }

    this.lastExecuted.set(gesture, now);
    return mapping.command;
  }

  // Get all current mappings
  getMappings(): GestureCommand[] {
    return [...this.gestureMap];
  }

  // Reset to defaults
  resetToDefaults(): void {
    this.gestureMap = [...DEFAULT_GESTURE_MAP];
    this.lastExecuted.clear();
  }
}
