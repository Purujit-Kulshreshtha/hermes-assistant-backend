(() => {
  const button = $('voiceButton');
  const panel = $('voiceStatus');
  const label = $('voiceStatusText');
  const timer = $('voiceTimer');
  let recorder;
  let stream;
  let sessionId;
  let sequence = 0;
  let uploads = [];
  let startedAt = 0;
  let timerHandle;
  let starting = false;
  let stopping = false;
  let releasePending = false;

  function supportedMimeType() {
    return [
      'audio/webm;codecs=opus',
      'audio/ogg;codecs=opus',
      'audio/mp4',
      'audio/webm',
    ].find(type => MediaRecorder.isTypeSupported(type));
  }

  async function rawRequest(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        Authorization: `Bearer ${state.key}`,
        ...(options.headers || {}),
      },
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      throw new Error(payload.detail || `Request failed (${response.status})`);
    }
    return response;
  }

  function showState(text, recording = false) {
    panel.hidden = false;
    label.textContent = text;
    button.classList.toggle('recording', recording);
  }

  function updateTimer() {
    const seconds = Math.floor((Date.now() - startedAt) / 1000);
    timer.textContent = `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`;
    if (seconds >= 300) finishRecording(false);
  }

  function stopTracks() {
    stream?.getTracks().forEach(track => track.stop());
    stream = undefined;
  }

  function reset() {
    clearInterval(timerHandle);
    recorder = undefined;
    sessionId = undefined;
    sequence = 0;
    uploads = [];
    starting = false;
    stopping = false;
    releasePending = false;
    stopTracks();
    button.classList.remove('recording');
    button.disabled = false;
    $('sendButton').disabled = false;
    panel.hidden = true;
    timer.textContent = '0:00';
  }

  function uploadChunk(blob) {
    const current = sequence++;
    const upload = rawRequest(`/voice/sessions/${sessionId}/chunks/${current}`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/octet-stream'},
      body: blob,
    });
    uploads.push(upload);
    upload.catch(() => {});
  }

  async function startRecording() {
    if (starting || recorder || !state.key) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      addMessage('assistant', 'Voice recording is not supported by this browser.');
      return;
    }
    const mimeType = supportedMimeType();
    if (!mimeType) {
      addMessage('assistant', 'This browser has no supported voice-note format.');
      return;
    }
    starting = true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({audio: true});
      const session = await api('/voice/sessions', {
        method: 'POST',
        body: JSON.stringify({mime_type: mimeType}),
      });
      sessionId = session.id;
      recorder = new MediaRecorder(stream, {mimeType});
      recorder.addEventListener('dataavailable', event => {
        if (event.data.size && sessionId) uploadChunk(event.data);
      });
      recorder.start(1000);
      startedAt = Date.now();
      timerHandle = setInterval(updateTimer, 250);
      showState('Recording — release to send', true);
      button.disabled = false;
      $('sendButton').disabled = true;
      starting = false;
      if (releasePending) await finishRecording(false);
    } catch (error) {
      if (sessionId) {
        rawRequest(`/voice/sessions/${sessionId}`, {method: 'DELETE'}).catch(() => {});
      }
      reset();
      addMessage('assistant', `Voice recording failed: ${error.message}`);
    }
  }

  async function finishRecording(discard) {
    if (starting) {
      releasePending = true;
      return;
    }
    if (!recorder || stopping) return;
    stopping = true;
    clearInterval(timerHandle);
    const stopped = new Promise(resolve => {
      recorder.addEventListener('stop', resolve, {once: true});
    });
    recorder.stop();
    await stopped;
    stopTracks();
    button.classList.remove('recording');
    button.disabled = true;
    try {
      if (discard) {
        showState('Discarding…');
        await rawRequest(`/voice/sessions/${sessionId}`, {method: 'DELETE'});
        reset();
        return;
      }
      showState('Uploading final audio…');
      await Promise.all(uploads);
      showState('Transcribing on Oracle…');
      const result = await api(`/voice/sessions/${sessionId}/finalize`, {method: 'POST'});
      reset();
      await send(result.transcript);
    } catch (error) {
      const failedSession = sessionId;
      reset();
      addMessage('assistant', `Voice note failed: ${error.message}`);
      if (failedSession) {
        rawRequest(`/voice/sessions/${failedSession}`, {method: 'DELETE'}).catch(() => {});
      }
    }
  }

  button.addEventListener('pointerdown', event => {
    event.preventDefault();
    releasePending = false;
    button.setPointerCapture?.(event.pointerId);
    startRecording();
  });
  button.addEventListener('pointerup', event => {
    event.preventDefault();
    finishRecording(false);
  });
  button.addEventListener('pointercancel', () => finishRecording(true));
  $('cancelVoice').addEventListener('click', () => finishRecording(true));
  window.addEventListener('keydown', event => {
    if (event.key === 'Escape' && recorder) finishRecording(true);
  });
})();
