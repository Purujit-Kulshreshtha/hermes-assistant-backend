import {KokoroTTS} from 'https://cdn.jsdelivr.net/npm/kokoro-js@1.2.1/dist/kokoro.web.js';

const MODEL = 'onnx-community/Kokoro-82M-v1.0-ONNX';
let tts;
let device;

async function supportsWebGPU() {
  if (!self.navigator?.gpu) return false;
  try {
    return Boolean(await self.navigator.gpu.requestAdapter());
  } catch (_) {
    return false;
  }
}

async function initialize() {
  if (tts) return;
  device = await supportsWebGPU() ? 'webgpu' : 'wasm';
  try {
    tts = await KokoroTTS.from_pretrained(MODEL, {
      device,
      dtype: device === 'webgpu' ? 'fp32' : 'q8',
    });
  } catch (error) {
    if (device !== 'webgpu') throw error;
    device = 'wasm';
    tts = await KokoroTTS.from_pretrained(MODEL, {device, dtype: 'q8'});
  }
}

self.addEventListener('message', async event => {
  const message = event.data;
  try {
    await initialize();
    if (message.type === 'init') {
      self.postMessage({type: 'ready', device});
      return;
    }
    if (message.type === 'generate') {
      const audio = await tts.generate(message.text, {
        voice: message.voice,
        speed: message.speed,
      });
      self.postMessage({type: 'audio', id: message.id, audio: audio.toBlob()});
    }
  } catch (error) {
    self.postMessage({
      type: 'error',
      id: message.id,
      error: error?.message || String(error),
    });
  }
});
