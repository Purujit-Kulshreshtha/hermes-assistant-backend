(() => {
  class NancyTTS {
    constructor() {
      this.audioContext = null;
      this.source = null;
      this.controller = null;
      this.generation = 0;
      this.queue = [];
      this.draining = false;
    }

    setStatus(status, detail = '') {
      window.dispatchEvent(new CustomEvent('nancy-tts-status', {
        detail: {status, detail, device: 'oracle'},
      }));
    }

    unlock() {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      if (!this.audioContext) this.audioContext = new AudioContextClass();
      if (this.audioContext.state === 'suspended') this.audioContext.resume().catch(() => {});
    }

    prepare() { return Promise.resolve(); }

    async play(frame, generation) {
      this.unlock();
      if (!this.audioContext) throw new Error('Web Audio is unavailable');
      const decoded = await this.audioContext.decodeAudioData(frame.buffer.slice(
        frame.byteOffset, frame.byteOffset + frame.byteLength,
      ));
      if (generation !== this.generation) return;
      await new Promise((resolve, reject) => {
        const source = this.audioContext.createBufferSource();
        this.source = source;
        source.buffer = decoded;
        source.connect(this.audioContext.destination);
        source.onended = () => {
          if (this.source === source) this.source = null;
          resolve();
        };
        try { source.start(); } catch (error) { reject(error); }
      });
    }

    speak(text, {voice = 'af_heart', speed = 1, before = null} = {}) {
      if (!text?.trim()) return Promise.resolve(false);
      return new Promise(resolve => {
        this.queue.push({text, voice, speed, before, resolve});
        this.drain();
      });
    }

    async drain() {
      if (this.draining) return;
      this.draining = true;
      try {
        while (this.queue.length) {
          const item = this.queue.shift();
          if (item.before) item.before();
          await this.speakOne(item.text, item.voice, item.speed);
          item.resolve(true);
        }
      } finally {
        this.draining = false;
        if (!this.controller && !this.source) this.setStatus('ready');
      }
    }

    async speakOne(text, voice, speed) {
      const generation = this.generation;
      const controller = new AbortController();
      this.controller = controller;
      this.setStatus('loading');
      try {
        const response = await fetch('/tts/stream', {
          method: 'POST',
          headers: {
            Authorization: `Bearer ${state.key}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({text, voice, speed}),
          signal: controller.signal,
        });
        if (!response.ok) {
          const payload = await response.json().catch(() => ({}));
          throw new Error(payload.detail || `Speech failed (${response.status})`);
        }
        if (!response.body) throw new Error('Streaming audio is unavailable');

        const reader = response.body.getReader();
        let buffered = new Uint8Array(0);
        let expected = null;
        for (;;) {
          const {value, done} = await reader.read();
          if (done) break;
          const joined = new Uint8Array(buffered.length + value.length);
          joined.set(buffered);
          joined.set(value, buffered.length);
          buffered = joined;
          for (;;) {
            if (expected == null) {
              if (buffered.length < 4) break;
              expected = new DataView(buffered.buffer, buffered.byteOffset, 4).getUint32(0);
              buffered = buffered.slice(4);
            }
            if (buffered.length < expected) break;
            const frame = buffered.slice(0, expected);
            buffered = buffered.slice(expected);
            expected = null;
            if (generation !== this.generation) return;
            this.setStatus('speaking');
            await this.play(frame, generation);
          }
        }
      } catch (error) {
        if (error.name === 'AbortError' || generation !== this.generation) return;
        console.warn('Oracle speech failed; using system speech', error);
        this.setStatus('fallback', error.message);
        if ('speechSynthesis' in window) {
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.rate = speed;
          await new Promise(resolve => {
            utterance.onend = resolve;
            utterance.onerror = resolve;
            speechSynthesis.speak(utterance);
          });
        }
      } finally {
        if (this.controller === controller) this.controller = null;
      }
    }

    stop() {
      this.generation += 1;
      for (const item of this.queue.splice(0)) item.resolve(false);
      this.controller?.abort();
      this.controller = null;
      if (this.source) {
        try { this.source.stop(); } catch (_) {}
        this.source = null;
      }
      if ('speechSynthesis' in window) speechSynthesis.cancel();
      this.setStatus('stopped');
    }
  }

  window.nancyTTS = new NancyTTS();
})();
