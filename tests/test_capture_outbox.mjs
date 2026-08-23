import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  OUTBOX_STATUS,
  buildCaptureEntry,
  createMemoryStore,
  createOutboxController,
  processCaptureEntry,
  shouldUpload,
} from '../app/static/captureOutboxLogic.mjs';

test('buildCaptureEntry persists required outbox fields', async () => {
  const blob = new Blob(['audio-bytes'], { type: 'audio/webm' });
  const entry = buildCaptureEntry({
    id: 'local-1',
    blob,
    mimeType: 'audio/webm',
    extension: 'webm',
    createdAt: 123,
  });

  assert.equal(entry.id, 'local-1');
  assert.equal(entry.createdAt, 123);
  assert.equal(entry.mimeType, 'audio/webm');
  assert.equal(entry.extension, 'webm');
  assert.equal(entry.status, OUTBOX_STATUS.SAVED_LOCALLY);
  assert.equal(entry.retryCount, 0);
  assert.equal(entry.lastError, null);
  assert.equal(entry.serverFragmentId, null);
});

test('enqueue stores capture in memory store', async () => {
  const store = createMemoryStore();
  const controller = createOutboxController(store);
  const blob = new Blob(['audio-bytes'], { type: 'audio/webm' });
  const entry = await controller.enqueue({ blob, mimeType: 'audio/webm', extension: 'webm' });
  const stored = await store.get(entry.id);

  assert.ok(stored);
  assert.equal(stored.status, OUTBOX_STATUS.SAVED_LOCALLY);
  assert.equal(stored.audioBlob.size, blob.size);
});

test('retry skips upload when server fragment already exists', async () => {
  const store = createMemoryStore();
  let uploadCalls = 0;
  const entry = buildCaptureEntry({
    id: 'local-2',
    blob: new Blob(['audio'], { type: 'audio/webm' }),
    mimeType: 'audio/webm',
    extension: 'webm',
  });
  entry.serverFragmentId = 42;
  entry.fragmentUrl = '/fragments/42';
  await store.add(entry);

  const result = await processCaptureEntry(entry, {
    uploadCapture: async () => {
      uploadCalls += 1;
      return { id: 99, url: '/fragments/99' };
    },
    transcribeCapture: async () => ({ ok: true }),
    updateEntry: (id, patch) => store.update(id, patch),
    removeEntry: id => store.remove(id),
  });

  assert.equal(uploadCalls, 0);
  assert.equal(result.outcome, 'synced');
  assert.equal(await store.get(entry.id), null);
});

test('processQueue retries upload failures and does not duplicate server fragments', async () => {
  const store = createMemoryStore();
  let uploadCalls = 0;
  const controller = createOutboxController(store, {
    uploadCapture: async entry => {
      uploadCalls += 1;
      if (uploadCalls === 1) throw new Error('offline');
      return { id: 7, url: '/fragments/7' };
    },
    transcribeCapture: async () => ({ ok: true }),
  });

  await controller.enqueue({
    blob: new Blob(['audio'], { type: 'audio/webm' }),
    mimeType: 'audio/webm',
    extension: 'webm',
  });

  await controller.processQueue();
  const pendingAfterFailure = await controller.listPending();
  assert.equal(pendingAfterFailure.length, 1);
  assert.equal(pendingAfterFailure[0].status, OUTBOX_STATUS.NEEDS_RETRY);
  assert.equal(uploadCalls, 1);

  await controller.processQueue();
  assert.equal(uploadCalls, 2);
  assert.equal((await controller.listPending()).length, 0);
});

test('transcribe failure keeps uploaded fragment id for safe retry', async () => {
  const store = createMemoryStore();
  let transcribeCalls = 0;
  const controller = createOutboxController(store, {
    uploadCapture: async () => ({ id: 11, url: '/fragments/11' }),
    transcribeCapture: async () => {
      transcribeCalls += 1;
      return transcribeCalls === 1
        ? { ok: false, error: 'provider unavailable' }
        : { ok: true };
    },
  });

  await controller.enqueue({
    blob: new Blob(['audio'], { type: 'audio/webm' }),
    mimeType: 'audio/webm',
    extension: 'webm',
  });

  await controller.processQueue();
  const retryable = await controller.listPending();
  assert.equal(retryable.length, 1);
  assert.equal(retryable[0].serverFragmentId, 11);
  assert.equal(retryable[0].status, OUTBOX_STATUS.NEEDS_RETRY);
  assert.equal(shouldUpload(retryable[0]), false);

  await controller.processQueue();
  assert.equal((await controller.listPending()).length, 0);
  assert.equal(transcribeCalls, 2);
});

console.log('capture outbox tests passed');
