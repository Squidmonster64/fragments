const button = document.getElementById('recordButton');
const statusText = document.getElementById('recordStatus');
const previewEl = document.getElementById('liveTranscript');
let recorder;
let stream;
let chunks = [];
let recognition;
let recordedMimeType = '';

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function setButtonState(recording) {
  button.classList.toggle('recording', recording);
  button.setAttribute('aria-label', recording ? 'Stop recording' : 'Start recording');
  button.innerHTML = recording
    ? '<span aria-hidden="true">■</span><span class="record-button-label">Stop</span>'
    : '<span aria-hidden="true">●</span><span class="record-button-label">Start</span>';
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
  stream = await navigator.mediaDevices.getUserMedia({audio: true});
  // Safari may record MP4 while Chromium commonly records WebM.  Ask for a
  // supported format, then keep the type the recorder actually returns.
  const preferred = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm']
    .find(type => MediaRecorder.isTypeSupported(type));
  recorder = new MediaRecorder(stream, preferred ? {mimeType: preferred} : undefined);
  chunks = [];
  recordedMimeType = recorder.mimeType || preferred || '';
  previewEl.hidden = true;
  previewEl.textContent = '';
  recorder.ondataavailable = event => {
    if (!event.data || !event.data.size) return;
    chunks.push(event.data);
    if (event.data.type) recordedMimeType = event.data.type;
  };
  recorder.onstop = () => { void saveFinishedRecording(); };
  // Do not use a one-second slice.  Some iPhone browsers can emit only a
  // container header when the microphone stream is released mid-slice.
  recorder.start();
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
  // Flush the final chunk before stopping.  The microphone remains live only
  // until MediaRecorder has finished the already-ended capture.
  try { recorder.requestData(); } catch (_) {}
  recorder.stop();
}

async function transcriptionErrorMessage(response) {
  const fallback = 'Automatic transcription could not finish just yet. The original recording is safe. Open the Fragment and try Transcribe recording again.';
  const contentType = response.headers.get('content-type') || '';
  if (!contentType.includes('application/json')) return fallback;
  try {
    const body = await response.json();
    const detail = String(body.detail || body.message || '').trim();
    return detail || fallback;
  } catch (_) {
    return fallback;
  }
}

async function saveFinishedRecording() {
  const mimeType = chunks.find(chunk => chunk.type)?.type || recordedMimeType || 'audio/webm';
  const extension = mimeType.includes('mp4') || mimeType.includes('m4a') ? 'm4a' : 'webm';
  const blob = new Blob(chunks, {type: mimeType});
  releaseRecordingStream();
  if (blob.size < 1_024) {
    statusText.textContent = 'That recording was too short to save. Please record again or type the words.';
    button.disabled = false;
    setButtonState(false);
    return;
  }
  const form = new FormData();
  form.append('audio', blob, `fragment.${extension}`);
  form.append('raw_transcript', '');
  form.append('capture_mode', 'voice');
  try {
    const saved = await fetch('/api/fragments', {method: 'POST', body: form});
    if (!saved.ok) throw new Error(await saved.text());
    const result = await saved.json();
    statusText.textContent = 'Transcribing the finished recording…';
    const transcription = await fetch(`/api/fragments/${result.id}/transcribe`, {method: 'POST'});
    if (transcription.ok) {
      window.location.assign(`${result.url}?transcribed=1`);
      return;
    }
    const error = await transcriptionErrorMessage(transcription);
    sessionStorage.setItem('bloody-daves:fragments:transcription-error', error);
    window.location.assign(`${result.url}?transcription=not-ready`);
  } catch (error) {
    statusText.textContent = 'The recording could not be saved. Keep this page open and try again.';
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
