const button = document.getElementById('recordButton');
const statusText = document.getElementById('recordStatus');
const previewEl = document.getElementById('liveTranscript');
let recorder;
let stream;
let chunks = [];
let recognition;

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
  const preferred = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
  recorder = new MediaRecorder(stream, preferred ? {mimeType: preferred} : undefined);
  chunks = [];
  previewEl.hidden = true;
  previewEl.textContent = '';
  recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
  recorder.onstop = saveFinishedRecording;
  recorder.start(1_000);
  startPreviewRecognition();
  setButtonState(true);
  statusText.textContent = 'Recording. Tap Stop when you are done.';
}

function stopRecording() {
  if (!recorder || recorder.state === 'inactive') return;
  // Stop the optional browser preview first. Nothing keeps listening after Stop.
  stopPreviewRecognition();
  statusText.textContent = 'Saving the original recording…';
  button.disabled = true;
  recorder.stop();
  stream?.getTracks().forEach(track => track.stop());
}

async function saveFinishedRecording() {
  const mimeType = recorder.mimeType || 'audio/webm';
  const extension = mimeType.includes('mp4') ? 'm4a' : 'webm';
  const blob = new Blob(chunks, {type: mimeType});
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
    const error = await transcription.text();
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
