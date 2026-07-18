const button = document.getElementById('recordButton');
const statusText = document.getElementById('recordStatus');
const transcriptEl = document.getElementById('liveTranscript');
let recorder, stream, chunks = [], recognition, transcript = '';

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

function startRecognition() {
  if (!SpeechRecognition) return;
  recognition = new SpeechRecognition();
  recognition.continuous = true;
  recognition.interimResults = true;
  recognition.lang = 'en-AU';
  recognition.onresult = event => {
    let interim = '';
    for (let i = event.resultIndex; i < event.results.length; i++) {
      const text = event.results[i][0].transcript;
      if (event.results[i].isFinal) transcript += text + ' ';
      else interim += text;
    }
    transcriptEl.textContent = (transcript + interim).trim();
  };
  recognition.onerror = () => {};
  recognition.start();
}

async function startRecording() {
  stream = await navigator.mediaDevices.getUserMedia({audio: true});
  const preferred = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') ? 'audio/webm;codecs=opus' : '';
  recorder = new MediaRecorder(stream, preferred ? {mimeType: preferred} : undefined);
  chunks = []; transcript = ''; transcriptEl.textContent = '';
  recorder.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recorder.onstop = saveRecording;
  recorder.start(1000);
  startRecognition();
  button.classList.add('recording');
  button.textContent = '■';
  statusText.textContent = 'Recording — tap to save';
}

function stopRecording() {
  statusText.textContent = 'Saving original audio…';
  button.disabled = true;
  if (recognition) { try { recognition.stop(); } catch (_) {} }
  recorder.stop();
  stream.getTracks().forEach(track => track.stop());
}

async function saveRecording() {
  const mimeType = recorder.mimeType || 'audio/webm';
  const extension = mimeType.includes('mp4') ? 'm4a' : 'webm';
  const blob = new Blob(chunks, {type: mimeType});
  const form = new FormData();
  form.append('audio', blob, `recording.${extension}`);
  form.append('raw_transcript', transcript.trim());
  try {
    const response = await fetch('/api/fragments', {method:'POST', body:form});
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    window.location.href = result.url;
  } catch (error) {
    statusText.textContent = 'Save failed. Keep this page open and try again.';
    button.disabled = false;
    console.error(error);
  }
}

button.addEventListener('click', async () => {
  try {
    if (!recorder || recorder.state === 'inactive') await startRecording();
    else stopRecording();
  } catch (error) {
    statusText.textContent = 'Microphone access is required.';
    console.error(error);
  }
});
