export const OUTBOX_STATUS = {
  SAVED_LOCALLY: 'saved_locally',
  UPLOADING: 'uploading',
  SYNCED: 'synced',
  NEEDS_RETRY: 'needs_retry',
};

export const OUTBOX_STATUS_LABEL = {
  [OUTBOX_STATUS.SAVED_LOCALLY]: 'Saved locally',
  [OUTBOX_STATUS.UPLOADING]: 'Routing',
  [OUTBOX_STATUS.SYNCED]: 'Captured and routed',
  [OUTBOX_STATUS.NEEDS_RETRY]: 'Saved · routing needs retry',
};

export function shouldUpload(entry) {
  return entry.serverFragmentId == null;
}

export function buildCaptureEntry({ id, blob, mimeType, extension, createdAt = Date.now(), kind = 'voice', rawText = '', title = '' }) {
  return {
    id,
    createdAt,
    kind,
    rawText,
    title,
    audioBlob: blob || null,
    mimeType: mimeType || (kind === 'typed' ? 'text/plain' : ''),
    extension: extension || (kind === 'typed' ? 'txt' : ''),
    status: OUTBOX_STATUS.SAVED_LOCALLY,
    retryCount: 0,
    lastError: null,
    serverFragmentId: null,
    fragmentUrl: null,
    transcriptionComplete: kind === 'typed',
  };
}

export function buildTypedCaptureEntry({ id, rawText, title = '', createdAt = Date.now() }) {
  return buildCaptureEntry({ id, createdAt, kind: 'typed', rawText, title });
}

export function isTypedCapture(entry) {
  return entry?.kind === 'typed';
}

async function routeOrRetry(current, deps) {
  const routing = await deps.routeCapture(current);
  if (routing?.ok) return null;
  const error = routing?.error || 'The Fragment is safe, but routing did not finish. It will retry.';
  await deps.updateEntry(current.id, {
    status: OUTBOX_STATUS.NEEDS_RETRY,
    lastError: error,
    retryCount: (current.retryCount || 0) + 1,
  });
  return {
    entry: {
      ...current,
      status: OUTBOX_STATUS.NEEDS_RETRY,
      lastError: error,
      retryCount: (current.retryCount || 0) + 1,
    },
    outcome: 'route_failed',
    uploaded: { id: current.serverFragmentId, url: current.fragmentUrl },
  };
}

async function processTypedCapture(entry, deps) {
  const { uploadCapture, updateEntry, removeEntry } = deps;
  let current = { ...entry };
  if (shouldUpload(current)) {
    await updateEntry(current.id, { status: OUTBOX_STATUS.UPLOADING, lastError: null });
    current = { ...current, status: OUTBOX_STATUS.UPLOADING, lastError: null };
    const uploaded = await uploadCapture(current);
    await updateEntry(current.id, {
      serverFragmentId: uploaded.id,
      fragmentUrl: uploaded.url,
      status: OUTBOX_STATUS.UPLOADING,
      lastError: null,
      transcriptionComplete: true,
    });
    current = {
      ...current,
      serverFragmentId: uploaded.id,
      fragmentUrl: uploaded.url,
      status: OUTBOX_STATUS.UPLOADING,
      lastError: null,
      transcriptionComplete: true,
    };
  }
  const routeFailure = await routeOrRetry(current, deps);
  if (routeFailure) return routeFailure;
  await updateEntry(current.id, { status: OUTBOX_STATUS.SYNCED, lastError: null });
  await removeEntry(current.id);
  return {
    entry: { ...current, status: OUTBOX_STATUS.SYNCED, lastError: null },
    outcome: 'synced',
    uploaded: { id: current.serverFragmentId, url: current.fragmentUrl },
  };
}

export async function processCaptureEntry(entry, deps) {
  if (isTypedCapture(entry)) {
    return processTypedCapture(entry, deps);
  }
  const { uploadCapture, transcribeCapture, updateEntry, removeEntry } = deps;
  let current = { ...entry };

  if (!shouldUpload(current)) {
    await updateEntry(current.id, { status: OUTBOX_STATUS.UPLOADING, lastError: null });
    current = { ...current, status: OUTBOX_STATUS.UPLOADING, lastError: null };
  } else {
    await updateEntry(current.id, {
      status: OUTBOX_STATUS.UPLOADING,
      lastError: null,
      retryCount: current.retryCount,
    });
    current = { ...current, status: OUTBOX_STATUS.UPLOADING, lastError: null };
    const uploaded = await uploadCapture(current);
    await updateEntry(current.id, {
      serverFragmentId: uploaded.id,
      fragmentUrl: uploaded.url,
      status: OUTBOX_STATUS.UPLOADING,
      lastError: null,
    });
    current = {
      ...current,
      serverFragmentId: uploaded.id,
      fragmentUrl: uploaded.url,
      status: OUTBOX_STATUS.UPLOADING,
      lastError: null,
    };
  }

  if (!current.transcriptionComplete) {
    const transcription = await transcribeCapture(current);
    if (!transcription.ok) {
      await updateEntry(current.id, {
        status: OUTBOX_STATUS.NEEDS_RETRY,
        lastError: transcription.error,
        retryCount: current.retryCount + 1,
      });
      return {
        entry: {
          ...current,
          status: OUTBOX_STATUS.NEEDS_RETRY,
          lastError: transcription.error,
          retryCount: current.retryCount + 1,
        },
        outcome: 'transcribe_failed',
        uploaded: { id: current.serverFragmentId, url: current.fragmentUrl },
      };
    }
    await updateEntry(current.id, { transcriptionComplete: true, lastError: null });
    current = { ...current, transcriptionComplete: true, lastError: null };
  }

  const routeFailure = await routeOrRetry(current, deps);
  if (routeFailure) return routeFailure;

  await updateEntry(current.id, { status: OUTBOX_STATUS.SYNCED, lastError: null });
  await removeEntry(current.id);
  return {
    entry: { ...current, status: OUTBOX_STATUS.SYNCED, lastError: null },
    outcome: 'synced',
    uploaded: { id: current.serverFragmentId, url: current.fragmentUrl },
  };
}

export function createMemoryStore() {
  /** @type {Map<string, object>} */
  const entries = new Map();

  return {
    async add(entry) {
      entries.set(entry.id, { ...entry });
    },
    async get(id) {
      const entry = entries.get(id);
      return entry ? { ...entry } : null;
    },
    async listAll() {
      return [...entries.values()]
        .map(entry => ({ ...entry }))
        .sort((a, b) => a.createdAt - b.createdAt);
    },
    async update(id, patch) {
      const existing = entries.get(id);
      if (!existing) throw new Error(`Missing outbox entry ${id}`);
      const next = { ...existing, ...patch };
      entries.set(id, next);
      return { ...next };
    },
    async remove(id) {
      entries.delete(id);
    },
  };
}

export function createOutboxController(store, network = {}) {
  let processing = false;

  const uploadCapture =
    network.uploadCapture ||
    (async () => {
      throw new Error('uploadCapture not configured');
    });
  const transcribeCapture =
    network.transcribeCapture ||
    (async () => {
      throw new Error('transcribeCapture not configured');
    });
  const routeCapture =
    network.routeCapture ||
    (async () => ({ ok: true }));

  async function enqueue(input) {
    const id = crypto.randomUUID();
    const entry = input.kind === 'typed' || input.rawText != null
      ? buildTypedCaptureEntry({ id, rawText: input.rawText || '', title: input.title || '' })
      : buildCaptureEntry({ id, blob: input.blob, mimeType: input.mimeType, extension: input.extension });
    await store.add(entry);
    return entry;
  }

  async function listPending() {
    const entries = await store.listAll();
    return entries.filter(entry => entry.status !== OUTBOX_STATUS.SYNCED);
  }

  async function processQueue(handlers = {}) {
    if (processing) return;
    processing = true;
    try {
      const pending = await listPending();
      for (const entry of pending) {
        handlers.onStatus?.(entry);
        try {
          const result = await processCaptureEntry(entry, {
            uploadCapture,
            transcribeCapture,
            routeCapture,
            updateEntry: (id, patch) => store.update(id, patch),
            removeEntry: id => store.remove(id),
          });
          handlers.onStatus?.(result.entry);
          if (result.outcome === 'synced') {
            handlers.onComplete?.(result.entry, result.uploaded);
          } else if (result.outcome === 'transcribe_failed') {
            handlers.onTranscribeFailed?.(result.entry, result.entry.lastError, result.uploaded);
          } else if (result.outcome === 'route_failed') {
            handlers.onRouteFailed?.(result.entry, result.entry.lastError, result.uploaded);
          }
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          const updated = await store.update(entry.id, {
            status: OUTBOX_STATUS.NEEDS_RETRY,
            lastError: message,
            retryCount: (entry.retryCount || 0) + 1,
          });
          handlers.onStatus?.(updated);
          handlers.onError?.(updated, error);
        }
      }
    } finally {
      processing = false;
    }
  }

  return {
    OUTBOX_STATUS,
    OUTBOX_STATUS_LABEL,
    enqueue,
    listPending,
    processQueue,
    shouldUpload,
    processCaptureEntry,
  };
}
