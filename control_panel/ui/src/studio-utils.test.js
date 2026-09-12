import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactUrl,
  dependentNodeIds,
  formatBytes,
  label,
  previewCaptionLines,
  previewCuesFromWords,
  previewFramesFromTimeline,
  statusClass,
  subtitleMarginPx,
  SUBTITLE_FONT_SUPPORTS_PERSIAN,
  SUBTITLE_POSITION_OFFSETS,
  validateLaunchValues,
} from "./studio-utils.js";

test("dependentNodeIds finds all downstream consumers without looping", () => {
  const dependents = dependentNodeIds(
    [
      { source: "script", target: "plan" },
      { source: "plan", target: "render" },
      { source: "script", target: "voice" },
      { source: "render", target: "script" },
    ],
    "script",
  );
  assert.deepEqual([...dependents].sort(), ["plan", "render", "voice"]);
});

test("status values map to stable visual classes", () => {
  assert.equal(statusClass("DONE"), "done");
  assert.equal(statusClass("REUSED"), "reused");
  assert.equal(statusClass("FAILED_VALIDATION"), "failed");
  assert.equal(statusClass("WAITING_FOR_FLOW"), "waiting");
  assert.equal(statusClass("PENDING"), "pending");
});

test("artifact URLs preserve hierarchy and escape unsafe path characters", () => {
  assert.equal(
    artifactUrl("/api/run/id/artifact", "music/a track #1.mp3", 42),
    "/api/run/id/artifact/music/a%20track%20%231.mp3?v=42",
  );
});

test("small presentation helpers remain predictable", () => {
  assert.equal(label("flow_clip_a"), "flow clip a");
  assert.equal(formatBytes(1536), "2 KB");
  assert.equal(formatBytes(2 * 1024 * 1024), "2.0 MB");
});

test("launch validation catches cross-field constraints", () => {
  const valid = {
    min_duration_seconds: 40,
    max_duration_seconds: 60,
    telegram_low_size: true,
    telegram_original: false,
    music_providers: ["freesound"],
    motion_enabled: true,
    motion_allow_hold: true,
  };
  assert.doesNotThrow(() => validateLaunchValues(valid));
  assert.throws(
    () => validateLaunchValues({ ...valid, min_duration_seconds: 80 }),
    /Minimum duration/,
  );
  assert.throws(
    () =>
      validateLaunchValues({
        ...valid,
        telegram_low_size: false,
        telegram_original: false,
      }),
    /Telegram/,
  );
  assert.throws(
    () => validateLaunchValues({ ...valid, music_providers: [] }),
    /music provider/,
  );
  assert.throws(
    () => validateLaunchValues({ ...valid, motion_allow_hold: false }),
    /motion primitive/,
  );
  assert.throws(
    () => validateLaunchValues({ ...valid, character_mode: "manual", character_id: "" }),
    /manual character/,
  );
});

test("subtitle preview wraps the first caption like the ASS writer", () => {
  assert.deepEqual(
    previewCaptionLines("This a subtitle preview for test, thank you for attention", 6),
    ["This a subtitle preview for test,"],
  );
  assert.deepEqual(previewCaptionLines("one two three four five", 3), [
    "one two three",
  ]);
  const long = previewCaptionLines(
    "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu",
    12,
  );
  assert.ok(long.length <= 2);
  assert.equal(long.join(" ").split(" ").length, 12);
  assert.deepEqual(Object.keys(SUBTITLE_POSITION_OFFSETS).sort(), [
    "high",
    "low",
    "standard",
  ]);
});

test("subtitle revision preview re-chunks measured words before render", () => {
  const cues = previewCuesFromWords([
    { text: "One", start: 0, end: 0.2 },
    { text: "two", start: 0.2, end: 0.4 },
    { text: "three", start: 0.4, end: 0.6 },
    { text: "four.", start: 0.6, end: 0.8 },
    { text: "Five", start: 1, end: 1.2 },
  ], 2);
  assert.deepEqual(cues.map((cue) => cue.text), ["One two", "three four.", "Five"]);
  assert.deepEqual(cues[1].lines, ["three four."]);
  assert.equal(cues[1].start, 0.4);
  assert.equal(cues[1].end, 0.8);
});

test("subtitle custom offsets mirror the ASS margin math", () => {
  assert.equal(subtitleMarginPx("standard", 0, "percent"), 144);
  assert.equal(subtitleMarginPx("low", 0, "percent"), 86);
  assert.equal(subtitleMarginPx("custom", 10, "percent"), 192);
  assert.equal(subtitleMarginPx("custom", 200, "px"), 200);
  assert.equal(subtitleMarginPx("custom", 99, "percent"), 768);
  assert.equal(subtitleMarginPx("custom", -5, "percent"), 0);
});

test("subtitle font coverage makes Persian fallback explicit", () => {
  assert.equal(SUBTITLE_FONT_SUPPORTS_PERSIAN.has("Rubik"), true);
  assert.equal(SUBTITLE_FONT_SUPPORTS_PERSIAN.has("DejaVu Sans"), true);
  assert.equal(SUBTITLE_FONT_SUPPORTS_PERSIAN.has("Oswald"), false);
});

test("revision branding preview samples ten frames across video and image beats", () => {
  const frames = previewFramesFromTimeline({ beats: [
    { beat_id: "video_opening_a", media_type: "video", source: "assets/opening/a clip.mp4", duration: 4 },
    { beat_id: 1, media_type: "image", image: "assets/raw_beats/beat_001.png", duration: 2 },
    { beat_id: 2, media_type: "image", image: "assets/raw_beats/beat_002.png", duration: 2 },
  ] }, "/api/run/job/artifact", 10);
  assert.equal(frames.length, 10);
  assert.equal(frames[0].kind, "video");
  assert.equal(frames[0].mediaStart, 2);
  assert.match(frames[0].src, /a%20clip\.mp4$/);
  assert.ok(frames.some((frame) => frame.kind === "image"));
  assert.ok(frames.some((frame) => frame.label === "Image beat 2"));
});
