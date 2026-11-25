// Shared by the upload form's estimate and the video-frame extractor.
// The first frame is always sampled at 0 seconds; the last sample is before the end.
export const LARGE_JOB_FRAME_THRESHOLD = 60;

export function validSamplingInterval(seconds) {
  return Number.isInteger(seconds) && seconds >= 1 && seconds <= 300;
}

export function estimateFrameCount(duration, intervalSeconds) {
  if (!Number.isFinite(duration) || duration <= 0 || !validSamplingInterval(intervalSeconds)) {
    return null;
  }
  return Math.ceil(duration / intervalSeconds);
}

export function buildFrameTimestamps(duration, intervalSeconds) {
  const count = estimateFrameCount(duration, intervalSeconds);
  if (count === null) throw new Error('Video duration or sample interval is invalid.');
  return Array.from({ length: count }, (_, index) => index * intervalSeconds);
}
