const button = document.getElementById('recordButton');
const statusText = document.getElementById('recordStatus');
const previewEl = document.getElementById('liveTranscript');
let recorder;
let stream;
let chunks = [];
let recognition;
let recordedMimeType = '';
let recordingStartedAt = 0;
let foregroundCaptureId = null;

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

window.__fragmentsForegroundCaptureId = null;
window.__fragmentsIsRecording = () => Boolean(recorder && recorder.state !== 'inactive');

function setButtonState(recording) {
  button.classList.toggle('recording', recording);
  button.setAttribute('aria-label', recording ? 'Stop recording' : 'Start recording');
  button.innerHTML = recording
    ? '<span aria-hidden="true">■</span><span class="record-button-label">Stop</span>'
    : '<span aria-hidden="true">●</span><span class="record-button-label">Start</span>';
}

function resetCaptureUi() {
  chunks = [];
  button.disabled = false;
  setButtonState(false);
  statusText.textContent = 'Tap once to speak.';
}

function startPreviewRecognition() {
  if (!SpeechRecognition) return;
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-AU';
  recognition.onresult = event => {
    let preview = '';
    for (let i = event.resultIndex; i < event.results.length; i += 1) preview += event.results[i][0].transcript;
    if (preview.trim()) {
      previewEl.hidden = false;
      previewEl.textContent = `Rough preview — not saved: ${preview.trim()}`;
    }
  };
  recognition.onerror = () => {};
  try { recognition.start(); } catch (_) {}
}

function stopPreviewRecognition() {
  if (!recognition) return;
  try { recognition.abort(); } catch (_) {}
  recognition = undefined;
}

async function startRecording() {
  foregroundCaptureId = null;
  window.__fragmentsForegroundCaptureId = null;
  stream = await navigator.mediaDevices.getUserMedia({audio: true});
  // Safari may record MP4 while Chromium commonly records WebM.  Ask for a
  // supported format, then keep the type the recorder actually returns.
  const preferred = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm']
    .find(type => MediaRecorder.isTypeSupported(type));
  recorder = new MediaRecorder(stream, preferred ? {mimeType: preferred} : undefined);
  chunks = [];
  recordedMimeType = recorder.mimeType || preferred || '';
  recordingStartedAt = performance.now();
  previewEl.hidden = true;
  previewEl.textContent = '';
  recorder.ondataavailable = event => {
    if (!event.data || !event.data.size) return;
    chunks.push(event.data);
    if (event.data.type) recordedMimeType = event.data.type;
  };
  recorder.onstop = () => { void saveFinishedRecording(); };
  // Keep delivery continuous. iPhone Safari can otherwise return only a
  // container header when a short recording is stopped before its first
  // browser-managed flush.
  recorder.start(250);
  startPreviewRecognition();
  setButtonState(true);
  statusText.textContent = 'Recording. Tap Stop when you are done.';
}

function releaseRecordingStream() {
  stream?.getTracks().forEach(track => track.stop());
  stream = undefined;
  recorder = undefined;
}

function stopRecording() {
  if (!recorder || recorder.state === 'inactive') return;
  // Stop the optional browser preview first. Nothing keeps listening after Stop.
  stopPreviewRecognition();
  statusText.textContent = 'Saving the original recording…';
  button.disabled = true;
  // The final dataavailable event is delivered before onstop. Continuous
  // chunks above ensure the recording already contains real audio.
  recorder.stop();
}

async function saveFinishedRecording() {
  const mimeType = chunks.find(chunk => chunk.type)?.type || recordedMimeType || 'audio/webm';
  const extension = mimeType.includes('mp4') || mimeType.includes('m4a') ? 'm4a' : 'webm';
  const blob = new Blob(chunks, {type: mimeType});
  releaseRecordingStream();
  if (blob.size < 1_024) {
    const seconds = Math.max(0, (performance.now() - recordingStartedAt) / 1000).toFixed(1);
    statusText.textContent = `Only ${blob.size} bytes arrived after ${seconds}s. The phone did not deliver usable audio; please reload Fragments and try again.`;
    button.disabled = false;
    setButtonState(false);
    return;
  }

  if (!window.CaptureOutbox) {
    statusText.textContent = 'Capture storage is still loading. Please try again in a moment.';
    button.disabled = false;
    setButtonState(false);
    return;
  }

  try {
    const entry = await window.CaptureOutbox.enqueue({ blob, mimeType, extension });
    foregroundCaptureId = entry.id;
    window.__fragmentsForegroundCaptureId = entry.id;
    resetCaptureUi();
    statusText.textContent = 'Saved locally. Upload will continue in the background.';
    window.CaptureOutbox.refreshOutboxStatus?.();
    void window.CaptureOutbox.processQueue({
      onStatus: () => window.CaptureOutbox.refreshOutboxStatus?.(),
      onComplete: (completedEntry, uploaded) => {
        window.CaptureOutbox.refreshOutboxStatus?.();
        if (completedEntry.id === foregroundCaptureId && !window.__fragmentsIsRecording()) {
          window.location.assign(`${uploaded.url}?transcribed=1`);
        }
      },
      onTranscribeFailed: (failedEntry, error, uploaded) => {
        window.CaptureOutbox.refreshOutboxStatus?.();
        if (failedEntry.id === foregroundCaptureId && !window.__fragmentsIsRecording()) {
          sessionStorage.setItem('bloody-daves:fragments:transcription-error', error);
          window.location.assign(`${uploaded.url}?transcription=not-ready`);
        }
      },
      onError: () => window.CaptureOutbox.refreshOutboxStatus?.(),
    });
  } catch (error) {
    statusText.textContent = 'The recording could not be saved locally. Please try again.';
    button.disabled = false;
    setButtonState(false);
    console.error(error);
  }
}

button.addEventListener('click', async () => {
  try {
    if (!recorder || recorder.state === 'inactive') await startRecording();
    else stopRecording();
  } catch (error) {
    statusText.textContent = 'Microphone access is needed to record. You can still type a fragment below.';
    console.error(error);
  }
});
