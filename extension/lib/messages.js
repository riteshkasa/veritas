// Cross-context message type constants.
export const MSG = {
  // content -> background
  START: "niwas/start",
  STOP: "niwas/stop",
  CC_CUE: "niwas/cc-cue",
  AUDIO_REQUEST: "niwas/audio-request",
  // background -> content
  VERDICT: "niwas/verdict",
  STATUS: "niwas/status",
  TRANSCRIPT: "niwas/transcript",
  // background <-> offscreen
  OFFSCREEN_START: "niwas/offscreen-start",
  OFFSCREEN_STOP: "niwas/offscreen-stop",
};
