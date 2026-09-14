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
  parseConfigGroup,
  serializeConfigGroup,
  statusClass,
  subtitleMarginPx,
  SUBTITLE_FONT_SUPPORTS_PERSIAN,
  SUBTITLE_POSITION_OFFSETS,
  validateLaunchValues,
} from "./studio-utils.js";

const clipboardGroup = {
  id: "subtitles",
  title: "Subtitles",
  fields: [
    { name: "show_subtitles", label: "Show", type: "toggle", default: false },
    { name: "subtitle_size", label: "Size", type: "number", min: 24, max: 100, default: 56 },
    { name: "subtitle_colour", label: "Colour", type: "color", default: "#FFFFFF" },
    { name: "locked", label: "Locked", type: "readonly", default: "provider" },
  ],
};

test("config groups round-trip through a readable versioned clipboard envelope", () => {
  const text = serializeConfigGroup(clipboardGroup, {
    show_subtitles: true,
    subtitle_size: "64",
    subtitle_colour: "#00E5FF",
    locked: "must not be copied",
  }, "2026-09-13T00:00:00.000Z");
  const payload = JSON.parse(text);
  assert.equal(payload.kind, "yt-video-generation-pipeline/config-group");
  assert.equal(payload.version, 1);
  assert.equal(payload.group_id, "subtitles");
  assert.equal(payload.settings.locked, undefined);
  assert.deepEqual(parseConfigGroup(text, clipboardGroup), {
    show_subtitles: true,
    subtitle_size: "64",
    subtitle_colour: "#00E5FF",
  });
});

test("config group paste rejects wrong sections, partial payloads, and invalid values atomically", () => {
  const valid = JSON.parse(serializeConfigGroup(clipboardGroup, {
    show_subtitles: true,
    subtitle_size: 64,
    subtitle_colour: "#FFFFFF",
  }));
  assert.throws(
    () => parseConfigGroup(JSON.stringify({ ...valid, group_id: "motion" }), clipboardGroup),
    /belong.*not/i,
  );
  const partial = structuredClone(valid);
  delete partial.settings.subtitle_size;
  assert.throws(() => parseConfigGroup(JSON.stringify(partial), clipboardGroup), /missing/i);
  const invalid = structuredClone(valid);
  invalid.settings.subtitle_size = 101;
  assert.throws(() => parseConfigGroup(JSON.stringify(invalid), clipboardGroup), /greater than 100/i);
  const extra = structuredClone(valid);
  extra.settings.injected = true;
  assert.throws(() => parseConfigGroup(JSON.stringify(extra), clipboardGroup), /unknown setting/i);
});

test("config group paste enforces cross-field section constraints", () => {
  const format = {
    id: "format",
    title: "Format",
    fields: [
      { name: "min_duration_seconds", label: "Minimum", type: "number", min: 15, max: 300 },
      { name: "max_duration_seconds", label: "Maximum", type: "number", min: 15, max: 300 },
      { name: "aspect_ratio", label: "Ratio", type: "select", options: [{ value: "9:16" }, { value: "16:9" }] },
    ],
  };
  const text = serializeConfigGroup(format, {
    min_duration_seconds: 80,
    max_duration_seconds: 40,
    aspect_ratio: "9:16",
  });
  assert.throws(() => parseConfigGroup(text, format), /Minimum duration/i);
  const landscape = serializeConfigGroup(format, {
    min_duration_seconds: 40,
    max_duration_seconds: 60,
    aspect_ratio: "16:9",
  });
  assert.throws(
    () => parseConfigGroup(landscape, format, { content_project: "q_station" }),
    /Q Station requires/i,
  );
});

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
