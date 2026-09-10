import assert from "node:assert/strict";
import test from "node:test";

import {
  artifactUrl,
  dependentNodeIds,
  formatBytes,
  label,
  statusClass,
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
