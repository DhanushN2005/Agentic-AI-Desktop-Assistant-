import { useState, useEffect, useRef, useCallback } from "react";
import { HandTracker, type GestureType, type GestureEvent } from "./handTracker";
import { GestureMapper, type GestureCommand } from "./gestureMapper";

interface UseGestureControlOptions {
  wsRef: React.MutableRefObject<WebSocket | null>;
  // enabled?: boolean; // reserved for future
  cooldownMs?: number;
  customMappings?: GestureCommand[];
}

interface GestureControlState {
  isActive: boolean;
  handCount: number;
  lastGesture: GestureType | null;
  status: string;
  error: string | null;
}

export function useGestureControl({
  wsRef,
  cooldownMs = 1500,
  customMappings,
}: UseGestureControlOptions) {
  const [state, setState] = useState<GestureControlState>({
    isActive: false,
    handCount: 0,
    lastGesture: null,
    status: "Off",
    error: null,
  });

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement | null>(null);
  const trackerRef = useRef<HandTracker | null>(null);
  const mapperRef = useRef<GestureMapper>(new GestureMapper(customMappings));

  // Update cooldown if provided
  useEffect(() => {
    mapperRef.current.setCooldown(cooldownMs);
  }, [cooldownMs]);

  // Update custom mappings if provided
  useEffect(() => {
    if (customMappings) {
      customMappings.forEach((m) => {
        mapperRef.current.updateMapping(m.gesture, m.command);
      });
    }
  }, [customMappings]);

  const sendCommand = useCallback(
    (command: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(command);
        setState((prev) => ({
          ...prev,
          status: `Sent: ${command}`,
        }));
      }
    },
    [wsRef]
  );

  const handleGesture = useCallback(
    (event: GestureEvent) => {
      const command = mapperRef.current.getCommand(event.gesture);
      if (command) {
        sendCommand(command);
        setState((prev) => ({
          ...prev,
          lastGesture: event.gesture,
          status: `Gesture: ${event.gesture} → ${command}`,
        }));
      }
    },
    [sendCommand]
  );

  const start = useCallback(async () => {
    if (trackerRef.current) return;

    // Create hidden video/overlay elements if not provided
    if (!videoRef.current) {
      const video = document.createElement("video");
      video.style.display = "none";
      video.setAttribute("playsinline", "");
      video.setAttribute("muted", "");
      document.body.appendChild(video);
      videoRef.current = video;
    }

    if (!overlayRef.current) {
      const canvas = document.createElement("canvas");
      canvas.width = 208;
      canvas.height = 156;
      canvas.style.position = "fixed";
      canvas.style.bottom = "10px";
      canvas.style.right = "10px";
      canvas.style.width = "160px";
      canvas.style.height = "120px";
      canvas.style.borderRadius = "8px";
      canvas.style.border = "1px solid rgba(0,255,136,0.3)";
      canvas.style.zIndex = "9999";
      canvas.style.opacity = "0.8";
      document.body.appendChild(canvas);
      overlayRef.current = canvas;
    }

    const tracker = new HandTracker(videoRef.current, overlayRef.current, {
      onGesture: handleGesture,
      onStatus: (status) => setState((prev) => ({ ...prev, status })),
      onHandCount: (count) => setState((prev) => ({ ...prev, handCount: count })),
    });

    trackerRef.current = tracker;

    try {
      await tracker.start();
      setState((prev) => ({
        ...prev,
        isActive: true,
        status: "Active - Show hands",
        error: null,
      }));
    } catch (err) {
      const errorMsg =
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Camera access denied"
          : "Failed to start tracking";
      setState((prev) => ({
        ...prev,
        error: errorMsg,
        status: "Error",
      }));
      trackerRef.current = null;
    }
  }, [handleGesture]);

  const stop = useCallback(() => {
    trackerRef.current?.stop();
    trackerRef.current = null;

    // Clean up overlay
    if (overlayRef.current) {
      overlayRef.current.remove();
      overlayRef.current = null;
    }

    setState({
      isActive: false,
      handCount: 0,
      lastGesture: null,
      status: "Off",
      error: null,
    });
  }, []);

  const toggle = useCallback(() => {
    if (state.isActive) {
      stop();
    } else {
      start();
    }
  }, [state.isActive, start, stop]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      trackerRef.current?.stop();
      videoRef.current?.remove();
      overlayRef.current?.remove();
    };
  }, []);

  return {
    ...state,
    start,
    stop,
    toggle,
    updateGestureMapping: (gesture: GestureType, command: string) =>
      mapperRef.current.updateMapping(gesture, command),
    getMappings: () => mapperRef.current.getMappings(),
    resetMappings: () => mapperRef.current.resetToDefaults(),
  };
}
