import {
  OUTBOX_STATUS,
  OUTBOX_STATUS_LABEL,
  createOutboxController,
} from './captureOutboxLogic.mjs';

const DB_NAME = 'bloody-daves:fragments-outbox';
const DB_VERSION = 1;
const STORE_NAME = 'captures';

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains(STORE_NAME)) {
        db.createObjectStore(STORE_NAME, { keyPath: 'id' });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function withStore(mode, fn) {
  return openDb().then(
    db =>
      new Promise((resolve, reject) => {
        const tx = db.transaction(STORE_NAME, mode);
        const store = tx.objectStore(STORE_NAME);
        Promise.resolve(fn(store))
          .then(result => {
            tx.oncomplete = () => {
              db.close();
              resolve(result);
            };
            tx.onerror = () => {
              db.close();
              reject(tx.error);
            };
          })
          .catch(error => {
            db.close();
            reject(error);
          });
      }),
  );
}

function requestToPromise(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

const indexedDbStore = {
  add(entry) {
    return withStore('readwrite', store => requestToPromise(store.put(entry)));
  },
  get(id) {
    return withStore('readonly', store => requestToPromise(store.get(id)));
  },
  listAll() {
    return withStore('readonly', store =>
      requestToPromise(store.getAll()).then(entries =>
        entries.sort((a, b) => a.createdAt - b.createdAt),
      ),
    );
  },
  update(id, patch) {
    return withStore('readwrite', async store => {
      const existing = await requestToPromise(store.get(id));
      if (!existing) throw new Error(`Missing outbox entry ${id}`);
      const next = { ...existing, ...patch };
      await requestToPromise(store.put(next));
      return next;
    });
  },
  remove(id) {
    return withStore('readwrite', store => requestToPromise(store.delete(id)));
  },
};

async function responseErrorMessage(response, fallback) {
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) return fallback;
  try {
    const body = await response.json();
    const detail = String(body.detail || body.message || body.error || '').trim();
    return detail || fallback;
  } catch (_) {
    return fallback;
  }
}

async function transcriptionErrorMessage(response) {
  return responseErrorMessage(
    response,
    'Automatic transcription could not finish just yet. The original recording is safe. Open the Fragment and try Transcribe recording again.',
  );
}

async function uploadCapture(entry) {
  const form = new FormData();
  if (entry.kind === 'typed') {
    form.append('raw_transcript', entry.rawText || '');
    form.append('title', entry.title || '');
    form.append('capture_mode', 'typed');
    form.append('client_capture_id', entry.id);
  } else {
    form.append('audio', entry.audioBlob, `fragment.${entry.extension}`);
    form.append('raw_transcript', '');
    form.append('capture_mode', 'voice');
    form.append('client_capture_id', entry.id);
  }
  const saved = await fetch('/api/fragments', {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
  });
  if (!saved.ok) {
    throw new Error(await saved.text());
  }
  return saved.json();
}

async function transcribeCapture(entry) {
  const response = await fetch(`/api/fragments/${entry.serverFragmentId}/transcribe`, {
    method: 'POST',
    credentials: 'same-origin',
  });
  if (response.ok) {
    return { ok: true };
  }
  return { ok: false, error: await transcriptionErrorMessage(response) };
}

async function routeCapture(entry) {
  const fallback = 'The Fragment is safe, but automatic routing did not finish. It will retry.';
  const response = await fetch(`/api/fragments/${entry.serverFragmentId}/interpret`, {
    method: 'POST',
    credentials: 'same-origin',
  });
  if (!response.ok) {
    return { ok: false, error: await responseErrorMessage(response, fallback) };
  }
  let body;
  try {
    body = await response.json();
  } catch (_) {
    return { ok: false, error: fallback };
  }
  const engine = body?.routing_review?.capture_engine;
  if (!engine || engine.accepted !== true) {
    return { ok: false, error: engine?.message || fallback };
  }
  return { ok: true, body };
}

const controller = createOutboxController(indexedDbStore, {
  uploadCapture,
  transcribeCapture,
  routeCapture,
});

window.CaptureOutbox = {
  ...controller,
  OUTBOX_STATUS,
  OUTBOX_STATUS_LABEL,
};

function summarizeOutbox(entries) {
  if (!entries.length) return '';
  const latest = entries[entries.length - 1];
  const label = OUTBOX_STATUS_LABEL[latest.status] || latest.status;
  const pendingCount = entries.filter(entry => entry.status !== OUTBOX_STATUS.SYNCED).length;
  if (pendingCount <= 1) return label;
  return `${label} · ${pendingCount} captures waiting`;
}

async function refreshOutboxStatus() {
  const statusEl = document.getElementById('outboxStatus');
  if (!statusEl) return;
  const pending = await controller.listPending();
  const summary = summarizeOutbox(pending);
  if (!summary) {
    statusEl.hidden = true;
    statusEl.textContent = '';
    return;
  }
  statusEl.hidden = false;
  statusEl.textContent = summary;
}

window.CaptureOutbox.refreshOutboxStatus = refreshOutboxStatus;

function bindTypedCapture() {
  const form = document.querySelector('form.fragments-typed');
  if (!form || form.dataset.outboxBound) return;
  form.dataset.outboxBound = 'true';
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const rawText = String(form.raw_transcript?.value || '').trim();
    const title = String(form.title?.value || '').trim();
    if (!rawText) return;
    form.reset();
    await controller.enqueue({ kind: 'typed', rawText, title });
    await refreshOutboxStatus();
    void controller.processQueue({
      onStatus: () => refreshOutboxStatus(),
      onComplete: () => refreshOutboxStatus(),
      onRouteFailed: () => refreshOutboxStatus(),
      onError: () => refreshOutboxStatus(),
    });
  });
}

function bindOutboxLifecycle() {
  bindTypedCapture();
  const runQueue = () => {
    void controller.processQueue({
      onStatus: () => refreshOutboxStatus(),
      onComplete: (entry, uploaded) => {
        refreshOutboxStatus();
        if (entry.id === window.__fragmentsForegroundCaptureId && !window.__fragmentsIsRecording?.()) {
          window.location.assign(`${uploaded.url}?transcribed=1&routed=1`);
        }
      },
      onTranscribeFailed: (entry, error, uploaded) => {
        refreshOutboxStatus();
        if (entry.id === window.__fragmentsForegroundCaptureId && !window.__fragmentsIsRecording?.()) {
          sessionStorage.setItem('bloody-daves:fragments:transcription-error', error);
          window.location.assign(`${uploaded.url}?transcription=not-ready`);
        }
      },
      onRouteFailed: () => refreshOutboxStatus(),
      onError: () => refreshOutboxStatus(),
    });
  };

  window.addEventListener('online', runQueue);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') runQueue();
  });
  runQueue();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', bindOutboxLifecycle);
} else {
  bindOutboxLifecycle();
}
