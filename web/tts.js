(() => {
  class NancyTTS {
    constructor() {
      this.worker = null;
      this.readyPromise = null;
      this.pending = new Map();
      this.nextRequest = 1;
      this.generation = 0;
      this.audioContext = null;
      this.source = null;
      this.device = null;
    }

    setStatus(status, detail = '') {
      window.dispatchEvent(new CustomEvent('nancy-tts-status', {
        detail: {status, detail, device: this.device},
      }));
    }

    unlock() {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      if (!AudioContextClass) return;
      if (!this.audioContext) this.audioContext = new AudioContextClass();
      if (this.audioContext.state === 'suspended') this.audioContext.resume().catch(() => {});
    }

    ensureReady() {
      if (this.readyPromise) return this.readyPromise;
      this.setStatus('loading');
      this.worker = new Worker('/tts-worker.js', {type: 'module'});
      this.readyPromise = new Promise((resolve, reject) => {
        const fail = error => {
          this.setStatus('error', error.message || String(error));
          reject(error);
        };
        this.worker.addEventListener('error', fail, {once: true});
        this.worker.addEventListener('message', event => {
          const message = event.data;
          if (message.type === 'ready') {
            this.device = message.device;
            this.setStatus('ready');
            resolve();
            return;
          }
          if (message.type === 'error' && message.id == null) {
            const error = new Error(message.error);
            this.setStatus('error', error.message);
            reject(error);
            return;
          }
          if (message.type === 'audio' || message.type === 'error') {
            const request = this.pending.get(message.id);
            if (!request) return;
            this.pending.delete(message.id);
            if (message.type === 'audio') request.resolve(message.audio);
            else request.reject(new Error(message.error));
          }
        });
        this.worker.postMessage({type: 'init'});
      });
      return this.readyPromise;
    }

    prepare() {
      return this.ensureReady().catch(() => {});
    }

    generate(text, voice, speed) {
      const id = this.nextRequest++;
      return new Promise((resolve, reject) => {
        this.pending.set(id, {resolve, reject});
        this.worker.postMessage({type: 'generate', id, text, voice, speed});
      });
    }

    sentences(text) {
      const matches = text.trim().match(/[^.!?\n]+(?:[.!?]+|\n|$)/g) || [text];
      const pieces = [];
      for (const match of matches) {
        const sentence = match.trim();
        if (!sentence) continue;
        if (sentence.length <= 320) {
          pieces.push(sentence);
          continue;
        }
        for (let start = 0; start < sentence.length; start += 320) {
          pieces.push(sentence.slice(start, start + 320));
        }
      }
      return pieces;
    }

    async play(blob, generation) {
      this.unlock();
      if (!this.audioContext) throw new Error('Web Audio is unavailable');
      const buffer = await blob.arrayBuffer();
      const decoded = await this.audioContext.decodeAudioData(buffer.slice(0));
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
        try {
          source.start();
        } catch (error) {
          reject(error);
        }
      });
    }

    async speak(text, {voice = 'af_heart', speed = 1} = {}) {
      if (!text?.trim()) return;
      this.stop();
      const generation = this.generation;
      try {
        await this.ensureReady();
        for (const sentence of this.sentences(text)) {
          if (generation !== this.generation) return;
          this.setStatus('speaking');
          const audio = await this.generate(sentence, voice, speed);
          if (generation !== this.generation) return;
          await this.play(audio, generation);
        }
        if (generation === this.generation) this.setStatus('ready');
      } catch (error) {
        console.warn('Kokoro speech failed; using system speech', error);
        this.setStatus('fallback', error.message);
        if (generation === this.generation && 'speechSynthesis' in window) {
          const utterance = new SpeechSynthesisUtterance(text);
          utterance.rate = speed;
          speechSynthesis.speak(utterance);
        }
      }
    }

    stop() {
      this.generation += 1;
      if (this.source) {
        try { this.source.stop(); } catch (_) {}
        this.source = null;
      }
      if ('speechSynthesis' in window) speechSynthesis.cancel();
    }
  }

  window.nancyTTS = new NancyTTS();
})();
