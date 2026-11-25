import test from 'node:test';
import assert from 'node:assert/strict';
import { buildFrameTimestamps, estimateFrameCount, LARGE_JOB_FRAME_THRESHOLD,
  validSamplingInterval } from '../src/videoSampling.js';

test('frame estimates match timestamps for regular and custom intervals', () => {
  for (const [duration, interval, expected] of [
    [300, 60, 5], [300, 10, 30], [300, 5, 60], [300, 20, 15],
    [121, 20, 7], [0.7, 1, 1],
  ]) {
    assert.equal(estimateFrameCount(duration, interval), expected);
    const timestamps = buildFrameTimestamps(duration, interval);
    assert.equal(timestamps.length, expected);
    assert.equal(timestamps[0], 0);
    assert.ok(timestamps.every((value) => value < duration));
  }
});

test('invalid intervals and durations are rejected', () => {
  for (const invalid of [0, -1, 0.5, 301, Infinity, NaN]) {
    assert.equal(validSamplingInterval(invalid), false);
    assert.equal(estimateFrameCount(300, invalid), null);
  }
  assert.equal(estimateFrameCount(0, 10), null);
  assert.throws(() => buildFrameTimestamps(120, 0));
});

test('large workload threshold is exceeded only above sixty frames', () => {
  assert.equal(estimateFrameCount(300, 5) > LARGE_JOB_FRAME_THRESHOLD, false);
  assert.equal(estimateFrameCount(301, 5) > LARGE_JOB_FRAME_THRESHOLD, true);
});
