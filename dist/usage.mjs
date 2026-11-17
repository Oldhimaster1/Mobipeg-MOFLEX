// Aggregate counters only. No media, filenames, reports, or visitor identifiers.
const ENDPOINT = 'https://usage-stats.moflex.workers.dev/ingest';
const PREFERENCE = 'mobipeg-usage-opt-out';

export function createUsage(env = globalThis) {
  let viewSent = false;
  let optedOut = false;
  try { optedOut = env.localStorage?.getItem(PREFERENCE) === '1'; } catch {}
  const privacySignal = () => env.navigator?.globalPrivacyControl === true ||
    env.navigator?.doNotTrack === '1' || env.doNotTrack === '1';
  const enabled = () => !optedOut && !privacySignal();
  function send(payload) {
    // Local copies, previews, and tests never contribute to production counters.
    if (!enabled() || env.location?.origin !== 'https://oldhimaster1.github.io') return;
    try {
      Promise.resolve(env.fetch(ENDPOINT, {
        method: 'POST', mode: 'cors', credentials: 'omit', referrerPolicy: 'no-referrer',
        headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
        keepalive: true,
      })).catch(() => {}); // Counters must never interrupt conversion. No retries.
    } catch {}
  }
  return {
    enabled, privacySignal,
    setEnabled(value) {
      optedOut = !value;
      try { env.localStorage?.setItem(PREFERENCE, optedOut ? '1' : '0'); } catch {}
    },
    view() {
      if (viewSent || !enabled()) return;
      viewSent = true;
      send({type: 'view'});
    },
    conversion(duration, inputBytes, outputBytes) {
      if (!Number.isFinite(duration) || duration <= 0 || duration > 86400 ||
          !Number.isSafeInteger(inputBytes) || inputBytes <= 0 ||
          !Number.isSafeInteger(outputBytes) || outputBytes <= 0) return;
      send({type: 'conversion', duration: Math.max(1, Math.round(duration)), inputBytes, outputBytes});
    },
  };
}
